"""The new tab / home page: your own shortcuts (or most visited sites), a background (Pelagic's ocean, a colour or
your own photo, with dim and blur), and which parts show (logo, tagline, search box, shortcuts, clock).
Everything is set in Settings → Homepage, and shortcuts can also be added or edited from the page itself.

The page is a local file (start.html in the profile folder). Its "+", "⋮" and "Customize" links point back at
start.html with a ?pelagic= query; WebPage.acceptNavigationRequest turns those into home_action instead of loading.
Clicking the logo five times in a row does the same with ?pelagic=playground, which opens the hidden playground.
"""
from __future__ import annotations

import base64
import html
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from .store import HOMEPAGE_DEFAULTS as DEFAULTS

MAX_SHORTCUTS = 20
IMAGE_TYPES = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"
BACKGROUNDS = (("ocean", "Pelagic ocean"), ("color", "Solid color"), ("image", "My photo"))
SHOW = (("home_show_logo", "Logo and name"), ("home_show_tagline", "Tagline"), ("home_show_search", "Search box"),
        ("home_show_shortcuts", "Shortcuts"), ("home_show_clock", "Clock and date"),
        ("home_show_footer", "\"Searching with …\" line"))

LOGO_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="88" height="88" class="mark" role'
    '="img" aria-label="Pelagic"><defs><linearGradient id="pg-depth" x1="0" y1="0" x2="0" y2="1"><stop of'
    'fset="0" stop-color="#1B8C9A"/><stop offset="0.45" stop-color="#0B4A6B"/><stop offset="1" stop-color'
    '="#04162B"/></linearGradient><linearGradient id="pg-surface" x1="0" y1="0" x2="0" y2="1"><stop offse'
    't="0" stop-color="#7FE3DA"/><stop offset="1" stop-color="#2FB3B4"/></linearGradient><radialGradient '
    'id="pg-glow" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#C9FFF4" stop-opacity="0.9"/><st'
    'op offset="0.35" stop-color="#5FF0D6" stop-opacity="0.45"/><stop offset="1" stop-color="#5FF0D6" sto'
    'p-opacity="0"/></radialGradient><clipPath id="pg-tile"><rect width="64" height="64" rx="14"/></clipP'
    'ath></defs><g clip-path="url(#pg-tile)"><rect width="64" height="64" fill="url(#pg-depth)"/><path d='
    '"M0 0 H64 V17 C58 13 52 13 46 17.5 C40 22 33 22 27 17.5 C21 13 14 13 8 17 C5 19 2 19.5 0 19 Z" fill='
    '"url(#pg-surface)"/><path d="M0 24 C6 21 12 21 18 24.5 C24 28 31 28 37 24.5 C43 21 50 21 56 24.5 C59'
    ' 26 62 26.5 64 26" fill="none" stroke="#7FE3DA" stroke-opacity="0.35" stroke-width="1.6" stroke-line'
    'cap="round"/><circle cx="39" cy="43" r="15" fill="url(#pg-glow)"/><circle cx="39" cy="43" r="5.5" fi'
    'll="#D8FFF7"/><circle cx="24" cy="50" r="2.2" fill="#8FF3E2" fill-opacity="0.75"/><circle cx="27" cy'
    '="38" r="1.4" fill="#8FF3E2" fill-opacity="0.55"/></g></svg>')


# ------------------------------------------------------------------ data
def shortcuts(store) -> list[dict]:
    return list(store.get("home_shortcuts") or [])


def most_visited(store, n: int = 8) -> list[dict]:
    """Top sites from history, one per host."""
    by_host: dict[str, dict] = {}
    for url, title, visits, _last in store.history(limit=2000):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        host = parts.hostname.removeprefix("www.")
        e = by_host.setdefault(host, {"url": f"{parts.scheme}://{parts.hostname}/", "title": "", "visits": 0})
        e["visits"] += visits or 0
        if not e["title"] or parts.path in ("", "/"):
            e["title"] = (title or host).split(" - ")[0].split(" | ")[0][:40]
    top = sorted(by_host.values(), key=lambda e: -e["visits"])[:n]
    return [{"title": e["title"], "url": e["url"]} for e in top]


def add_shortcut(store, title: str, url: str):
    items = shortcuts(store)
    if len(items) < MAX_SHORTCUTS:
        items.append({"title": title.strip() or host_of(url), "url": url})
        store.set("home_shortcuts", items)


