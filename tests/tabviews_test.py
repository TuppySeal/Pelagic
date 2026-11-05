"""Tab hover previews, split view, vertical tabs and workspaces.

Run:  python tests/tabviews_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_tabviews_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(cond, ms=6000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def page(n, color="#fff"):
    return f"data:text/html,<title>Page {n}</title><body style='background:{color}'><h1>Page {n}</h1>"


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import tabviews
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [page(0, "red"), page(1, "blue"), page(2, "green")])
    win.resize(1300, 800)
    win.show()
    wait(lambda: all(not t.loading for t in win.tab_list()), 6000)
    pump(500)
    tabs, bar, strip = win.tab_list(), win.tabs.tabBar(), win.strip

    # hover previews
    win.select_tab(tabs[0])
    pump(400)
    win.select_tab(tabs[1])
    pump(300)
    check("leaving a tab keeps a picture of it", getattr(tabs[0], "_thumb", None) is not None
          and not tabs[0]._thumb.isNull())
    win.activateWindow()   # previews only show while Pelagic is the window in front
    wait(lambda: win.isActiveWindow(), 2000)
    r = bar.tabRect(win.tabs.indexOf(tabs[0]))
    QTest.mouseMove(bar, r.center())
    pump(50)
    QTest.mouseMove(bar, r.center() + QPoint(3, 0))
    check("resting on a tab shows its preview", wait(lambda: win.previews.card is not None and win.previews.card.isVisible(), 2000))
    card = win.previews.card
    check("the preview has the title and a picture", "Page 0" in card.title.text() and card.pic.isVisibleTo(card),
          card.title.text())
    r1 = bar.tabRect(win.tabs.indexOf(tabs[1]))
    QTest.mouseMove(bar, r1.center())
    pump(100)
    check("moving to the current tab shows its title without a picture",
          card.tab is tabs[1] and not card.pic.isVisibleTo(card),
          str((card.tab is tabs[1], card.isVisible(), card.pic.isVisibleTo(card), win.isActiveWindow(), win.previews._over_tabs())))
    check("the preview belongs to this window, not floating above other apps",
          card.parent() is win and not (card.windowFlags() & Qt.WindowStaysOnTopHint)
          and (card.windowFlags() & Qt.WindowType_Mask) != Qt.ToolTip)
    QTest.mouseMove(win.addr, win.addr.rect().center())   # off the tabs without a leave event reaching the strip
    check("it goes away when the pointer is no longer over the tabs", wait(lambda: not card.isVisible(), 1500))
    QTest.mouseMove(bar, r.center())
    pump(50)
    QTest.mouseMove(bar, r.center() + QPoint(2, 0))
    wait(lambda: card.isVisible(), 2000)
    win.select_tab(tabs[2])
    check("switching tabs hides it", not card.isVisible())
    win.select_tab(tabs[1])
    QTest.mouseMove(bar, r.center())
    pump(50)
    QTest.mouseMove(bar, r.center() + QPoint(3, 0))
    wait(lambda: card.isVisible(), 2000)
    win.showMinimized()
    check("minimising the window hides it", wait(lambda: not card.isVisible(), 1500))
    win.showNormal()
    win.activateWindow()
    pump(300)
    win.previews.hide()
    store.set("tab_previews", False)
    QTest.mouseMove(bar, r.center())
    pump(700)
    check("previews can be turned off in Settings", not card.isVisible())
    store.set("tab_previews", True)

    # split view
    win.select_tab(tabs[0])
    pump(200)
    strip.split_view()
    pump(300)
    check("split view shows two tabs side by side", win.tabs.split == [tabs[0], tabs[1]]
          and tabs[0].isVisible() and tabs[1].isVisible(), str(win.tabs.split))
    g0, g1 = tabs[0].geometry(), tabs[1].geometry()
    check("left and right halves", g0.right() < g1.left() and abs(g0.width() - g1.width()) < 30, f"{g0} {g1}")
    tabs[1].setFocus()
    pump(200)
    check("clicking into the right half makes it the current tab", win.current_tab() is tabs[1])
    check("and the split stays", tabs[0].isVisible() and tabs[1].isVisible())
    check("tab menu offers Exit split view", any("Exit split view" in a.text() for a in strip.tab_menu(tabs[0]).actions()))
    state = strip.layout_state(win.tab_list())
    check("the split is saved with the session", state.get("split") == [0, 1], str(state.get("split")))
    win.select_tab(tabs[2])
    pump(200)
    check("another tab shows on its own", tabs[2].isVisible() and not tabs[0].isVisible())
    win.select_tab(tabs[0])
    pump(200)
    check("going back brings the split back", tabs[0].isVisible() and tabs[1].isVisible())
    check("tabs in a split view don't go to sleep", not win.sleeper.can_sleep(tabs[1]))
    strip.split_view()
    pump(200)
    check("Split view again ends it", win.tabs.split is None and tabs[0].isVisible() and not tabs[1].isVisible())
    strip.split_view(tabs[2])
    pump(200)
    win.close_tab_obj(tabs[2])
    pump(200)
    check("closing one side ends the split", win.tabs.split is None and win.current_tab().isVisible())
    tabs = win.tab_list()

    # vertical tabs
    gid = strip.new_group([tabs[1]], name="Work")
    win.set_vertical_tabs(True)
    pump(300)
    vt = win.vtabs
    check("vertical tabs show down the left", vt.isVisible() and not bar.isVisible() and not win.tabs.row.isVisible())
    kinds = [(vt.list.item(n).data(tabviews.KIND), vt.list.item(n).text()) for n in range(vt.list.count())]
    check("they list every tab, with the group's label", [k for k, _ in kinds] == ["tab", "group", "tab"]
          and "Work" in kinds[1][1], str(kinds))
    win.open_tab(page(5))
    wait(lambda: vt.list.count() == 4 and "Page 5" in vt.list.item(3).text())   # its title comes once it loads
    check("a new tab appears in the list", vt.list.count() == 4 and "Page 5" in vt.list.item(3).text(),
          str([vt.list.item(n).text() for n in range(vt.list.count())]))
    rect = vt.list.visualItemRect(vt.list.item(0))
    QTest.mouseClick(vt.list.viewport(), Qt.LeftButton, pos=rect.center())
    pump(200)
    check("clicking a tab in the list switches to it", win.current_tab() is tabs[0])
    QTest.mouseClick(vt.list.viewport(), Qt.LeftButton, pos=vt.list.visualItemRect(vt.list.item(1)).center())
    pump(200)
    check("clicking the group label collapses it", strip.groups[gid]["collapsed"] and vt.list.count() == 3,
          str(vt.list.count()))
    strip.toggle_collapse(gid)
    pump(200)
    # drag: move the last tab to the top by reordering the list like a drop does
    it = vt.list.takeItem(3)
    vt.list.insertItem(0, it)
    vt.dropped()
    pump(200)
    check("dragging in the list reorders the tabs", "Page 5" in (win.tab_list()[0].title() or ""),
          str([t.title() for t in win.tab_list()]))
    rect = vt.list.visualItemRect(vt.list.item(0))
    QTest.mouseClick(vt.list.viewport(), Qt.MiddleButton, pos=rect.center())
    pump(300)
    check("middle-click closes a tab from the list", len(win.tab_list()) == 2)
    win.set_fullscreen(True)
    pump(200)
    check("in F11 the top row comes back for the window buttons", win.tabs.row.isVisible() and win.window_buttons.isVisible())
    win.set_fullscreen(False)
    pump(200)
    check("and goes away again after", not win.tabs.row.isVisible())
    win.set_vertical_tabs(False)
    pump(200)
    check("turning vertical tabs off brings the tab strip back", bar.isVisible() and win.tabs.row.isVisible()
          and not vt.isVisible())

    # workspaces (they keep web pages, like the saved session)
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for n, t in enumerate(win.tab_list()):
        t.load(f"http://127.0.0.1:{srv.server_port}/ws-{n}")
    wait(lambda: all("ws-" in t.url().toString() and not t.loading for t in win.tab_list()))
    before = [t.url().toString() for t in win.tab_list()]
    check("starts in the Main workspace", tabviews.current_workspace(store) == "Main")
    from PySide6.QtWidgets import QInputDialog
    QInputDialog.getText = staticmethod(lambda *a, **k: ("School", True))
    tabviews.new_workspace(win)
    pump(500)
    check("a new workspace starts with one fresh tab", len(win.tab_list()) == 1 and tabviews.current_workspace(store) == "School")
    win.current_tab().load(f"http://127.0.0.1:{srv.server_port}/school")
    wait(lambda: "school" in win.current_tab().url().toString())
    tabviews.switch_workspace(win, "Main")
    wait(lambda: len(win.tab_list()) == len(before))
    pump(500)
    check("switching back brings the old tabs back", [t.url().toString() for t in win.tab_list()] == before,
          str([t.url().toString() for t in win.tab_list()]))
    check("with their group", any(getattr(t, "_group", None) for t in win.tab_list()))
    check("switching doesn't fill 'reopen closed tab'", not any("school" in u for u in strip.closed))
    tabviews.switch_workspace(win, "School")
    wait(lambda: "school" in win.current_tab().url().toString())
    check("and the other workspace kept its tab", [t.url().toString() for t in win.tab_list()]
          == [f"http://127.0.0.1:{srv.server_port}/school"])
    tabviews.switch_workspace(win, "Main")
    wait(lambda: len(win.tab_list()) == len(before))
    menu = win.menu_btn.menu()
    menu.aboutToShow.emit()
    titles = [a.text() for a in menu.actions()]
    check("the menu shows the workspace you're in", "Workspace: Main" in titles, str(titles))
    from PySide6.QtWidgets import QMenu
    wm = QMenu()
    tabviews.fill_menu(win, wm)
    names = [a.text() for a in wm.actions()]
    check("the workspace menu lists both", names[:2] == ["Main", "School"], str(names))
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    tabviews.delete_workspace(win, "School")
    check("delete a workspace", "School" not in tabviews.workspaces(store))
    for name in ("Split view\tCtrl+Shift+E", "Vertical tabs"):
        check(f"menu has {name.split(chr(9))[0]}", name in titles, str(titles))

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

