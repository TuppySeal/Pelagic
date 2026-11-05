"""Playground: the hidden challenges page opens from pelagic:playground and from five clicks on the homepage logo,
knows it's the built-in copy, checks answers, and keeps your progress.

Run:  python tests/playground_test.py          (add --visible to show the window)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_playground_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, secs=10):
    for _ in range(int(secs * 20)):
        if cond():
            return True
        pump(50)
    return cond()


def js(tab, code):
    out = []
    tab.page().runJavaScript(code, 0, lambda v: out.append(v))
    wait_until(lambda: out, 5)
    return out[0] if out else None


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import playground
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, ["atlas:start"])
    win.resize(1200, 800)
    win.show()
    tab = win.current_tab()
    wait_until(lambda: not tab.loading)

    check("the page ships in assets", playground.PAGE.is_file())
    for typed in ("pelagic:playground", "Pelagic://playground/", "atlas:playground"):
        check(f"typing {typed} opens it", win.to_qurl(typed) == playground.url(), win.to_qurl(typed).toString())
    check("other atlas: addresses still mean the homepage", win.is_start(win.to_qurl("atlas:start")))
    check("ordinary searches are untouched", win.to_qurl("pelagic playground").scheme() == "https")

    # five quick clicks on the homepage logo
    pump(300)
    js(tab, "for (var i = 0; i < 4; i++) document.querySelector('.mark').click()")
    pump(400)
    check("four clicks are not enough", win.is_start(tab.url()), tab.url().toString())
    js(tab, "for (var i = 0; i < 5; i++) document.querySelector('.mark').click()")
    check("five clicks on the logo open the playground", wait_until(lambda: playground.is_playground(tab.url()), 8),
          tab.url().toString())
    wait_until(lambda: not tab.loading)
    pump(500)

    title = js(tab, "document.getElementById('detect-title').textContent")
    check("the page knows it's inside Pelagic", "playground" in (title or "").lower(), title)
    js(tab, "document.getElementById('ans-bin').value = 'the kraken sleeps at noon';"
            "document.querySelector('form[data-check=bin] button').click()")
    check("a right answer turns into a pearl",
          js(tab, "document.querySelector('.ch[data-id=bin]').classList.contains('solved')"))
    check("a wrong answer doesn't", not js(tab, "document.getElementById('ans-morse').value = 'anchor';"
                                              "document.querySelector('form[data-check=morse] button').click();"
                                              "document.querySelector('.ch[data-id=morse]').classList.contains('solved')"))
    check("the restock phrase isn't on the page while sold out (so watchers don't fire early)",
          js(tab, "Date.now() % 120000 < 30000") or not js(tab, "/in stock/i.test(document.body.innerText)"))

    # dark mode only runs on websites, so the built-in copy sends you to a bright one and lets you tick it off
    check("the dark mode card offers a website to try",
          js(tab, "!document.getElementById('dark-self').hidden && "
                  "!!document.querySelector('#dark-task a[href^=\"https://\"]')"))
    done = []
    tab.loadFinished.connect(done.append)
    tab.reload()
    wait_until(lambda: done)
    pump(300)
    check("progress survives a reload", js(tab, "document.querySelector('.ch[data-id=bin]').classList.contains('solved')"))

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
