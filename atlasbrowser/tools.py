"""Page tools: reader mode, AI page translation, screenshots and picture-in-picture.

Reader mode writes a clean copy of the article to the profile's reader/ folder and shows that file; its toolbar
links (?pelagic=reader-…) are caught by WebPage.acceptNavigationRequest like the homepage's.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from PySide6.QtCore import QRect, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import providers
from .agent import run_in_pool

# ------------------------------------------------------------------ reader mode
READER_JS = r"""
(function () {
  var DROP = /comment|share|social|related|promo|advert|(^|[-_ ])ad([-_ ]|$)|newsletter|subscribe|footer|sidebar|nav|menu|cookie|banner|popup|modal/i;
  function textLen(el) { return (el.innerText || '').trim().length; }
  var best = null, bestScore = 0;
  var cands = document.querySelectorAll('article, main, [role=main], [itemprop=articleBody], .post, .entry-content, .article, .content, div, section');
  for (var i = 0; i < cands.length && i < 4000; i++) {
    var el = cands[i], ps = el.querySelectorAll('p'), score = 0;
    for (var j = 0; j < ps.length; j++) { var n = textLen(ps[j]); if (n > 40) score += n; }
    if (/^(ARTICLE|MAIN)$/.test(el.tagName)) score *= 1.3;
    score -= 0.25 * (textLen(el) - score > 0 ? Math.min(textLen(el) - score, score) : 0);
    if (score > bestScore) { bestScore = score; best = el; }
  }
  if (!best || bestScore < 400) return JSON.stringify({ ok: false });
  var KEEP = { P:1, H1:1, H2:1, H3:1, H4:1, H5:1, H6:1, UL:1, OL:1, LI:1, BLOCKQUOTE:1, PRE:1, CODE:1, EM:1, STRONG:1,
               B:1, I:1, A:1, IMG:1, FIGURE:1, FIGCAPTION:1, BR:1, HR:1, TABLE:1, THEAD:1, TBODY:1, TR:1, TD:1, TH:1, SUP:1, SUB:1 };
  var SKIP = { SCRIPT:1, STYLE:1, NOSCRIPT:1, NAV:1, ASIDE:1, FOOTER:1, FORM:1, BUTTON:1, IFRAME:1, SVG:1, INPUT:1,
               SELECT:1, TEXTAREA:1, HEADER:1, DIALOG:1 };
  function clean(node, out) {
    for (var c = node.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) { out.push(c.textContent.replace(/[&<>]/g, function (m) { return {'&':'&amp;','<':'&lt;','>':'&gt;'}[m]; })); continue; }
      if (c.nodeType !== 1 || SKIP[c.tagName]) continue;
      var tag = c.tagName, label = (c.className && c.className.baseVal === undefined ? c.className : '') + ' ' + (c.id || '');
      if (tag !== 'P' && DROP.test(label) && textLen(c) < 2000) continue;
      if (getComputedStyle(c).display === 'none') continue;
      if (!KEEP[tag]) { clean(c, out); if (/^(DIV|SECTION)$/.test(tag)) out.push('\n'); continue; }
      if (tag === 'IMG') {
        var src = c.currentSrc || c.src;
        if (src && (c.naturalWidth || c.width) > 80) out.push('<img src="' + src.replace(/"/g, '&quot;') + '" alt="">');
        continue;
      }
      if (tag === 'BR' || tag === 'HR') { out.push('<' + tag.toLowerCase() + '>'); continue; }
      var open = '<' + tag.toLowerCase();
      if (tag === 'A' && c.href && /^https?:/.test(c.href)) open += ' href="' + c.href.replace(/"/g, '&quot;') + '"';
      out.push(open + '>'); clean(c, out); out.push('</' + tag.toLowerCase() + '>');
    }
  }
  var out = []; clean(best, out);
  var h1 = document.querySelector('h1');
  var by = document.querySelector('[rel=author], .author, .byline, [itemprop=author]');
  var site = (document.querySelector('meta[property="og:site_name"]') || {}).content || location.hostname;
  return JSON.stringify({ ok: true, title: (h1 && h1.innerText.trim()) || document.title, byline: by ? by.innerText.trim().slice(0, 120) : '',
                          site: site, html: out.join(''), url: location.href, words: (best.innerText || '').split(/\s+/).length });
})()
"""

THEMES = {"dark": ("#16181d", "#e6e8ee", "#8fd8cf"), "light": ("#ffffff", "#1d1f24", "#1B8C9A"),
          "sepia": ("#f4ecd8", "#3b3024", "#8a5a2b")}


def reader_folder(store) -> Path:
    d = store.root / "reader"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_reader(url: QUrl) -> bool:
    return url.isLocalFile() and url.fileName().startswith("reader-")


def page_url(tab) -> QUrl:
    """The address to show and save for a tab: a reader view stands for the page it was made from."""
    url = tab.url()
    src = getattr(tab, "_reader_source", "")
    if src and is_reader(url):
        return QUrl(src)
    from .fileview import source_of
    shown = source_of(url)
    if shown is not None:
        return shown            # the file view stands for the file itself
    blocked = getattr(tab, "_unsafe_target", "")
    if blocked and url.isLocalFile() and url.fileName().startswith("unsafe-"):
        return QUrl(blocked)    # an unsafe-site warning stands for the address it stopped
    return url


def parse_reader_action(url: QUrl) -> str | None:
    """'reader-…' for a toolbar link on a reader page, else None."""
    if not is_reader(url):
        return None
    q = dict(p.split("=", 1) for p in url.query().split("&") if "=" in p)
    act = q.get("pelagic", "")
    return act if act.startswith("reader-") else None


def build_reader(store, art: dict) -> str:
    theme = store.get("reader_theme") or "dark"
    bg, fg, link = THEMES.get(theme, THEMES["dark"])
    size = int(store.get("reader_size") or 19)
    serif = store.get("reader_font") != "sans"
    body = re.sub(r"(\s*\n\s*){2,}", "\n", art.get("html", ""))
    title = (art.get("title") or "").strip()
    body = re.sub(r"^\s*<h1>(.*?)</h1>", lambda m: "" if html.unescape(re.sub("<[^>]+>", "", m.group(1))).strip() == title
                  else m.group(0), body, count=1, flags=re.S)   # the title is already shown above the article
    minutes = max(1, round(int(art.get("words") or 0) / 230))
    btn = lambda act, text, tip: (f'<a class="b" href="?pelagic=reader-{act}" title="{tip}">{text}</a>')   # noqa: E731
    bar = "".join([
        btn("exit", "✕ Exit reader", "Back to the normal page (F9)"),
        '<span class="sp"></span>',
        btn("summarize", "✦ Summarize with AI", "Ask Pelagic AI for the key points"),
        btn("smaller", "A−", "Smaller text"), btn("bigger", "A+", "Bigger text"),
        btn("font", "Sans" if serif else "Serif", "Switch font"),
        btn("theme-dark", "Dark", "Dark background"), btn("theme-sepia", "Sepia", "Warm paper background"),
        btn("theme-light", "Light", "White background")])
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(art.get('title') or 'Reader')}</title>
<meta name="pelagic-source" content="{html.escape(art.get('url', ''))}">
<style>
body{{margin:0;background:{bg};color:{fg};font:{size}px/1.7 {"Georgia,'Times New Roman',serif" if serif else "'Segoe UI',sans-serif"}}}
.bar{{position:sticky;top:0;display:flex;gap:6px;align-items:center;padding:8px 14px;background:{bg}ee;
border-bottom:1px solid {fg}22;font:13px 'Segoe UI',sans-serif;backdrop-filter:blur(6px)}}.sp{{flex:1}}
.b{{color:{fg};text-decoration:none;padding:5px 10px;border-radius:8px;border:1px solid {fg}22}}.b:hover{{background:{fg}14}}
.b[href$="theme-{theme}"]{{border-color:{link};color:{link}}}
main{{max-width:700px;margin:0 auto;padding:36px 22px 90px}}
h1.t{{font-size:1.9em;line-height:1.25;margin:0 0 10px}}.meta{{opacity:.65;font:14px 'Segoe UI',sans-serif;margin-bottom:28px}}
a{{color:{link}}}img{{max-width:100%;height:auto;border-radius:6px;margin:12px 0}}
pre{{overflow:auto;background:{fg}10;padding:12px;border-radius:8px;font-size:.8em}}
blockquote{{border-left:3px solid {link};margin:1em 0;padding:.2em 1em;opacity:.9}}
table{{border-collapse:collapse}}td,th{{border:1px solid {fg}33;padding:4px 8px}}
</style>
<div class="bar">{bar}</div>
<main><h1 class="t">{html.escape(art.get('title') or '')}</h1>
<div class="meta">{html.escape(art.get('site') or '')}{(' · ' + html.escape(art['byline'])) if art.get('byline') else ''} · {minutes} min read</div>
{body}</main>"""


def reader_action(win, tab, action: str):
    store = win.store
    if action == "reader-exit":
        toggle_reader(win, tab)
        return
    if action == "reader-summarize":
        win.toggle_panel(True)
        win.panel.ask_about("page", "")
        return
    if action in ("reader-bigger", "reader-smaller"):
        size = int(store.get("reader_size") or 19) + (1 if action == "reader-bigger" else -1)
        store.set("reader_size", max(13, min(32, size)))
    elif action == "reader-font":
        store.set("reader_font", "serif" if store.get("reader_font") == "sans" else "sans")
    elif action.startswith("reader-theme-"):
        store.set("reader_theme", action.removeprefix("reader-theme-"))
    art = getattr(tab, "_reader_article", None)
    if art:
        _show_reader(win, tab, art)


def toggle_reader(win, tab=None):
    """F9: show the page as a clean article, or go back to the normal page."""
    tab = tab or win.current_tab()
    if tab is None:
        return
    if is_reader(tab.url()):
        src = getattr(tab, "_reader_source", "")
        tab.load(QUrl(src)) if src else tab.back()
        return
    if tab.url().scheme() not in ("http", "https"):
        return

    def got(raw):
        try:
            art = json.loads(raw) if raw else {}
        except ValueError:
            art = {}
        if not art.get("ok"):
            win.notify("Reader mode couldn't find an article on this page.")
            QTimer.singleShot(4000, win.notice.hide)
            return
        tab._reader_article = art
        tab._reader_source = art["url"]
        _show_reader(win, tab, art)
    tab.run_js(READER_JS, got)


def _show_reader(win, tab, art):
    path = reader_folder(win.store) / f"reader-{id(tab):x}.html"
    path.write_text(build_reader(win.store, art), encoding="utf-8")
    url = QUrl.fromLocalFile(str(path))
    if tab.url() == url:
        tab.reload()
    else:
        tab.load(url)


# ------------------------------------------------------------------ translate
LANGUAGES = ["English", "Spanish", "French", "German", "Portuguese", "Italian", "Chinese (Simplified)", "Japanese",
             "Korean", "Arabic", "Hindi", "Russian", "Vietnamese", "Tagalog", "Dutch", "Polish", "Turkish", "Ukrainian"]

COLLECT_JS = r"""
(function () {
  var SKIP = { SCRIPT:1, STYLE:1, NOSCRIPT:1, CODE:1, PRE:1, TEXTAREA:1, INPUT:1, SELECT:1, OPTION:1, SVG:1 };
  var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: function (n) {
    var p = n.parentElement; if (!p || SKIP[p.tagName] || p.isContentEditable) return NodeFilter.FILTER_REJECT;
    var t = n.textContent.trim(); if (t.length < 2 || !/[A-Za-zÀ-ɏͰ-῿぀-￯]/.test(t)) return NodeFilter.FILTER_REJECT;
    return NodeFilter.FILTER_ACCEPT; } });
  var nodes = [], texts = [], total = 0;
  while (w.nextNode() && total < 60000) { nodes.push(w.currentNode); texts.push(w.currentNode.textContent); total += w.currentNode.textContent.length; }
  window.__pelagicTr = { nodes: nodes, orig: texts.slice() };
  return JSON.stringify(texts);
})()
"""
APPLY_JS = r"""
(function (start, out) {
  var s = window.__pelagicTr; if (!s) return 0;
  for (var i = 0; i < out.length; i++) {
    var n = s.nodes[start + i]; if (!n || typeof out[i] !== 'string') continue;
    var o = s.orig[start + i], lead = o.match(/^\s*/)[0], tail = o.match(/\s*$/)[0];
    n.textContent = lead + out[i].trim() + tail;
  }
  document.documentElement.dataset.pelagicTranslated = '1';
  return out.length;
})(%s, %s)
"""
RESTORE_JS = r"""
(function () { var s = window.__pelagicTr; if (!s) return false;
  for (var i = 0; i < s.nodes.length; i++) s.nodes[i].textContent = s.orig[i];
  delete document.documentElement.dataset.pelagicTranslated; return true; })()
"""
BATCH_CHARS = 6000


def translate_system(lang: str) -> str:
    return (f"You translate web page text into {lang}. You get a JSON array of strings. Reply with ONLY a JSON array "
            f"of the same length, in the same order, each string translated into {lang}. Keep names, numbers, URLs "
            f"and emoji. Strings already in {lang} stay as they are.")


def parse_array(text: str, n: int):
    m = re.search(r"\[.*\]", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return out if isinstance(out, list) and len(out) == n else None


def batches(texts: list[str]) -> list[tuple[int, list[str]]]:
    out, start, cur, size = [], 0, [], 0
    for i, t in enumerate(texts):
        if cur and size + len(t) > BATCH_CHARS:
            out.append((start, cur))
            start, cur, size = i, [], 0
        cur.append(t)
        size += len(t)
    if cur:
        out.append((start, cur))
    return out


def translate_page(win, lang: str | None = None, ask: bool = True):
    """Translates the page's text in place with the AI service chosen in the panel. Translate again → original."""
    tab = win.current_tab()
    if tab is None:
        return
    if getattr(tab, "_translated", False):
        tab.run_js(RESTORE_JS)
        tab._translated = False
        win.notify("Showing the original page.")
        QTimer.singleShot(3000, win.notice.hide)
        return
    store = win.store
    if lang is None:
        lang = store.get("translate_to") or "English"
        if ask:
            items = LANGUAGES if lang in LANGUAGES else [lang] + LANGUAGES
            lang, ok = QInputDialog.getItem(win, "Translate page", "Translate this page into:", items,
                                            items.index(lang), True)
            if not ok or not lang.strip():
                return
            lang = lang.strip()
            store.set("translate_to", lang)
    p = win.panel.current_provider()
    key = providers.resolve_key(store, p) if p else ""
    if p is None or (p.needs_key and not key):
        win.notify("Translating uses your AI service. Open the AI panel (Ctrl+Shift+A) and add an API key first.")
        return
    win.notify(f"Translating to {lang} with {p.name}…")
    token = time.monotonic()
    tab._translate_token = token

    def collected(raw):
        try:
            texts = json.loads(raw) if raw else []
        except ValueError:
            texts = []
        if not texts:
            win.notify("There's no text to translate on this page.")
            return
        jobs = batches(texts)
        state = {"left": len(jobs), "failed": 0}
        for start, chunk in jobs:
            def done(_tok, out, start=start, chunk=chunk):
                if getattr(tab, "_translate_token", None) != token:
                    return
                arr = None if isinstance(out, Exception) else parse_array(out, len(chunk))
                if arr is None:
                    state["failed"] += 1
                else:
                    tab.run_js(APPLY_JS % (start, json.dumps(arr)))
                    tab._translated = True
                state["left"] -= 1
                if state["left"] == 0:
                    if not state["failed"]:
                        msg = f"Translated to {lang}. Use Translate page again to see the original."
                    elif state["failed"] == len(jobs):
                        msg = "The translation didn't work. The AI panel's Raw view shows what the AI sent back."
                    else:
                        msg = f"Translated most of the page to {lang} ({state['failed']} part(s) failed)."
                    win.notify(msg)
            run_in_pool(0, lambda chunk=chunk: providers.chat(
                p, key, [{"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}],
                translate_system(lang), max_tokens=8000, meter=win.panel.session), done)
    tab.run_js(COLLECT_JS, collected)


# ------------------------------------------------------------------ screenshots
def pictures_folder() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
    d = Path(base) / "Pelagic Screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ScreenshotDialog(QDialog):
    """Preview of a capture. It's already on the clipboard; Save keeps a copy."""

    def __init__(self, pix: QPixmap, title: str, parent=None):
        super().__init__(parent)
        self.pix, self.title = pix, title
        self.setWindowTitle("Screenshot")
        self.resize(760, 560)
        QGuiApplication.clipboard().setPixmap(pix)
        lab = QLabel()
        lab.setPixmap(pix.scaledToWidth(min(pix.width(), 700), Qt.SmoothTransformation))
        area = QScrollArea()
        area.setWidget(lab)
        area.setAlignment(Qt.AlignHCenter)
        note = QLabel(f"{pix.width()} × {pix.height()} — copied to the clipboard. Paste it anywhere with Ctrl+V.")
        note.setObjectName("muted")
        row = QHBoxLayout()
        save = QPushButton("Save to Pictures")
        save.setObjectName("primary")
        save.clicked.connect(self.save_default)
        save_as = QPushButton("Save as…")
        save_as.clicked.connect(self.save_as)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(note, 1)
        row.addWidget(save_as)
        row.addWidget(save)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(area, 1)
        lay.addLayout(row)
        self.saved: Path | None = None

    def _name(self):
        safe = re.sub(r'[\\/:*?"<>|]+', " ", self.title).strip()[:60] or "Screenshot"
        return f"{safe} {time.strftime('%Y-%m-%d %H.%M.%S')}.png"

    def save_default(self):
        self.saved = pictures_folder() / self._name()
        self.pix.save(str(self.saved), "PNG")
        self.accept()

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save screenshot", str(pictures_folder() / self._name()),
                                              "PNG image (*.png);;JPEG image (*.jpg)")
        if path:
            self.pix.save(path)
            self.saved = Path(path)
            self.accept()


class AreaPicker(QWidget):
    """Drag over the page to pick an area. Enter = whole visible page, Esc = cancel."""

    def __init__(self, tab, frozen: QPixmap, done):
        super().__init__(tab)
        self.frozen, self.done = frozen, done
        self.start = self.end = None
        self.setGeometry(tab.rect())
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.show()
        self.raise_()
        self.setFocus()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.frozen)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        r = self.sel()
        if r is not None:
            p.drawPixmap(r, self.frozen, self._src(r))
            p.setPen(QPen(QColor("#5FE0CF"), 2))
            p.drawRect(r)
        else:
            p.setPen(QColor("#ffffff"))
            p.drawText(self.rect(), Qt.AlignCenter, "Drag to select an area\nEnter: whole visible page · Esc: cancel")
        p.end()

    def _src(self, r: QRect) -> QRect:
        k = self.frozen.width() / max(1, self.width())
        return QRect(int(r.x() * k), int(r.y() * k), int(r.width() * k), int(r.height() * k))

    def sel(self):
        if self.start is None or self.end is None:
            return None
        return QRect(self.start, self.end).normalized()

    def mousePressEvent(self, ev):
        self.start = self.end = ev.position().toPoint()
        self.update()

    def mouseMoveEvent(self, ev):
        if self.start is not None:
            self.end = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev):
        r = self.sel()
        if r is not None and r.width() > 4 and r.height() > 4:
            self._finish(self.frozen.copy(self._src(r)))
        else:
            self.start = self.end = None
            self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self._finish(None)
        elif ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish(self.frozen)

    def _finish(self, pix):
        self.hide()
        self.deleteLater()
        self.done(pix)


def grab_visible(tab) -> QPixmap:
    return tab.grab()


def grab_full_page(tab, done, max_screens: int = 25):
    """Scrolls down the page one screen at a time and stitches the shots together."""
    def got(raw):
        try:
            info = json.loads(raw)
        except (TypeError, ValueError):
            done(grab_visible(tab))
            return
        view_h = max(1, int(info["vh"]))
        total = min(int(info["h"]), view_h * max_screens)
        ratio = tab.grab().height() / view_h
        canvas = QPixmap(tab.grab().width(), int(total * ratio))
        canvas.fill(QColor("#ffffff"))
        painter = QPainter(canvas)
        offsets = list(range(0, max(1, total - view_h) + 1, view_h))
        if offsets[-1] < total - view_h:
            offsets.append(total - view_h)

        def step(i=0):
            if i >= len(offsets):
                painter.end()
                tab.run_js(f"window.scrollTo(0,{int(info['y'])})")
                done(canvas)
                return
            y = offsets[i]

            def shot(_r=None):
                def take():
                    painter.drawPixmap(0, int(y * ratio), tab.grab())
                    step(i + 1)
                QTimer.singleShot(260, take)
            tab.run_js(f"window.scrollTo(0,{y})", shot)
        step()
    tab.run_js("JSON.stringify({h: Math.max(document.documentElement.scrollHeight, document.body ? "
               "document.body.scrollHeight : 0), vh: window.innerHeight, y: window.scrollY})", got)


def screenshot(win, kind: str = "area"):
    """kind: 'area' (drag to pick), 'visible' or 'full'."""
    tab = win.current_tab()
    if tab is None:
        return

    def show(pix):
        if pix is None or pix.isNull():
            return
        ScreenshotDialog(pix, tab.title() or "Screenshot", win).exec()
    if kind == "visible":
        show(grab_visible(tab))
    elif kind == "full":
        win.notify("Capturing the whole page…")
        grab_full_page(tab, lambda pix: (win.notice.hide(), show(pix)))
    else:
        AreaPicker(tab, grab_visible(tab), show)


# ------------------------------------------------------------------ picture in picture
PIP_FIND = r"""
(function () {
  var vs = Array.from(document.querySelectorAll('video')).filter(function (v) { var r = v.getBoundingClientRect(); return r.width * r.height > 0; });
  if (!vs.length) return JSON.stringify(null);
  vs.sort(function (a, b) { var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return rb.width * rb.height - ra.width * ra.height; });
  var v = vs[0], t = v.currentTime || 0, playing = !v.paused;
  document.querySelectorAll('video').forEach(function (x) { x.pause(); });
  return JSON.stringify({ t: t, playing: playing });
})()
"""
PIP_ISOLATE = r"""
(function (t) {
  var vs = Array.from(document.querySelectorAll('video'));
  if (!vs.length) return false;
  vs.sort(function (a, b) { var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return rb.width * rb.height - ra.width * ra.height; });
  var v = vs[0];
  if (!document.getElementById('pelagic-pip')) {
    var s = document.createElement('style'); s.id = 'pelagic-pip';
    s.textContent = 'html,body{background:#000!important;overflow:hidden!important;margin:0!important}' +
      'body>*:not(video){display:none!important}' +
      'video#pelagic-pip-video{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;' +
      'object-fit:contain!important;z-index:2147483647!important;background:#000!important;filter:none!important;transform:none!important}';
    (document.head || document.documentElement).appendChild(s);
  }
  v.id = 'pelagic-pip-video'; v.controls = true;
  if (v.parentNode !== document.body) document.body.appendChild(v);
  if (t > 1 && Math.abs(v.currentTime - t) > 2) v.currentTime = t;
  v.muted = false; v.play().catch(function () {});
  return true;
})(%s)
"""


class PipWindow(QWidget):
    """A small always-on-top window playing the tab's video, so you can keep browsing."""

    def __init__(self, win, tab, start: float):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.win, self.tab, self.start = win, tab, start
        self.setWindowTitle(f"Picture-in-picture — {tab.title()}")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.view = QWebEngineView(self)
        from .webview import WebPage
        self.view.setPage(WebPage(tab.page().profile(), tab))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.resize(480, 270)
        screen = (tab.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 48)
        url = QUrl(tab.url())
        if "youtube.com" in url.host() and start > 1:
            q = url.query()
            url.setQuery((q + "&" if q else "") + f"t={int(start)}s")
        self._tries = 0
        self.view.loadFinished.connect(lambda _ok: self._isolate())
        self.view.load(url)
        self.show()

    def _isolate(self):
        def got(ok):
            self._tries += 1
            if not ok and self._tries < 30:
                QTimer.singleShot(500, self._isolate)
        self.view.page().runJavaScript(PIP_ISOLATE % json.dumps(self.start), got)

    def closeEvent(self, ev):
        tab = self.tab

        def back(t):
            try:
                t = float(t or 0)
            except (TypeError, ValueError):
                t = 0
            try:
                tab.page().runJavaScript(
                    "(function(t){var v=Array.from(document.querySelectorAll('video')).sort(function(a,b){"
                    "var ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();return rb.width*rb.height-"
                    "ra.width*ra.height})[0];if(v){if(t>1)v.currentTime=t;v.play().catch(function(){})}})(%s)" % t)
            except RuntimeError:
                pass
        self.view.page().runJavaScript("(document.getElementById('pelagic-pip-video')||{}).currentTime||0", back)
        self.view.page().runJavaScript("document.querySelectorAll('video').forEach(function(v){v.pause()})")
        QTimer.singleShot(300, self.view.page().deleteLater)
        self.win._pip = None
        super().closeEvent(ev)


def picture_in_picture(win):
    tab = win.current_tab()
    if tab is None:
        return
    if getattr(win, "_pip", None) is not None:
        win._pip.close()
        return

    def got(raw):
        try:
            info = json.loads(raw) if raw else None
        except ValueError:
            info = None
        if not info:
            win.notify("There's no video on this page to pop out.")
            QTimer.singleShot(3500, win.notice.hide)
            return
        win._pip = PipWindow(win, tab, float(info.get("t") or 0))
    tab.run_js(PIP_FIND, got)