def set_shortcut(store, i: int, title: str, url: str):
    items = shortcuts(store)
    if 0 <= i < len(items):
        items[i] = {"title": title.strip() or host_of(url), "url": url}
        store.set("home_shortcuts", items)


def remove_shortcut(store, i: int):
    items = shortcuts(store)
    if 0 <= i < len(items):
        del items[i]
        store.set("home_shortcuts", items)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")


def normalize_url(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    return t if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) else QUrl.fromUserInput(t).toString()


def save_background(store, src: str) -> str:
    """Copies the chosen photo into the profile, so moving or deleting the original doesn't break the page."""
    folder = store.root / "homepage"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("background.*"):
        old.unlink()
    dest = folder / ("background" + (Path(src).suffix.lower() or ".png"))
    shutil.copyfile(src, dest)
    return str(dest)


# ------------------------------------------------------------------ page
def _opt(store, key):
    v = store.get(key)
    return DEFAULTS[key] if v is None else v


def _tile(store, i, s, editable):
    fav = store.favicon_path(s["url"])
    if fav.exists():
        icon = f'<img src="data:image/png;base64,{base64.b64encode(fav.read_bytes()).decode()}">'
    else:
        icon = f'<span class="letter">{html.escape((s["title"] or host_of(s["url"]) or "?")[:1].upper())}</span>'
    edit = (f'<a class="more" href="?pelagic=edit&i={i}" title="Edit shortcut">⋮</a>' if editable else "")
    return (f'<div class="tile"><a class="go" href="{html.escape(s["url"])}" title="{html.escape(s["url"])}">'
            f'<span class="ic">{icon}</span><span class="name">{html.escape(s["title"][:24])}</span></a>{edit}</div>')


