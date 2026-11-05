"""Opening files from the computer (Ctrl+O, dragging a file in, or "Open with Pelagic").

Markdown is shown formatted, with a button to see its source; text files (.txt, .log, .json, .csv, code…) get a
readable page in the reader's colours (dark, light or sepia), so they suit dark mode. Other files a browser can show
itself (web pages, PDFs, pictures) open as usual. The address bar shows the file itself.
"""
from __future__ import annotations

import html
import json
import re
import tempfile
import zlib
from pathlib import Path

from PySide6.QtCore import QUrl

MARKDOWN = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}
TEXT = {".txt", ".text", ".log", ".csv", ".tsv", ".json", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml",
        ".py", ".js", ".ts", ".css", ".ps1", ".bat", ".cmd", ".sh", ".c", ".h", ".cpp", ".java", ".cs", ".rs",
        ".go", ".rb", ".php", ".sql", ".srt", ".nfo", ".env", ".gitignore"}
# what the Windows installer offers "Open with Pelagic" for
OPEN_WITH = sorted(MARKDOWN | {".txt", ".log", ".html", ".htm", ".pdf"})
DIALOG_FILTER = ("Files Pelagic can show (*.md *.markdown *.txt *.log *.json *.csv *.html *.htm *.pdf *.png *.jpg "
                 "*.jpeg *.gif *.webp *.svg);;Markdown (*.md *.markdown);;Text files (*.txt *.log);;All files (*)")
MAX_BYTES = 8 * 1024 * 1024
THEMES = {"dark": ("#16181d", "#e6e8ee", "#8fd8cf", "#20232b", "#2c3039"),
          "light": ("#ffffff", "#1d1f24", "#1B8C9A", "#f3f4f6", "#dde0e6"),
          "sepia": ("#f4ecd8", "#3b3024", "#8a5a2b", "#ebe0c6", "#d8c9a6")}


def folder() -> Path:
    d = Path(tempfile.gettempdir()) / "Pelagic file view"
    d.mkdir(parents=True, exist_ok=True)
    return d


def kind(url: QUrl) -> str | None:
    """'markdown' or 'text' for a local file Pelagic shows itself, else None."""
    if not url.isLocalFile():
        return None
    path = Path(url.toLocalFile())
    suffix = path.suffix.lower() or (path.name.lower() if path.name.startswith(".") else "")
    if suffix in MARKDOWN:
        return "markdown"
    if suffix in TEXT or path.name.upper() in ("README", "LICENSE", "CHANGELOG", "NOTES"):
        return "text"
    return None


def is_view(url: QUrl) -> bool:
    return url.isLocalFile() and url.fileName().startswith("fileview-") and Path(url.toLocalFile()).parent == folder()


def wants(url: QUrl) -> bool:
    """A navigation to a file that should open in the file view (not the view page itself)."""
    return not is_view(url) and kind(url) is not None


def parse_action(url: QUrl) -> str | None:
    if not is_view(url):
        return None
    q = dict(p.split("=", 1) for p in url.query().split("&") if "=" in p)
    act = q.get("pelagic", "")
    return act if act.startswith("file-") else None


def to_url(text: str) -> QUrl | None:
    """A path typed in the address bar or passed on the command line (C:\\notes\\todo.md, ~/a.txt)."""
    t = (text or "").strip().strip('"')
    if not t or "\n" in t or len(t) > 1000:
        return None
    if re.match(r"^[a-zA-Z]:[\\/]", t) or t.startswith(("\\\\", "/", "~")):
        p = Path(t).expanduser()
        try:
            if p.exists():
                return QUrl.fromLocalFile(str(p.resolve()))
        except OSError:
            return None
    return None


# ------------------------------------------------------------------ showing a file
_SHOWN: dict[str, tuple[str, str]] = {}   # view page name -> (the file's address, "rendered" | "text")


def source_of(view: QUrl) -> QUrl | None:
    """The file a view page shows."""
    got = _SHOWN.get(view.fileName()) if is_view(view) else None
    return QUrl(got[0]) if got else None


