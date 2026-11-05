"""Opening files from the computer: Markdown shown formatted (with its source a click away), text files in a readable
view, Ctrl+O, paths typed or passed on the command line.

Run:  python tests/fileview_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_fileview_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

NOTES = """# Shopping list

Things to get **today**, see [the other list](other.md) and <https://example.com>.

- milk
- bread
  - brown
- [x] eggs

```
code <stays> as written
```

| Item | Price |
|------|------:|
| Tea  | 2.50  |

<script>document.title = "hacked"</script>
"""


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(cond, ms=8000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def js(tab, code):
    out = []
    tab.run_js(code, out.append)
    wait(lambda: out, 4000)
    return out[0] if out else None


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import fileview, tools
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)

    docs = Path(tempfile.mkdtemp(prefix="pelagic docs "))
    (docs / "notes.md").write_text(NOTES, encoding="utf-8")
    (docs / "other.md").write_text("# Other list\n\nJust *one* thing.\n", encoding="utf-8")
    # written with Windows line endings on every system (Notepad's), so the check is the same everywhere
    (docs / "readme.txt").write_bytes(b"Plain <b>text</b>\r\n  keeps   its spacing\r\n")
    (docs / "mac.txt").write_bytes(b"one\rtwo\r")
    (docs / "data.json").write_text('{"a":1,"b":[1,2]}', encoding="utf-8")
    (docs / "old.txt").write_bytes("caf\xe9 in Windows-1252".encode("cp1252"))

    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [str(docs / "notes.md")])   # like "Open with Pelagic"
    win.resize(1200, 800)
    win.show()
    tab = win.current_tab()
    in_view = lambda: fileview.is_view(tab.url()) and not tab.loading  # noqa: E731
    check("a Markdown path from the command line opens", wait(lambda: in_view() and tab.title() == "notes.md"),
          tab.url().toString())
    check("the address bar shows the file, not the view page", win.addr.text().endswith("notes.md")
          and "fileview-" not in win.addr.text(), win.addr.text())
    check("it's formatted", js(tab, "document.querySelector('main h1').textContent") == "Shopping list"
          and js(tab, "document.querySelectorAll('main li').length") == 4
          and js(tab, "document.querySelector('main strong').textContent") == "today",
          str([js(tab, "document.querySelector('main h1').textContent"), js(tab, "document.querySelectorAll('main li').length")]))
    check("tables and code blocks too", js(tab, "document.querySelector('main td:last-child').style.textAlign") == "right"
          and js(tab, "document.querySelector('main pre').textContent") == "code <stays> as written")
    check("scripts in the file don't run", tab.title() == "notes.md"
          and js(tab, "document.querySelectorAll('main script').length") == 0)
    check("a ticked task shows ticked", "☑ eggs" in js(tab, "document.querySelector('main').innerText"))
    bg = js(tab, "getComputedStyle(document.body).backgroundColor")
    check("it uses the dark reading colours by default", bg == "rgb(22, 24, 29)", bg)

    js(tab, "[...document.querySelectorAll('.bar a')].find(a => a.textContent == 'Show source').click(); 1")
    check("Show source shows the Markdown as written", wait(lambda: in_view() and "# Shopping list" in (
        js(tab, "document.querySelector('pre.text') ? document.querySelector('pre.text').textContent : ''") or "")))
    check("still showing the file's address", win.addr.text().endswith("notes.md"), win.addr.text())
    js(tab, "[...document.querySelectorAll('.bar a')].find(a => a.textContent == 'Show formatted').click(); 1")
    check("and back to formatted", wait(lambda: in_view() and js(tab, "!!document.querySelector('main h1')") is True))
    js(tab, "[...document.querySelectorAll('.bar a')].find(a => a.textContent == 'Light').click(); 1")
    check("the colour choice is remembered (shared with reader mode)", wait(lambda: store.get("reader_theme") == "light"))
    wait(lambda: in_view() and js(tab, "getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)")
    check("and shown", js(tab, "getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)")
    store.set("reader_theme", "dark")

    js(tab, "document.querySelector('main a[href=\"other.md\"]').click(); 1")
    check("a link to another Markdown file opens it the same way",
          wait(lambda: in_view() and tab.title() == "other.md") and win.addr.text().endswith("other.md"), win.addr.text())
    (docs / "other.md").write_text("# Other list, edited\n", encoding="utf-8")
    tab.reload()
    check("Reload (F5) shows changes made to the file",
          wait(lambda: in_view() and js(tab, "document.querySelector('main h1').textContent") == "Other list, edited"))
    tab.back()
    check("Back returns to the first file", wait(lambda: in_view() and tab.title() == "notes.md"), tab.title())

    # text files
    tab.load(QUrl.fromLocalFile(str(docs / "readme.txt")))
    check("a text file gets the readable view", wait(lambda: in_view() and tab.title() == "readme.txt"))
    text = js(tab, "document.querySelector('pre.text').textContent")
    check("its text is shown exactly, not as HTML", text == "Plain <b>text</b>\n  keeps   its spacing\n", repr(text))
    check("no source button for plain text", js(tab, "document.querySelector('.bar').innerText.includes('source')")
          is False)
    tab.load(QUrl.fromLocalFile(str(docs / "mac.txt")))
    wait(lambda: in_view() and tab.title() == "mac.txt")
    check("old Mac line endings too", js(tab, "document.querySelector('pre.text').textContent") == "one\ntwo\n")
    tab.load(QUrl.fromLocalFile(str(docs / "data.json")))
    wait(lambda: in_view() and tab.title() == "data.json")
    check("JSON is laid out to read", '"b": [' in (js(tab, "document.querySelector('pre.text').textContent") or ""))
    tab.load(QUrl.fromLocalFile(str(docs / "old.txt")))
    wait(lambda: in_view() and tab.title() == "old.txt")
    check("older Windows text files read correctly", "café" in (js(tab, "document.body.innerText") or ""))

    # typing a path, Ctrl+O's opener, the menu
    check("a typed path opens the file", win.to_qurl(str(docs / "readme.txt")) == QUrl.fromLocalFile(str(docs / "readme.txt")))
    check("ordinary searches still search", "search" in win.to_qurl("what is markdown").toString().lower()
          or "q=" in win.to_qurl("what is markdown").toString())
    check("a Windows-style path is recognised", fileview.to_url("C:\\no\\such\\file.md") is None
          and fileview.to_url("not a path") is None)
    labels = [a.text() for a in win.menu_btn.menu().actions()]
    check("the menu has Open file (Ctrl+O)", "Open file…\tCtrl+O" in labels, str(labels))
    win.open_tab()
    start = win.current_tab()
    wait(lambda: win.is_start(start.url()) and not start.loading)
    before = len(win.tab_list())
    win.open_paths([str(docs / "other.md"), str(docs / "readme.txt")])
    check("opening files uses the empty new-tab page first", len(win.tab_list()) == before + 1
          and wait(lambda: fileview.is_view(start.url())), str((before, len(win.tab_list()), start.url().toString())))
    check("each further file gets its own tab", wait(lambda: win.tab_list()[-1].title() == "readme.txt"))
    check("the file view page stands for the file in the tab list", tools.page_url(start).toLocalFile().endswith("other.md"))
    (docs / "page.html").write_text("<title>My page</title><h1 id=h>Hello from a file</h1>", encoding="utf-8")
    win.open_paths([str(docs / "page.html")])
    page = win.tab_list()[-1]
    check("an .html file opens as a normal web page", wait(lambda: page.title() == "My page" and not page.loading)
          and js(page, "document.getElementById('h').textContent") == "Hello from a file"
          and page.url().toLocalFile().endswith("page.html"), page.url().toString())
    check("an .html path from the command line or address bar opens it",
          win.to_qurl(str(docs / "page.html")) == QUrl.fromLocalFile(str(docs / "page.html")))
    check("the types offered for Open with", {".md", ".markdown", ".txt"} <= set(fileview.OPEN_WITH))

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    os._exit(code)