def build(store, engine_name: str, search_action: str) -> str:
    o = lambda k: _opt(store, k)   # noqa: E731
    mine = o("home_shortcuts_mode") != "most_visited"
    items = shortcuts(store) if mine else most_visited(store)
    tiles = "".join(_tile(store, i, s, mine) for i, s in enumerate(items))
    if mine and len(items) < MAX_SHORTCUTS:
        tiles += ('<div class="tile"><a class="go" href="?pelagic=add" title="Add shortcut"><span class="ic add">+'
                  '</span><span class="name">Add shortcut</span></a></div>')
    bg_kind = o("home_bg")
    image = o("home_bg_image")
    if bg_kind == "image" and image and Path(image).exists():
        url = QUrl.fromLocalFile(image).toString() + f"?v={int(Path(image).stat().st_mtime)}"
        bg = f"background:#000 url('{url}') center/cover no-repeat"
    elif bg_kind == "color":
        bg = f"background:{QColor(o('home_bg_color')).name()}"
    else:
        bg = "background:radial-gradient(circle at 50% 25%,#0B4A6B,#04162B 65%)"
    dim = max(0, min(90, int(o("home_bg_dim")))) / 100 if bg_kind == "image" else 0
    blur = max(0, min(40, int(o("home_bg_blur")))) if bg_kind == "image" else 0
    light = bg_kind == "color" and QColor(o("home_bg_color")).lightnessF() > 0.62
    ink, soft = ("#10202b", "#3d5560") if light else ("#E3F6F4", "#a9c4ca")
    logo = LOGO_SVG
    parts = []
    if o("home_show_clock"):
        parts.append('<div class="clock" id="clock"></div><div class="date" id="date"></div>')
    if o("home_show_logo"):
        parts.append(f'<div class="mark">{logo}</div><h1>Pelagic</h1>')
    if o("home_show_tagline"):
        parts.append("<p>Search the web — or press Ctrl+Shift+A and let AI do the browsing.</p>")
    if o("home_show_search"):
        parts.append(f'<form action="{html.escape(search_action)}" method="get"><input name="q" '
                     f'placeholder="Search {html.escape(engine_name)}" autofocus autocomplete="off"></form>')
    if o("home_show_shortcuts"):
        parts.append(f'<div class="tiles">{tiles}</div>')
    if o("home_show_footer"):
        parts.append(f"<small>Searching with {html.escape(engine_name)}</small>")
    clock_js = """<script>(function(){function t(){var d=new Date();
document.getElementById('clock').textContent=d.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
document.getElementById('date').textContent=d.toLocaleDateString([], {weekday:'long',month:'long',day:'numeric'});}
t();setInterval(t,1000);})();</script>""" if o("home_show_clock") else ""
    # easter egg: five quick clicks on the logo open the playground (each click tilts it a little)
    logo_js = """<script>(function(){var m=document.querySelector('.mark'),n=0,t;if(!m)return;
m.addEventListener('click',function(){n++;clearTimeout(t);m.style.transform='rotate('+(n%2?-1:1)*n*3+'deg)';
t=setTimeout(function(){n=0;m.style.transform='';},1200);if(n>=5)location.href='?pelagic=playground';});})();</script>""" \
        if o("home_show_logo") else ""
    return f"""<!doctype html><meta charset=utf-8><title>New tab</title>
<style>
html,body{{margin:0;min-height:100vh}}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;color:{ink};
font-family:Segoe UI,sans-serif;background:#04162B}}
.bg{{position:fixed;inset:-{blur * 2}px;{bg};filter:blur({blur}px);z-index:-2}}
.dim{{position:fixed;inset:0;background:rgba(0,0,0,{dim});z-index:-1}}
.mark{{margin-bottom:14px;filter:drop-shadow(0 14px 26px rgba(0,0,0,.35));transition:transform .15s}}.mark svg{{width:88px;height:88px}}
h1{{font-weight:600;font-size:46px;letter-spacing:-.5px;margin:0 0 6px;text-shadow:0 2px 12px rgba(0,0,0,.25)}}
p{{color:{soft};margin:0 0 26px}}
.clock{{font-size:64px;font-weight:300;letter-spacing:-1px;text-shadow:0 2px 14px rgba(0,0,0,.3)}}
.date{{color:{soft};margin:0 0 26px}}
form{{width:min(620px,86vw)}}input{{width:100%;box-sizing:border-box;padding:15px 20px;border-radius:30px;
border:1px solid rgba(127,227,218,.25);background:rgba(10,34,54,.82);color:#fff;font-size:17px;outline:none;
backdrop-filter:blur(8px)}}input:focus{{border-color:#5FE0CF;box-shadow:0 0 0 3px #5FE0CF44}}
.tiles{{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:30px;max-width:720px}}
.tile{{position:relative;width:104px;border-radius:12px}}.tile:hover{{background:rgba(255,255,255,.08)}}
.go{{display:flex;flex-direction:column;align-items:center;gap:8px;padding:14px 6px 10px;color:inherit;
text-decoration:none}}
.ic{{width:48px;height:48px;border-radius:50%;background:rgba(10,34,54,.85);display:flex;align-items:center;
justify-content:center;border:1px solid rgba(127,227,218,.18)}}.ic img{{width:24px;height:24px}}
.letter{{font-weight:700;font-size:20px;color:#7FE3DA}}.add{{font-size:26px;color:#7FE3DA;font-weight:300}}
.name{{font-size:12.5px;max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
text-shadow:0 1px 6px rgba(0,0,0,.35)}}
.more{{position:absolute;top:4px;right:4px;width:22px;height:22px;border-radius:50%;display:none;align-items:center;
justify-content:center;color:{ink};text-decoration:none;font-weight:700}}
.tile:hover .more{{display:flex}}.more:hover{{background:rgba(255,255,255,.15)}}
small{{margin-top:30px;color:{soft};opacity:.8}}
.customize{{position:fixed;right:18px;bottom:16px;padding:8px 14px;border-radius:18px;color:{ink};
background:rgba(10,34,54,.6);text-decoration:none;font-size:13px;border:1px solid rgba(127,227,218,.2)}}
.customize:hover{{border-color:#5FE0CF}}</style>
<div class="bg"></div><div class="dim"></div>
{"".join(parts)}
<a class="customize" href="?pelagic=customize" title="Change the background, shortcuts and what shows here">✎ Customize</a>
{clock_js}{logo_js}"""


def parse_action(url: QUrl):
    """('add'|'edit'|'customize'|'playground', index) for a ?pelagic= link on the start page, else None."""
    if not (url.isLocalFile() and url.fileName() == "start.html"):
        return None
    q = dict(p.split("=", 1) for p in url.query().split("&") if "=" in p)
    action = q.get("pelagic")
    if action not in ("add", "edit", "customize", "playground"):
        return None
    try:
        return action, int(q.get("i", -1))
    except ValueError:
        return action, -1