def show(tab, url: QUrl, store=None, mode: str | None = None):
    """Render the file into a view page and load that in the tab."""
    path = Path(url.toLocalFile())
    k = kind(url) or "text"
    mode = mode or ("rendered" if k == "markdown" else "text")
    src = QUrl.fromLocalFile(str(path)).toString()
    # one page per tab and file, so Back and Forward between files work
    name = f"fileview-{id(tab):x}-{zlib.crc32(src.encode()):08x}.html"
    _SHOWN[name] = (src, mode)
    page = folder() / name
    view = QUrl.fromLocalFile(str(page))
    page.write_text(build(path, k, mode, theme_of(store), view.toString()), encoding="utf-8")
    view.setFragment(url.fragment())
    if tab.url().toString().split("#")[0] == view.toString().split("#")[0]:
        tab._file_rerender = True    # this reload is ours: let it through (F5 alone renders the file again)
        tab.reload()
    else:
        tab.load(view)


def handle_action(tab, action: str, store=None):
    got = _SHOWN.get(tab.url().fileName())
    if not got:
        return
    src, mode = got
    if action in ("file-source", "file-rendered"):
        show(tab, QUrl(src), store, "text" if action == "file-source" else "rendered")
    elif action == "file-reload":
        show(tab, QUrl(src), store, mode)
    elif action.startswith("file-theme-") and store is not None:
        store.set("reader_theme", action.removeprefix("file-theme-"))
        show(tab, QUrl(src), store, mode)


def theme_of(store) -> str:
    t = (store.get("reader_theme") if store is not None else None) or "dark"
    return t if t in THEMES else "dark"


def read_text(path: Path) -> str:
    """The file's text with Windows (\\r\\n) and old Mac (\\r) line endings made plain \\n."""
    data = path.read_bytes()[:MAX_BYTES]
    text = None
    for enc in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        text = data.decode("cp1252", "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def build(path: Path, k: str, mode: str, theme: str = "dark", self_url: str = "") -> str:
    bg, fg, link, code_bg, line = THEMES.get(theme, THEMES["dark"])
    try:
        text = read_text(path)
        error = ""
    except OSError as e:
        text, error = "", f"Couldn't open this file: {e.strerror or e}"
    big = path.exists() and path.stat().st_size > MAX_BYTES
    if error:
        body = f'<p class="note">{html.escape(error)}</p>'
    elif k == "markdown" and mode == "rendered":
        body = f'<article class="md">{markdown_to_html(text)}</article>'
    else:
        if path.suffix.lower() == ".json":
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        body = f'<pre class="text">{html.escape(text)}</pre>'
    if big:
        body = '<p class="note">This file is large; only the first 8 MB is shown.</p>' + body
    me = html.escape(self_url) + "?pelagic="   # the bar's own links (handled by Pelagic, never loaded)
    toggle = ""
    if k == "markdown":
        toggle = (f'<a href="{me}file-source">Show source</a>' if mode == "rendered"
                  else f'<a href="{me}file-rendered">Show formatted</a>')
    themes = "".join(f'<a href="{me}file-theme-{t}" class="{"on" if t == theme else ""}">{t.title()}</a>'
                     for t in THEMES)
    base = QUrl.fromLocalFile(str(path.parent) + "/").toString()
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(path.name)}</title>
<meta name="color-scheme" content="{'dark' if theme == 'dark' else 'light'}">
<style>
html,body{{background:{bg};color:{fg};margin:0}}
body{{font:16px/1.65 "Segoe UI",system-ui,sans-serif}}
.bar{{position:sticky;top:0;background:{bg};border-bottom:1px solid {line};padding:8px 20px;display:flex;gap:14px;
  align-items:center;font-size:13px;z-index:2}}
