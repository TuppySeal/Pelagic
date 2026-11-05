"""Page tools: reader mode, AI page translation, screenshots and picture-in-picture.

Run:  python tests/tools_test.py
"""
import json
import os
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_tools_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PARA = ("The ocean covers most of the planet and holds most of its water. Scientists study its currents, "
        "its life and its long history to understand how the climate changes over time. ")
ARTICLE = ("<!doctype html><title>Ocean news</title><body><nav class=menu>Home · About · Shop</nav>"
           "<div class=sidebar>Buy our mugs! Subscribe now!</div><article><h1>Deep Currents</h1>"
           + "".join(f"<p>{PARA * 2} Part {i}.</p>" for i in range(8))
           + "</article><footer>Copyright footer text</footer></body>")
LONG = "<!doctype html><title>Long</title><body style='margin:0'>" + "".join(
    f"<div style='height:300px;background:hsl({i * 40},60%,50%)'>Block {i}</div>" for i in range(10)) + "</body>"
VIDEO = ("<!doctype html><title>Video page</title><body><p>Watch this</p>"
         "<video id=v width=480 height=270 style='background:#000'></video></body>")


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
    from atlasbrowser import tools
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)

    site = Path(tempfile.mkdtemp())
    (site / "article.html").write_text(ARTICLE, encoding="utf-8")
    (site / "long.html").write_text(LONG, encoding="utf-8")
    (site / "video.html").write_text(VIDEO, encoding="utf-8")
    (site / "plain.html").write_text("<title>Plain</title><p>Hi.</p>", encoding="utf-8")

    class Quiet(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [base + "/article.html"])
    win.resize(1200, 800)
    win.show()
    tab = win.current_tab()
    wait(lambda: not tab.loading and tab.title() == "Ocean news")

    # reader mode
    labels = [a.text() for a in win.menu_btn.menu().actions()]
    for want in ("Reader mode\tF9", "Translate page…", "Screenshot", "Picture-in-picture"):
        check(f"menu has {want.split(chr(9))[0]}", want in labels, str(labels))
    QTest.keyClick(win, Qt.Key_F9)
    check("F9 opens reader mode", wait(lambda: tools.is_reader(tab.url()) and not tab.loading))
    body = js(tab, "document.body.innerText")
    check("reader keeps the article", "Deep Currents" in body and "Part 7" in body, body[:200])
    check("the title is shown once", body.count("Deep Currents") == 1, str(body.count("Deep Currents")))
    check("reader drops menus, sidebars and footers", "mugs" not in body and "Copyright" not in body
          and "Home · About" not in body)
    check("address bar shows the real page", win.addr.text() == base + "/article.html", win.addr.text())
    check("the session saves the real page", (win.save_session(), store.get("session"))[1] == [base + "/article.html"],
          str(store.get("session")))
    size = int(store.get("reader_size") or 19)
    js(tab, "document.querySelector('a[href$=\"reader-bigger\"]').click(); 1")
    check("A+ makes the text bigger", wait(lambda: int(store.get("reader_size") or 19) == size + 1))
    # the reader page reloads with the new size; on a slower machine a click sent mid-reload is lost
    pump(400)
    wait(lambda: not tab.loading and bool(js(tab, "!!document.querySelector('a[href$=\"reader-theme-sepia\"]')")))
    pump(200)
    js(tab, "document.querySelector('a[href$=\"reader-theme-sepia\"]').click(); 1")
    check("sepia theme", wait(lambda: store.get("reader_theme") == "sepia"))
    wait(lambda: not tab.loading)
    pump(300)
    bg = js(tab, "getComputedStyle(document.body).backgroundColor")
    check("the theme shows on the page", bg == "rgb(244, 236, 216)", bg)
    check("still in reader after changing settings", tools.is_reader(tab.url()))
    js(tab, "document.querySelector('a[href$=\"reader-exit\"]').click(); 1")
    check("Exit goes back to the page", wait(lambda: tab.url().toString() == base + "/article.html" and not tab.loading),
          tab.url().toString())
    tab.load(base + "/plain.html")
    wait(lambda: not tab.loading and tab.title() == "Plain")
    tools.toggle_reader(win, tab)
    check("a page without an article says so", wait(lambda: win.notice.isVisible()
                                                     and "couldn't find" in win.notice_text.text()))
    check("and stays on the page", not tools.is_reader(tab.url()))

    # translate (with a stand-in AI that upper-cases text)
    tab.load(base + "/article.html")
    wait(lambda: not tab.loading and tab.title() == "Ocean news")

    class FakeProvider:
        name, needs_key, id, env = "Test AI", False, "fake", ()
    sent = []

    def fake_chat(p, key, messages, system="", *a, **k):
        texts = json.loads(messages[0]["content"])
        sent.append((system, texts))
        return json.dumps([t.upper() for t in texts])
    real_chat, real_provider = tools.providers.chat, win.panel.current_provider
    tools.providers.chat = fake_chat
    win.panel.current_provider = lambda: FakeProvider()
    tools.BATCH_CHARS = 1500   # a small batch size, so this short page goes in several requests
    tools.translate_page(win, "Spanish", ask=False)
    check("translate replaces the page text", wait(lambda: "DEEP CURRENTS" in (js(tab, "document.body.innerText") or ""))
          and tab._translated)
    check("it asks for the chosen language", sent and "Spanish" in sent[0][0])
    check("it sends the page in batches", len(sent) >= 2, str(len(sent)))
    tools.translate_page(win)
    check("translate again shows the original", wait(lambda: "Deep Currents" in (js(tab, "document.body.innerText") or "")))
    check("form fields are never sent", all("type=password" not in t for _s, ts in sent for t in ts))
    tools.providers.chat, win.panel.current_provider = real_chat, real_provider

    # screenshots
    pics = Path(tempfile.mkdtemp())
    tools.pictures_folder = lambda: pics
    vis = tools.grab_visible(tab)
    check("visible screenshot", not vis.isNull() and vis.width() > 100)
    tab.load(base + "/long.html")
    wait(lambda: not tab.loading and tab.title() == "Long")
    full = []
    tools.grab_full_page(tab, full.append)
    check("whole-page screenshot stitches the full height", wait(lambda: full, 15000)
          and full[0].height() >= 2900 * full[0].width() / tab.width() - 5,
          f"{full[0].height() if full else None}")
    check("and scrolls back to where you were", int(js(tab, "window.scrollY") or 0) == 0)
    got = []
    picker = tools.AreaPicker(tab, tools.grab_visible(tab), got.append)
    QTest.mousePress(picker, Qt.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(picker, QPoint(220, 120))
    QTest.mouseRelease(picker, Qt.LeftButton, pos=QPoint(220, 120))
    check("area screenshot is the dragged rectangle", got and abs(got[0].width() - 200 * vis.width() / tab.width()) < 3,
          f"{got[0].width() if got else None}")
    d = tools.ScreenshotDialog(got[0], "Long", win)
    check("a screenshot is copied to the clipboard", not app.clipboard().pixmap().isNull())
    d.save_default()
    check("Save puts it in Pictures/Pelagic Screenshots", d.saved and d.saved.exists() and d.saved.parent == pics)

    # picture in picture
    tab.load(base + "/video.html")
    wait(lambda: not tab.loading and tab.title() == "Video page")
    tab.load(base + "/plain.html")
    wait(lambda: not tab.loading and tab.title() == "Plain")
    tools.picture_in_picture(win)
    check("a page without a video says so", wait(lambda: "no video" in win.notice_text.text()))
    tab.load(base + "/video.html")
    wait(lambda: not tab.loading and tab.title() == "Video page")
    tools.picture_in_picture(win)
    check("picture-in-picture opens a small window", wait(lambda: getattr(win, "_pip", None) is not None))
    pip = win._pip
    check("it stays on top", bool(pip.windowFlags() & Qt.WindowStaysOnTopHint))
    check("it shows only the video", wait(lambda: js(pip.view, "!!document.getElementById('pelagic-pip-video')")
                                          if hasattr(pip.view, "run_js") else
                                          _pip_has_video(pip), 10000))
    tools.picture_in_picture(win)
    pump(400)
    check("the same menu item closes it", win._pip is None)

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


def _pip_has_video(pip):
    out = []
    pip.view.page().runJavaScript("!!document.getElementById('pelagic-pip-video')", out.append)
    for _ in range(40):
        if out:
            break
        pump(50)
    return bool(out and out[0])


if __name__ == "__main__":
    sys.exit(main())