# ------------------------------------------------------------------ editing
class ShortcutEditor(QDialog):
    """Name and URL of one shortcut. done(2) means Remove."""

    def __init__(self, title: str = "", url: str = "", parent=None, editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Edit shortcut" if editing else "Add shortcut")
        self.setMinimumWidth(400)
        self.name = QLineEdit(title)
        self.addr = QLineEdit(url)
        self.addr.setPlaceholderText("https://…")
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("URL", self.addr)
        self.btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        if editing:
            self.btns.addButton("Remove", QDialogButtonBox.DestructiveRole).clicked.connect(lambda: self.done(2))
        self.btns.accepted.connect(self._ok)
        self.btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.btns)
        (self.name if editing else self.addr).setFocus()

    def _ok(self):
        if normalize_url(self.addr.text()):
            self.accept()
        else:
            self.addr.setFocus()

    def values(self):
        url = normalize_url(self.addr.text())
        return (self.name.text().strip() or host_of(url)), url


def handle_action(win, action: str, i: int):
    store = win.store
    if action == "playground":
        from . import playground
        win._cur(lambda t: t.load(playground.url()))
        return
    if action == "customize":
        win.open_settings("homepage")
    elif action == "add":
        d = ShortcutEditor(parent=win)
        if d.exec() == QDialog.Accepted:
            add_shortcut(store, *d.values())
    elif action == "edit":
        items = shortcuts(store)
        if not 0 <= i < len(items):
            return
        d = ShortcutEditor(items[i]["title"], items[i]["url"], win, editing=True)
        r = d.exec()
        if r == 2:
            remove_shortcut(store, i)
        elif r == QDialog.Accepted:
            set_shortcut(store, i, *d.values())
    refresh_open_pages(win)


def refresh_open_pages(win):
    win.start_page_url()   # rewrites start.html
    for t in win.tab_list():
        if win.is_start(t.url()):
            t.load(win.start_page_url())