.bar .name{{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar .path{{opacity:.6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
.bar a{{color:{link};text-decoration:none;white-space:nowrap}} .bar a.on{{font-weight:700;text-decoration:underline}}
main{{max-width:900px;margin:0 auto;padding:24px 28px 80px}}
a{{color:{link}}}
pre,code{{font-family:Consolas,"Cascadia Mono",monospace;font-size:14px}}
pre.text{{white-space:pre-wrap;word-wrap:break-word;margin:0;line-height:1.5}}
.md code{{background:{code_bg};padding:1px 5px;border-radius:4px}}
.md pre{{background:{code_bg};padding:12px 14px;border-radius:8px;overflow:auto;line-height:1.45}}
.md pre code{{background:none;padding:0}}
.md h1,.md h2{{border-bottom:1px solid {line};padding-bottom:.25em}}
.md h1,.md h2,.md h3,.md h4{{line-height:1.25;margin:1.4em 0 .5em}}
.md blockquote{{margin:0;padding:0 1em;border-left:4px solid {line};opacity:.85}}
.md table{{border-collapse:collapse;margin:1em 0}} .md th,.md td{{border:1px solid {line};padding:6px 12px}}
.md th{{background:{code_bg}}}
.md img{{max-width:100%}} .md hr{{border:0;border-top:1px solid {line};margin:2em 0}}
.md li.task{{list-style:none;margin-left:-1.3em}}
.note{{background:{code_bg};padding:10px 14px;border-radius:8px}}
</style><base href="{html.escape(base)}"></head><body>
<div class="bar"><span class="name">{html.escape(path.name)}</span><span class="path">{html.escape(str(path.parent))}</span>
{toggle}<a href="{me}file-reload">Reload</a>{themes}</div>
<main>{body}</main></body></html>"""


# ------------------------------------------------------------------ a small Markdown renderer
def _inline(s: str) -> str:
    codes: list[str] = []

    def keep_code(m):
        codes.append(f"<code>{html.escape(m.group(2))}</code>")
        return f"\x00{len(codes) - 1}\x00"
    s = re.sub(r"(`+)(.+?)\1", keep_code, s)
    s = html.escape(s, quote=False)
    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;|\s+\"[^)]*\")?\)",
               lambda m: f'<img src="{_attr(m.group(2))}" alt="{_attr(m.group(1))}">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^)]*\")?\)",
               lambda m: f'<a href="{_attr(m.group(2))}">{m.group(1)}</a>', s)
    s = re.sub(r"&lt;(https?://[^\s&]+)&gt;", r'<a href="\1">\1</a>', s)
    s = re.sub(r"(?<![\"=>/])\b(https?://[^\s<]+[^\s<.,;:!?)])", r'<a href="\1">\1</a>', s)
    s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"<strong>\2</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"<em>\1</em>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", s)
    s = re.sub(r"  +$", "<br>", s, flags=re.M)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def _attr(v: str) -> str:
    v = html.unescape(v)
    if re.match(r"^\s*javascript:", v, re.I):
        v = "#"
    return html.escape(v, quote=True)


def _table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def markdown_to_html(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").split("\n")
    out: list[str] = []
    i = 0
    para: list[str] = []

    def flush():
        if para:
            out.append("<p>" + _inline("\n".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        fence = re.match(r"^\s*(```+|~~~+)\s*([\w+#.-]*)", line)
        if fence:
            flush()
            mark, lang = fence.group(1), fence.group(2)
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith(mark):
                code.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        if not s:
            flush()
            i += 1
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if h:
            flush()
            n = len(h.group(1))
            slug = re.sub(r"[^\w\- ]", "", h.group(2).lower()).strip().replace(" ", "-")
            out.append(f'<h{n} id="{html.escape(slug)}">{_inline(h.group(2))}</h{n}>')
            i += 1
            continue
        if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", s):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if para and re.match(r"^(=+|-+)$", s):     # Setext heading
            n = 1 if s[0] == "=" else 2
            title = " ".join(para)
            para.clear()
            out.append(f"<h{n}>{_inline(title)}</h{n}>")
            i += 1
            continue
        if s.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + markdown_to_html("\n".join(quote)) + "</blockquote>")
            continue
        if "|" in s and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", lines[i + 1]):
            flush()
            head = _table_row(s)
            aligns = []
            for c in _table_row(lines[i + 1]):
                aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":")
                              else "left" if c.startswith(":") else "")
            i += 2

            def cell(tag, v, n):
                a = aligns[n] if n < len(aligns) and aligns[n] else ""
                style = ' style="text-align:%s"' % a if a else ""
                return f"<{tag}{style}>{_inline(v)}</{tag}>"
            rows = ["<tr>" + "".join(cell("th", c, n) for n, c in enumerate(head)) + "</tr>"]
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append("<tr>" + "".join(cell("td", c, n) for n, c in enumerate(_table_row(lines[i]))) + "</tr>")
                i += 1
            out.append("<table>" + "".join(rows) + "</table>")
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
            flush()
            block = []
            indent0 = len(line) - len(line.lstrip())
            ordered0 = bool(re.match(r"^\s*\d", line))

            def other_list(ln):   # a new list of the other kind (bullets after numbers) at the same level
                m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+", ln)
                return bool(m) and len(m.group(1)) <= indent0 + 1 and m.group(2)[0].isdigit() != ordered0
            while i < len(lines):
                ln = lines[i]
                if block and other_list(ln):
                    break
                if not ln.strip():
                    # a blank line ends the list unless the list (or an item's text) carries on after it
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    if re.match(r"^\s*([-*+]|\d+[.)])\s+", nxt) or (nxt.startswith("  ") and nxt.strip()):
                        block.append("")
                        i += 1
                        continue
                    break
                if block and not re.match(r"^\s*([-*+]|\d+[.)])\s+", ln) and not ln.startswith(" ") and \
                        re.match(r"^(#|>|```|~~~)", ln.strip()):
                    break
                block.append(ln)
                i += 1
            out.append(_list(block))
            continue
        if line.startswith("    ") and not para:
            code = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                code.append(lines[i][4:])
                i += 1
            while code and not code[-1].strip():
                code.pop()
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        if re.match(r"^<(\w+)[^>]*>", s) and s.split(">")[0][1:].split()[0].lower() in (
                "div", "details", "summary", "p", "img", "br", "table", "center", "picture", "kbd", "sub", "sup"):
            flush()
            # simple HTML in Markdown (badges, <details>): shown as written, minus scripts and handlers
            raw = re.sub(r"<\s*/?\s*(script|iframe|object|embed|style)[^>]*>", "", line, flags=re.I)
            raw = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", raw, flags=re.I)
            raw = re.sub(r"javascript:", "", raw, flags=re.I)
            out.append(raw)
            i += 1
            continue
        para.append(s if not line.endswith("  ") else s + "  ")
        i += 1
    flush()
    return "\n".join(out)


def _list(block: list[str]) -> str:
    first = block[0]
    indent = len(first) - len(first.lstrip())
    ordered = bool(re.match(r"^\s*\d+[.)]", first))
    start = re.match(r"^\s*(\d+)", first)
    items: list[list[str]] = []
    for ln in block:
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", ln)
        if m and len(m.group(1)) <= indent + 1:
            items.append([m.group(3)])
        elif items:
            items[-1].append(ln[indent + 2:] if ln.startswith(" " * (indent + 2)) else ln.strip())
    html_items = []
    for it in items:
        head, rest = it[0], it[1:]
        cls = ""
        task = re.match(r"^\[( |x|X)\]\s+(.*)$", head)
        if task:
            box = "☑" if task.group(1) != " " else "☐"
            head, cls = f"{box} {task.group(2)}", ' class="task"'
        sub = [r for r in rest]
        nested = ""
        text_lines = [head]
        for n, r in enumerate(sub):
            if re.match(r"^\s*([-*+]|\d+[.)])\s+", r):
                nested = markdown_to_html("\n".join(sub[n:]))
                break
            text_lines.append(r)
        txt = "\n".join(t for t in text_lines if t.strip())
        html_items.append(f"<li{cls}>{_inline(txt)}{nested}</li>")
    tag = "ol" if ordered else "ul"
    st = f' start="{int(start.group(1))}"' if ordered and start and int(start.group(1)) != 1 else ""
    return f"<{tag}{st}>" + "".join(html_items) + f"</{tag}>"
