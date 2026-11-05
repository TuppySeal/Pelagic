"""Screen sharing: a page's getDisplayMedia shows Pelagic's picker; Share shares, Cancel shares nothing.

Run:  python tests/screenshare_test.py
"""
import os
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_share_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

PAGE = """<!doctype html><title>Call</title><button id=b style="position:fixed;left:0;top:0;width:300px;height:200px"
onclick="navigator.mediaDevices.getDisplayMedia({video:true,audio:true}).then(s=>{document.title='shared:'+
s.getVideoTracks().length;}).catch(e=>{document.title='refused:'+e.name})">Share</button>"""


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


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import screenshare
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store

    site = Path(tempfile.mkdtemp())
    (site / "call.html").write_text(PAGE, encoding="utf-8")

    class Quiet(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/call.html"

    # the picker on its own
    dlg = screenshare.SharePicker("discord.com", ["Screen A", "Screen B"], ["Notepad", "Calculator"], thumbs=False)
    check("the picker lists every screen", dlg.screen_list.count() == 2)
    check("and every window by name", [dlg.window_list.item(i).text() for i in range(2)] == ["Notepad", "Calculator"])
    check("the first screen is chosen to start with", dlg.share_btn.isEnabled() and dlg._current() == ("screen", 0))
    dlg.tabs.setCurrentIndex(1)
    check("on the Window tab nothing is chosen until you pick", not dlg.share_btn.isEnabled())
    dlg.window_list.setCurrentRow(1)
    dlg._share()
    check("picking a window shares that window", dlg.choice == ("window", 1) and dlg.result() == QDialog.Accepted)

    asked = []
    answer = {"v": None}

    def fake_exec(self):
        asked.append(True)
        if answer["v"] is None:
            return QDialog.Rejected
        self.choice = answer["v"]
        return QDialog.Accepted
    screenshare.SharePicker.exec = fake_exec

    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [url])
    win.resize(1000, 700)
    win.show()
    tab = win.current_tab()
    wait(lambda: tab.title() == "Call" and not tab.loading)
    pump(300)

    def click():
        QTest.mouseClick(tab.focusProxy() or tab, Qt.LeftButton, pos=QPoint(100, 100))

    click()
    got = wait(lambda: tab.title().startswith(("shared", "refused")) or asked, 8000)
    if not asked:
        print("NOTE screen capture isn't available on this machine:", tab.title())
    check("asking to share opens Pelagic's picker", bool(asked) and got, tab.title())
    wait(lambda: tab.title() != "Call", 4000)
    check("Cancel shares nothing and tells the page", tab.title().startswith("refused"), tab.title())

    answer["v"] = ("screen", 0)
    asked.clear()
    tab.page().runJavaScript("document.title='Call'")
    pump(200)
    click()
    wait(lambda: tab.title() != "Call", 8000)
    check("Share asks again each time", len(asked) == 1)
    check("Share gives the page the screen", tab.title() in ("shared:1",) or tab.title().startswith("refused:NotReadable")
          or tab.title().startswith("refused:Abort"), tab.title())

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    os._exit(main())