class HomepageSettings(QWidget):
    """Settings → Homepage. Nothing is saved until save() (the dialog's OK)."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        o = lambda k: _opt(store, k)   # noqa: E731
        self.items = shortcuts(store)
        self.color = QColor(o("home_bg_color"))
        self.image = o("home_bg_image")

        # shortcuts
        sc = QGroupBox("Shortcuts")
        sv = QVBoxLayout(sc)
        self.mode = QComboBox()
        self.mode.addItem("My shortcuts", "mine")
        self.mode.addItem("Most visited sites", "most_visited")
        self.mode.setCurrentIndex(max(0, self.mode.findData(o("home_shortcuts_mode"))))
        sv.addWidget(self.mode)
        self.list = QListWidget()
        self.list.setMaximumHeight(150)
        self.list.itemDoubleClicked.connect(lambda _it: self._edit())
        sv.addWidget(self.list)
        row = QHBoxLayout()
        self.list_btns = []
        for text, slot in (("Add…", self._add), ("Edit…", self._edit), ("Remove", self._remove),
                           ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.list_btns.append(b)
        row.addStretch(1)
        sv.addLayout(row)
        self.mode.currentIndexChanged.connect(self._mode_changed)

        # background
        bgbox = QGroupBox("Background")
        bf = QFormLayout(bgbox)
        self.bg = QComboBox()
        for k, label in BACKGROUNDS:
            self.bg.addItem(label, k)
        self.bg.setCurrentIndex(max(0, self.bg.findData(o("home_bg"))))
        bf.addRow("Style", self.bg)
        self.color_btn = QPushButton("Pick color…")
        self.color_btn.clicked.connect(self._pick_color)
        bf.addRow("Color", self.color_btn)
        img_row = QHBoxLayout()
        self.img_btn = QPushButton("Choose photo…")
        self.img_btn.clicked.connect(self._pick_image)
        self.img_label = QLabel()
        self.img_label.setStyleSheet("color:#8b93a7")
        img_row.addWidget(self.img_btn)
        img_row.addWidget(self.img_label, 1)
        bf.addRow("Photo", img_row)
        self.dim = self._slider(0, 90, int(o("home_bg_dim")), "%")
        self.blur = self._slider(0, 40, int(o("home_bg_blur")), " px")
        bf.addRow("Darken photo", self.dim[0])
        bf.addRow("Blur photo", self.blur[0])
        self.bg.currentIndexChanged.connect(self._bg_changed)

        # parts
        show = QGroupBox("Show on the homepage")
        shv = QVBoxLayout(show)
        self.show = {}
        for key, label in SHOW:
            cb = QCheckBox(label)
            cb.setChecked(bool(o(key)))
            shv.addWidget(cb)
            self.show[key] = cb

        inner = QWidget()
        lay = QVBoxLayout(inner)
        note = QLabel("This is the page new tabs open on (and Home, unless Settings → General sets another home page). "
                      "You can also add or edit shortcuts right on the page, and its ✎ Customize button opens this tab.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8b93a7")
        lay.addWidget(note)
        lay.addWidget(sc)
        lay.addWidget(bgbox)
        lay.addWidget(show)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._fill()
        self._mode_changed()
        self._bg_changed()

    def _slider(self, lo, hi, value, unit):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(max(lo, min(hi, value)))
        lab = QLabel(f"{s.value()}{unit}")
        lab.setMinimumWidth(44)
        s.valueChanged.connect(lambda v: lab.setText(f"{v}{unit}"))
        h.addWidget(s, 1)
        h.addWidget(lab)
        return w, s

    def _fill(self):
        self.list.clear()
        for s in self.items:
            it = QListWidgetItem(f"{s['title']}  —  {s['url']}")
            self.list.addItem(it)
        if not self.items:
            it = QListWidgetItem("No shortcuts yet. Click Add…")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def _mode_changed(self, *_):
        mine = self.mode.currentData() == "mine"
        self.list.setEnabled(mine)
        for b in self.list_btns:
            b.setEnabled(mine)

    def _bg_changed(self, *_):
        kind = self.bg.currentData()
        self.color_btn.setEnabled(kind == "color")
        self.img_btn.setEnabled(kind == "image")
        for w, _s in (self.dim, self.blur):
            w.setEnabled(kind == "image")
        self.color_btn.setStyleSheet(f"QPushButton{{border-left:18px solid {self.color.name()}}}")
        self.img_label.setText(Path(self.image).name if self.image else "No photo chosen")

    def _pick_color(self):
        c = QColorDialog.getColor(self.color, self, "Background color")
        if c.isValid():
            self.color = c
            self._bg_changed()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a background photo", str(Path.home() / "Pictures"),
                                              IMAGE_TYPES)
        if path:
            self.image = path
            self._bg_changed()

    def _row(self):
        r = self.list.currentRow()
        return r if 0 <= r < len(self.items) else -1

    def _add(self):
        if len(self.items) >= MAX_SHORTCUTS:
            return
        d = ShortcutEditor(parent=self)
        if d.exec() == QDialog.Accepted:
            t, u = d.values()
            self.items.append({"title": t, "url": u})
            self._fill()
            self.list.setCurrentRow(len(self.items) - 1)

    def _edit(self):
        r = self._row()
        if r < 0:
            return
        d = ShortcutEditor(self.items[r]["title"], self.items[r]["url"], self, editing=True)
        res = d.exec()
        if res == 2:
            del self.items[r]
        elif res == QDialog.Accepted:
            t, u = d.values()
            self.items[r] = {"title": t, "url": u}
        self._fill()

    def _remove(self):
        r = self._row()
        if r >= 0:
            del self.items[r]
            self._fill()

    def _move(self, step):
        r = self._row()
        j = r + step
        if r >= 0 and 0 <= j < len(self.items):
            self.items[r], self.items[j] = self.items[j], self.items[r]
            self._fill()
            self.list.setCurrentRow(j)

    def save(self):
        s = self.store
        s.set("home_shortcuts", self.items)
        s.set("home_shortcuts_mode", self.mode.currentData())
        kind = self.bg.currentData()
        image = self.image
        if image and image != s.get("home_bg_image") and Path(image).exists():
            image = save_background(s, image)
        if kind == "image" and not image:
            kind = "ocean"
        s.set("home_bg", kind)
        s.set("home_bg_color", self.color.name())
        s.set("home_bg_image", image or "")
        s.set("home_bg_dim", self.dim[1].value())
        s.set("home_bg_blur", self.blur[1].value())
        for key, cb in self.show.items():
            s.set(key, cb.isChecked())

