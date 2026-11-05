"""History page (Pelagic and Chrome), reading list, and session restore after a crash.

Run:  python tests/library_test.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_library_test_")

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


def fake_chrome(root: Path):
    """A Chrome 'User Data' folder with two profiles."""
    (root).mkdir(parents=True)
    (root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Tuppy"}, "Profile 1": {"name": "School"}}}}))
    to_chrome = lambda t: int((t + 11644473600) * 1_000_000)   # noqa: E731
    now = time.time()
    for folder, rows in (("Default", [("https://chrome-one.example/", "Chrome One", now - 60),
                                      ("https://chrome-two.example/", "Chrome Two", now - 86400 * 3)]),
                         ("Profile 1", [("https://school.example/", "School Site", now - 120)])):
        d = root / folder
        d.mkdir()
        db = sqlite3.connect(d / "History")
        db.execute("CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
        db.execute("CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
        for i, (u, title, t) in enumerate(rows, 1):
            db.execute("INSERT INTO urls VALUES(?,?,?)", (i, u, title))
            db.execute("INSERT INTO visits(url, visit_time) VALUES(?,?)", (i, to_chrome(t)))
            db.execute("INSERT INTO visits(url, visit_time) VALUES(?,?)", (i, to_chrome(t) + 1_000_000))   # reload
        db.commit()
        db.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import library
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)

    # Chrome history, read only
    chrome = Path(tempfile.mkdtemp()) / "User Data"
    fake_chrome(chrome)
    before = {p: p.read_bytes() for p in chrome.rglob("History")}
    profiles = library.chrome_profiles(chrome)
    check("finds Chrome profiles by their names", [n for n, _ in profiles] == ["Tuppy", "School"], str(profiles))
    rows = library.chrome_history(profiles[0][1])
    check("reads Chrome visits newest first, without duplicate reloads",
          [r[1] for r in rows] == ["Chrome One", "Chrome Two"], str(rows))
    check("Chrome visit times convert correctly", abs(rows[0][2] - (time.time() - 60)) < 5)
    check("search works on Chrome history", [r[1] for r in library.chrome_history(profiles[0][1], "two")] == ["Chrome Two"])
    check("Chrome's files are not changed", all(p.read_bytes() == b for p, b in before.items()))

    store = Store()
    store.add_history("https://pelagic-a.example/", "Pelagic A")
    store.add_history("https://pelagic-b.example/", "Pelagic B")
    d = library.HistoryDialog(store, chrome_dir=chrome)
    top = d.pelagic.topLevelItem(0)
    check("Pelagic history is grouped by day", top.text(0) == "Today" and top.childCount() == 2,
          f"{top.text(0)} {top.childCount()}")
    check("tabs are named Pelagic and Chrome", [d.tabs.tabText(i) for i in range(2)] == ["Pelagic", "Chrome"])
    d.tabs.setCurrentIndex(1)
    heads = [d.chrome.topLevelItem(i).text(0) for i in range(d.chrome.topLevelItemCount())]
    check("Chrome tab shows its own history by day", heads[0] == "Today" and len(heads) == 2, str(heads))
    d.chrome_profile.setCurrentIndex(1)
    check("switching Chrome profile", d.chrome.topLevelItem(0).child(0).text(1) == "School Site")
    d.tabs.setCurrentIndex(0)
    d.search.setText("pelagic-b")
    check("search filters Pelagic history", d.pelagic.topLevelItem(0).childCount() == 1)
    d.pelagic.topLevelItem(0).child(0).setSelected(True)
    d._delete()
    check("delete selected", [r[0] for r in store.history()] == ["https://pelagic-a.example/"])
    check("missing Chrome is handled", library.HistoryDialog(store, chrome_dir=Path(tempfile.mkdtemp())).chrome_profiles == [])

    # reading list
    check("add to reading list", store.add_to_reading_list("https://read.example/", "Read me"))
    check("no duplicates", not store.add_to_reading_list("https://read.example/", "Read me"))
    r = library.ReadingListDialog(store)
    check("reading list shows it as unread", r.tree.topLevelItem(0).text(0) == "Unread (1)")
    opened = []
    r.open_url.connect(opened.append)
    r._open(r.tree.topLevelItem(0).child(0))
    r.reload()
    check("opening marks it read", opened == ["https://read.example/"] and r.tree.topLevelItem(0).text(0) == "Read (1)")
    store.update_reading_list("https://read.example/", remove=True)
    check("remove", store.reading_list() == [])

    # crash: tabs are autosaved, and the next start says so
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{srv.server_port}/crash-a"
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, ["data:text/html,start"])
    pump(500)
    win.open_tab(page)
    pump(1000)
    win.save_session()   # what the 15-second timer does
    check("open tabs are saved while running", page in (store.get("session") or []),
          str(store.get("session")))
    check("marked as running", store.get("running") is True)
    # simulate a crash: start a second app on the same data without closing the first
    check("the next start would know Pelagic didn't close properly", Store(store.root).get("running") is True)
    win.ctx.crashed = True
    win.close()
    pump(300)
    w2 = hub.open_profile(DEFAULT_ID)
    from atlasbrowser.tools import page_url

    def restored():
        return any("crash-a" in page_url(t).toString() for t in w2.tab_list())
    for _ in range(100):   # a slower machine can take a few seconds before the restored tabs report their address
        if restored():
            break
        pump(50)
    check("after a crash the tabs come back with a notice", w2.notice.isVisible() and restored(),
          str((w2.notice.isVisible(), w2.notice_text.text(), [page_url(t).toString() for t in w2.tab_list()],
               store.get("session"))))
    w2.close()
    hub.stop_all()
    check("a normal close clears the running mark", Store(store.root).get("running") is False)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    os._exit(code)   # skip Qt's shutdown, which can crash after the checks are done (like the other tests)
