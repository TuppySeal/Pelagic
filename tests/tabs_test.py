"""Tabs and DevTools: equal-width tabs, pinning, tab groups, reopen closed tab, tab search, session restore,
and the docked developer tools (Ctrl+Shift+I, Ctrl+Shift+C, right-click Inspect).

Run:  python tests/tabs_test.py          (add --visible to show the window)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_tabs_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabBar  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def page(n):
    return f"data:text/html,<title>Page {n}</title><h1>Page {n}</h1>"


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [page(i) for i in range(5)])
    win.resize(1300, 800)
    win.show()
    pump(1500)
    strip, bar = win.strip, win.tabs.tabBar()
    tabs = win.tab_list()

    widths = {bar.tabRect(i).width() for i in range(bar.count())}
    check("all tabs are the same width", len(widths) == 1, str(widths))
    for _ in range(25):
        win.open_tab(page(9), background=True)
    pump(300)
    w_many = {bar.tabRect(i).width() for i in range(bar.count())}
    from atlasbrowser.tabstrip import TAB_MIN
    check("with many tabs they stay equal and readable (extra tabs scroll)", len(w_many) == 1 and
          min(w_many) >= TAB_MIN, str(w_many))
    check("tabs sit above the address bar", win.tabs.row.geometry().bottom() < win.addr.mapTo(win, win.addr.rect().topLeft()).y())
    for t in win.tab_list()[5:]:
        win.close_tab_obj(t)
    pump(200)
    check("closing them brings the width back", {bar.tabRect(i).width() for i in range(bar.count())} == widths)

    # pinning
    strip.set_pinned(tabs[3], True)
    pump(100)
    check("pinned tab moves to the front", win.tabs.indexOf(tabs[3]) == 0)
    check("pinned tab is narrow with no title", bar.tabRect(0).width() < 60 and bar.tabText(0) == "",
          f"{bar.tabRect(0).width()} '{bar.tabText(0)}'")

    # groups
    gid = strip.new_group([tabs[0], tabs[2]], name="Work")
    pump(100)
    order = win.tab_list()
    i0, i2 = order.index(tabs[0]), order.index(tabs[2])
    check("grouped tabs sit together", abs(i0 - i2) == 1, f"{i0} {i2}")
    head = order[min(i0, i2)]
    chip = bar.tabButton(win.tabs.indexOf(head), QTabBar.LeftSide)
    check("group chip shows its name", chip is not None and chip.text() == "Work")
    strip.add_to_group(tabs[4], gid)
    pump(50)
    check("adding a tab pulls it next to the group", sorted(win.tab_list().index(t) for t in strip.members(gid)) ==
          list(range(min(win.tab_list().index(t) for t in strip.members(gid)),
                     min(win.tab_list().index(t) for t in strip.members(gid)) + 3)))
    win.select_tab(tabs[1])
    strip.toggle_collapse(gid)
    pump(100)
    hidden = [t for t in strip.members(gid) if not bar.isTabVisible(win.tabs.indexOf(t))]
    check("collapsing hides the group's tabs but keeps the chip", len(hidden) == 2 and chip.isVisible())
    win.select_tab(tabs[2])
    pump(100)
    check("switching to a tab in a collapsed group expands it", not strip.groups[gid]["collapsed"])
    strip.set_group(gid, color="#e0605a", name="Jobs")
    pump(50)
    check("rename and recolour", strip.groups[gid]["name"] == "Jobs" and strip.groups[gid]["color"] == "#e0605a")

    # moving a group: drag its label
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    def mouse(w, kind, gx, buttons):
        g = QPointF(gx, bar.mapToGlobal(bar.rect().center()).y())
        local = QPointF(w.mapFromGlobal(g.toPoint()))
        app.sendEvent(w, QMouseEvent(kind, local, g, Qt.LeftButton, buttons, Qt.NoModifier))

    def drag_chip(to_x):
        head = strip.members(gid)[0]
        c = bar.tabButton(win.tabs.indexOf(head), QTabBar.LeftSide)
        start = c.mapToGlobal(c.rect().center()).x()
        mouse(c, QEvent.MouseButtonPress, start, Qt.LeftButton)
        for k in range(1, 11):
            mouse(c, QEvent.MouseMove, start + (to_x - start) * k / 10, Qt.LeftButton)
            pump(20)
        mouse(c, QEvent.MouseButtonRelease, to_x, Qt.NoButton)
        pump(100)

    def group_slots():
        order = win.tab_list()
        return sorted(order.index(t) for t in strip.members(gid))

    n_tabs = win.tabs.count()
    drag_chip(bar.mapToGlobal(bar.tabRect(n_tabs - 1).topRight()).x() + 5)
    check("dragging a group's label moves the whole group to the end",
          group_slots() == list(range(n_tabs - 3, n_tabs)), str(group_slots()))
    check("dragging the label doesn't collapse the group", not strip.groups[gid]["collapsed"])
    drag_chip(bar.mapToGlobal(bar.tabRect(1).topLeft()).x() + 3)
    check("and back to the front (after pinned tabs)", group_slots() == [1, 2, 3], str(group_slots()))
    check("pinned tab stays first", win.tab_list()[0] is tabs[3])
    free = [t for t in win.tab_list() if not t._pinned and t._group is None][0]
    bar.moveTab(win.tabs.indexOf(free), 2)
    strip.after_drag()
    check("a tab dropped inside a group joins it", free._group == gid and group_slots() == [1, 2, 3, 4])
    last = win.tabs.count() - 1
    bar.moveTab(win.tabs.indexOf(free), last)
    strip.after_drag((free, bar.tabRect(last).center().x() + 5))
    check("a tab dropped at the end of its group stays in it", free._group == gid)
    strip.after_drag((free, bar.tabRect(last).center().x() + bar.tabRect(last).width()))
    check("a tab dragged well past the end of its group leaves it", free._group is None)
    saved = strip.layout_state(win.tab_list())
    check("the new order is what gets saved", [r["group"] for r in saved["tabs"]] == [None, gid, gid, gid, None],
          str(saved["tabs"]))
    menu = strip.tab_menu(tabs[0])
    labels = [a.text() for a in menu.actions()]
    for want in ("Remove from group", "Duplicate", "Pin", "Mute site", "Close other tabs", "Close tabs to the right"):
        check(f"tab menu has {want}", any(want in l for l in labels), str(labels))

    # duplicate, reopen closed
    n = win.tabs.count()
    dup = strip.duplicate(tabs[1])
    pump(300)
    check("duplicate opens next to the original", win.tabs.count() == n + 1 and
          win.tabs.indexOf(dup) == win.tabs.indexOf(tabs[1]) + 1)
    win.close_tab_obj(dup)
    pump(100)
    win.close_tab_obj(tabs[1])
    pump(100)
    check("closed tab remembered", strip.closed and "Page 1" in strip.closed[-1].replace("%20", " "))
    QTest.keySequence(win, QKeySequence("Ctrl+Shift+T"))
    pump(500)
    check("Ctrl+Shift+T reopens it", any("Page 1" in (t.title() or "") for t in win.tab_list()),
          str([t.title() for t in win.tab_list()]))

    # tab search
    from atlasbrowser.tabstrip import TabSearch
    ts = TabSearch(strip)
    ts.edit.setText("page 4")
    check("tab search filters by title", ts.list.count() == 1, str(ts.list.count()))
    ts._pick()
    check("picking a result switches to it", win.current_tab() is tabs[4])

    # session layout round trip
    state = strip.layout_state(win.tab_list())
    rows = [(t._pinned, t._group) for t in win.tab_list()]
    for t in win.tab_list():
        t._pinned, t._group = False, None
    strip.groups = {}
    strip.restore_layout(state)
    check("pins and groups restore from the saved session", [(t._pinned, t._group) for t in win.tab_list()] == rows)

    # developer tools
    win.select_tab(tabs[2])
    QTest.keySequence(win, QKeySequence("Ctrl+Shift+I"))
    pump(1500)
    check("Ctrl+Shift+I opens docked DevTools", win.dev_dock.isVisible() and tabs[2] in win._devtools)
    check("DevTools are attached to the tab", tabs[2].page().devToolsPage() is win._devtools[tabs[2]].page())
    win.select_tab(tabs[4])
    pump(200)
    check("DevTools hide on a tab without them", not win.dev_dock.isVisible())
    win.select_tab(tabs[2])
    pump(200)
    check("and come back with their tab", win.dev_dock.isVisible())
    QTest.keySequence(win, QKeySequence("Ctrl+Shift+I"))
    pump(200)
    check("Ctrl+Shift+I closes them again", not win.dev_dock.isVisible())
    win.select_tab(tabs[4])
    QTest.keySequence(win, QKeySequence("Ctrl+Shift+C"))
    pump(2500)
    check("Ctrl+Shift+C opens DevTools for element picking", win.dev_dock.isVisible() and tabs[4] in win._devtools)
    dv = win._devtools[tabs[4]]

    def dev_js(code):
        out = []
        dv.page().runJavaScript(code, out.append)
        for _ in range(60):
            if out:
                break
            pump(50)
        return out[0] if out else None
    PICK_STATE = ("import('devtools://devtools/bundled/ui/legacy/legacy.js').then(function(m){window.__ps="
                  "m.ActionRegistry.ActionRegistry.instance().getAction('elements.toggle-element-search').toggled()});1")

    def picker_on():
        dev_js("window.__ps=null;" + PICK_STATE)
        pump(400)
        return dev_js("window.__ps") is True
    check("the element picker is on", picker_on())
    dev_js("import('devtools://devtools/bundled/ui/legacy/legacy.js').then(function(m){"
           "m.ActionRegistry.ActionRegistry.instance().getAction('elements.toggle-element-search').execute()});1")
    pump(600)
    check("(picking an element turns it off)", not picker_on())
    QTest.keySequence(win, QKeySequence("Ctrl+Shift+C"))
    pump(1500)
    check("Ctrl+Shift+C again lets you pick another element", picker_on() and win.dev_dock.isVisible())
    dev_js("InspectorFrontendHost.closeWindow(); 1")
    pump(600)
    check("DevTools' own close button closes them", not win.dev_dock.isVisible() and not tabs[4]._devtools_open)
    QTest.keySequence(win, QKeySequence("Ctrl+Shift+C"))
    pump(1500)
    check("and they open again after", win.dev_dock.isVisible())
    from PySide6.QtWebEngineCore import QWebEnginePage
    menu_actions = []
    orig_popup = None
    from PySide6.QtWidgets import QMenu
    orig_popup = QMenu.popup
    QMenu.popup = lambda self, *a: menu_actions.extend(x.text() for x in self.actions())
    target = tabs[4].focusProxy() or tabs[4]
    QTest.mouseClick(target, Qt.RightButton, Qt.NoModifier, QPoint(40, 40))
    pump(800)
    QMenu.popup = orig_popup
    check("right-click menu has a single Inspect", menu_actions.count("Inspect") == 1, str(menu_actions))
    _ = QWebEnginePage

    n = win.tabs.count()
    win.view_source()
    pump(800)
    check("Ctrl+U opens the page source in a new tab", win.tabs.count() == n + 1 and
          win.current_tab().url().scheme() == "view-source", win.current_tab().url().toString())

    # the wheel scrolls the tab strip; it doesn't switch tabs or open collapsed groups
    from PySide6.QtGui import QWheelEvent
    for _ in range(25):
        win.open_tab(page(8), background=True)
    pump(300)
    g2 = strip.new_group([win.tab_list()[-2], win.tab_list()[-1]], name="Later")
    strip.toggle_collapse(g2)
    pump(200)
    cur = win.current_tab()
    first = bar.tabAt(QPoint(bar.width() // 2, bar.height() // 2))
    for delta in (-120, -120, -120, 120):
        app.sendEvent(bar, QWheelEvent(QPointF(bar.width() / 2, bar.height() / 2), QPointF(bar.mapToGlobal(QPoint(5, 5))),
                                       QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        pump(60)
    check("the wheel doesn't switch tabs", win.current_tab() is cur)
    check("the wheel scrolls the strip", bar.tabAt(QPoint(bar.width() // 2, bar.height() // 2)) != first)
    check("the wheel doesn't open collapsed groups", strip.groups[g2]["collapsed"])

    # sleeping from the menus (web pages: other kinds of tab don't sleep)
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for n, t in enumerate(win.tab_list()[-4:]):
        t.load(QUrl(f"http://127.0.0.1:{srv.server_port}/sleepy-{n}"))
    for _ in range(80):
        if all(not t.loading and "sleepy" in t.url().toString() for t in win.tab_list()[-4:]):
            break
        pump(50)
    from atlasbrowser.sleeper import is_asleep
    sleepy = win.tab_list()[-3]
    if sleepy is win.current_tab():
        win.select_tab(win.tab_list()[-1])
    # put it to sleep the way you would, from its menu ("Put tab to sleep" works even if it's still loading)
    put = [a for a in strip.tab_menu(sleepy).actions() if a.text().startswith("Put tab to sleep")]
    check("an awake tab's menu offers Put tab to sleep", put and put[0].isEnabled(),
          str((sleepy.loading, sleepy is win.current_tab(), sleepy.url().toString())))
    if put:
        put[0].trigger()
    check("which puts it to sleep", is_asleep(sleepy))
    labels = [a.text() for a in strip.tab_menu(sleepy).actions()]
    check("a sleeping tab's menu offers Wake tab", "Wake tab" in labels, str(labels))
    for a in [a for a in strip.tab_menu(sleepy).actions() if a.text() == "Wake tab"][:1]:
        a.trigger()
    check("Wake tab wakes it", not is_asleep(sleepy))
    gl = [a.text() for a in strip._group_menu(g2).actions()]
    check("the group menu offers Put group to sleep", any("Put group to sleep" in t for t in gl), str(gl))
    strip.sleep_group(g2)
    check("Put group to sleep puts all its tabs to sleep", all(is_asleep(t) for t in strip.members(g2)))
    gl = [a.text() for a in strip._group_menu(g2).actions()]
    check("then it offers Wake group", "Wake group" in gl and not any("Put group" in t for t in gl), str(gl))
    strip.wake_group(g2)
    check("Wake group wakes them", not any(is_asleep(t) for t in strip.members(g2)))
    here = [t for t in win.tab_list() if "sleepy" in t.url().toString() and not strip.members(g2).count(t)]
    win.select_tab(here[0])
    pump(200)
    g3 = strip.new_group(here, name="Here")
    strip.sleep_group(g3)
    check("sleeping the group you're in moves you to another tab first",
          win.current_tab() not in strip.members(g3) and all(is_asleep(t) for t in strip.members(g3)))

    # F11: custom minimize / exit full screen / close buttons, only in full screen
    check("no window buttons in a normal window", not win.window_buttons.isVisible())
    QTest.keyClick(win, Qt.Key_F11)
    pump(500)
    wb = win.window_buttons
    right = wb.mapTo(win, wb.rect().topRight())
    check("F11 shows minimize, exit and close at the top right", win.isFullScreen() and wb.isVisible()
          and right.x() >= win.width() - 12 and right.y() <= 2, f"{right} {win.width()}")
    last = win.tabs.tabBar().mapTo(win, win.tabs.tabBar().tabRect(win.tabs.count() - 1).topRight()).x()
    check("tabs don't run under them", last < wb.mapTo(win, wb.rect().topLeft()).x(), str(last))
    from PySide6.QtWidgets import QToolButton as _TB
    wb.findChild(_TB, "restore").click()
    pump(500)
    check("the middle button leaves full screen and hides them", not win.isFullScreen() and not wb.isVisible())

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
