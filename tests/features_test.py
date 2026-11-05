"""Bookmarks (edit, folders, site icons), tab group colours, sleeping tabs, the CAPTCHA hand-off and the built-in
dark mode extension.

Run:  python tests/features_test.py          (add --visible to show the window)
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_features_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring
os.environ["PELAGIC_DARKMODE_SCRIPT"] = "1"   # covers the old dark mode script (Qt without ForceDarkMode); darkmode_test.py covers the new one

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QTabBar  # noqa: E402

PAGES = {
    "/light": "<title>Light</title><body style='background:#fff;color:#000'><h1>Light page</h1></body>",
    "/dark": "<title>Dark</title><body style='background:#111;color:#eee'><h1>Dark page</h1></body>",
    # like Discord: <html>/<body> transparent, the dark theme painted by an inner app element, styles arriving late
    "/app": "<title>App</title><style>html,body{margin:0;height:100%}</style><div id=mount style='height:100%'>"
            "Loading</div><script>setTimeout(function(){document.getElementById('mount').style.background="
            "'#313338';document.getElementById('mount').style.color='#dbdee1';"
            "document.documentElement.className='theme-dark'},1200)</script>",
    # like Google Slides: a light editor whose slides are big SVG drawings (dark navy here), plus a small SVG icon
    "/slides": "<title>Slides</title><body style='background:#fff'><svg id=icon width=24 height=24>"
               "<rect width=24 height=24 fill='#555'/></svg><div id=wrap><svg id=slide width=640 height=360>"
               "<rect width=640 height=360 fill='#1b2232'/><text x=40 y=80 fill='#fff'>Title</text></svg></div>"
               "<script>setTimeout(function(){document.getElementById('wrap').insertAdjacentHTML('beforeend',"
               "\"<svg id=thumb width=200 height=112><rect width=200 height=112 fill='#1b2232'/></svg>\")},300)"
               "</script></body>",
    "/scheme": "<title>Scheme</title><meta name=color-scheme content=dark><style>:root{color-scheme:dark}"
               "body{color:#eee}</style><p>dark by color scheme</p>",
    "/captcha": "<title>Verify</title><h1>Check</h1><iframe title='reCAPTCHA' width=304 height=78 "
                "src='about:blank#recaptcha/api2/anchor?k=x'></iframe>",
    "/plain": "<title>Plain</title><p>Nothing here</p>",
    # a portal built from frames (like Infinite Campus): same-site frames plus another site's frame
    "/portal": "<title>Portal</title><body style='background:#fff'><iframe id=same src='/light' width=400 "
               "height=200></iframe><iframe id=other src='http://localhost:PORT/light' width=400 height=200>"
               "</iframe></body>",
    "/frames": "<title>Frames</title><frameset cols='50%,50%'><frame name=a src='/light'><frame name=b "
               "src='/light'></frameset>",
    "/video": "<title>Video</title><body style='background:#fff'><div class='html5-video-player' id=player "
              "style='width:320px;height:180px;background:#000'><video id=v width=320 height=180></video></div>"
              "<button id=fs onclick=\"document.getElementById('player').requestFullscreen()\">FS</button></body>",
    "/csp": "<title>Strict</title><body style='background:#fff'><h1>Strict CSP page</h1></body>",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        body = PAGES.get(path, "<title>Other</title>ok").replace("PORT", str(self.server.server_port)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if path == "/csp":
            self.send_header("Content-Security-Policy", "style-src 'none'; script-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


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
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{srv.server_port}"
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [site + "/plain"])
    win.resize(1300, 800)
    win.show()
    tab = win.current_tab()
    wait_until(lambda: not tab.loading and tab.title() == "Plain")
    st = win.store

    # ---------------------------------------------------------------- bookmarks
    from atlasbrowser import bookmarks_ui
    pix = QPixmap(16, 16)
    pix.fill(QColor("#ff0000"))
    tab.icon = lambda: QIcon(pix)   # the test server has no favicon
    win.toggle_bookmark()
    url = tab.url().toString()
    check("bookmark added", st.is_bookmarked(url))
    check("site icon saved with the bookmark", st.favicon_path(url).exists())
    bar_buttons = lambda: [w for w in win.bm_bar.findChildren(QPushButton) if not w.isHidden()]   # noqa: E731
    pump(100)
    btn = next((b for b in bar_buttons() if b.text().startswith("Plain")), None)
    check("bar button shows the site icon", btn is not None and not btn.icon().isNull()
          and btn.icon().pixmap(16, 16).toImage().pixelColor(8, 8).red() > 200)
    ed = bookmarks_ui.BookmarkEditor(st, url, win)
    ed.name.setText("My plain page")
    ed.addr.setText(site + "/plain?x=1")
    ed._save()
    new_url = site + "/plain?x=1"
    check("editor renames and changes the address", st.is_bookmarked(new_url) and not st.is_bookmarked(url)
          and st.bookmarks[0]["title"] == "My plain page", str(st.bookmarks))
    st.add_folder("Work")
    st.add_bookmark(site + "/light", "Light")
    st.edit_bookmark(new_url, folder="Work")
    win._rebuild_bookmarks()
    pump(100)
    texts = [b.text() for b in bar_buttons()]
    check("folder shows on the bar first", texts and texts[0] == "Work", str(texts))
    check("bookmark moved into the folder leaves the bar", "My plain page" not in texts and "Light" in texts,
          str(texts))
    folder_btn = bar_buttons()[0]
    m = folder_btn.menu()
    m.aboutToShow.emit()
    check("folder menu lists its bookmarks", any(a.text() == "My plain page" for a in m.actions()),
          str([a.text() for a in m.actions()]))
    st.rename_folder("Work", "Jobs")
    check("renaming a folder keeps its bookmarks", st.bookmarks_in("Jobs") and not st.bookmarks_in("Work"))
    st.delete_folder("Jobs")
    check("deleting a folder keeps its bookmarks on the bar", "Jobs" not in st.all_folders()
          and st.is_bookmarked(new_url) and not st.bookmarks_in("Jobs"))
    st2 = Store(st.root)
    check("bookmarks and folders survive a restart", [b["title"] for b in st2.bookmarks] ==
          [b["title"] for b in st.bookmarks] and st2.all_folders() == st.all_folders())

    # a full bar never makes the window wider than the screen: it scrolls sideways, like the tabs
    st.set("bookmarks_bar", True)
    added = [f"{site}/plain?n={n}" for n in range(30)]
    for n, u in enumerate(added):
        st.add_bookmark(u, f"Learner Home - Edmentum site {n}")
    win._rebuild_bookmarks()
    was_max = win.isMaximized()
    win.showNormal()
    win.resize(1000, 700)
    pump(200)
    check("lots of bookmarks don't stop the window being made narrow", win.width() <= 1000
          and win.minimumSizeHint().width() < 1000, str((win.width(), win.minimumSizeHint().width())))
    strip = win.bm_bar
    sb = strip.area.horizontalScrollBar()
    labels = [b.text() for b in bar_buttons()]
    check("every bookmark is on the bar (no » menu)", any("site 29" in b.toolTip() for b in bar_buttons())
          and "»" not in labels, str(len(labels)))
    check("there's more than fits, so the › arrow shows", sb.maximum() > 0 and strip.right.isVisible()
          and not strip.left.isVisible(), str((sb.maximum(), strip.right.isVisible(), strip.left.isVisible())))
    strip.right.click()
    pump(50)
    check("› scrolls the bookmarks along", sb.value() > 0 and strip.left.isVisible(), str(sb.value()))
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    before = sb.value()
    QApplication.sendEvent(strip.area.viewport(), QWheelEvent(
        QPointF(20, 10), QPointF(strip.mapToGlobal(QPoint(20, 10))), QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    check("the mouse wheel scrolls them too", sb.value() > before, str((before, sb.value())))
    sb.setValue(sb.maximum())
    pump(50)
    check("at the end the › arrow goes away", not strip.right.isVisible() and strip.left.isVisible())
    for u in added:
        st.remove_bookmark(u) if hasattr(st, "remove_bookmark") else st.toggle_bookmark(u, "")
    win._rebuild_bookmarks()
    # nothing on the page side (however wide) can squeeze the AI panel or push the window past the screen
    from PySide6.QtWidgets import QWidget
    wide = QWidget()
    wide.setMinimumWidth(1600)
    wide.setFixedHeight(2)
    win.centralWidget().layout().insertWidget(0, wide)
    pump(100)
    check("a very wide toolbar or bar can't make the window wider than the screen",
          win.minimumSizeHint().width() < 900, str(win.minimumSizeHint()))
    wide.setParent(None)
    wide.deleteLater()
    # opening or closing the AI panel puts a window that hangs off the screen back inside it
    avail = win.screen().availableGeometry()
    room = lambda: max(avail.width(), win.minimumSizeHint().width()) + 40   # noqa: E731  (the test screen is small)
    win.showNormal()
    win.resize(avail.width() + 600, avail.height() + 400)
    win.toggle_panel(True)
    pump(400)
    check("opening the AI panel fits the window back on the screen", win.frameGeometry().width() <= room()
          and win.frameGeometry().height() <= avail.height() + 1, str((win.frameGeometry(), avail)))
    win.resize(avail.width() + 600, avail.height() + 400)
    win.toggle_panel(False)
    pump(400)
    check("and so does closing it", win.frameGeometry().width() <= room(), str((win.frameGeometry(), avail)))
    win.toggle_panel(True)
    win.resize(1000, 700)
    if was_max:
        win.showMaximized()
    menu = win.bm.bookmark_menu(new_url)
    labels = [a.text() for a in menu.actions()]
    check("bookmark right-click has Edit, Move to and Delete", all(any(w in l for l in labels)
                                                                   for w in ("Edit", "Move to", "Delete")), str(labels))
    d = bookmarks_ui.BookmarksDialog(st, win)
    check("manager lists bookmarks with icons", d.tree.topLevelItemCount() >= 2 and
          not d.tree.topLevelItem(0).icon(0).isNull())
    st.add_folder("Reading")
    d.reload()
    item = next(d.tree.topLevelItem(i) for i in range(d.tree.topLevelItemCount())
                if d.tree.topLevelItem(i).text(0) == "Light")
    item.setText(0, "Light renamed")
    check("renaming in the manager saves", any(b["title"] == "Light renamed" for b in st.bookmarks))
    d.close()

    # ---------------------------------------------------------------- tab group colours
    strip = win.strip
    t2 = win.open_tab(site + "/dark", background=True)
    gid = strip.new_group([tab, t2], name="Docs")
    pump(100)
    from atlasbrowser.tabstrip import GROUP_COLORS, GroupEditor
    gm = strip._group_menu(gid)
    color_menu = next(a.menu() for a in gm.actions() if a.menu() and a.text() == "Color")
    names = [a.text() for a in color_menu.actions()]
    check("Color menu has swatches and a custom color", all(not a.icon().isNull() for a in color_menu.actions()
                                                           if a.text() in GROUP_COLORS) and "Custom color…" in names,
          str(names))
    ge = GroupEditor(strip, gid)
    ge.pick(GROUP_COLORS["Purple"])
    check("group editor recolors the group", strip.groups[gid]["color"] == GROUP_COLORS["Purple"])
    ge.name.setText("Reading")
    ge.name.textEdited.emit("Reading")
    check("group editor renames the group", strip.groups[gid]["name"] == "Reading")
    ge.close()
    strip.set_group(gid, color="#123456")
    pump(50)
    chip = win.tabs.tabBar().tabButton(win.tabs.indexOf(strip.members(gid)[0]), QTabBar.LeftSide)
    check("custom dark color gets white chip text", chip is not None and "#ffffff" in chip.styleSheet())
    strip.ungroup(gid)

    # ---------------------------------------------------------------- sleeping tabs
    from atlasbrowser.sleeper import is_asleep
    wait_until(lambda: not t2.loading)
    t2._last_active -= 3600
    win.sleeper.check()
    check("an unused background tab goes to sleep", is_asleep(t2))
    check("it keeps its title", win.tabs.tabBar().tabText(win.tabs.indexOf(t2)) == "Dark",
          win.tabs.tabBar().tabText(win.tabs.indexOf(t2)))
    tab._last_active -= 3600
    win.sleeper.check()
    check("the tab you're on stays awake", not is_asleep(tab))
    win.select_tab(t2)
    pump(300)
    check("clicking a sleeping tab wakes it", not is_asleep(t2))
    check("and reloads the page", wait_until(lambda: not t2.loading and t2.title() == "Dark"))
    win.select_tab(tab)
    strip.set_pinned(t2, True)
    t2._last_active -= 3600
    win.sleeper.check()
    check("pinned tabs stay awake", not is_asleep(t2))
    strip.set_pinned(t2, False)
    gid2 = strip.new_group([t2], name="School")
    strip.toggle_collapse(gid2)
    pix2 = QPixmap(16, 16)
    pix2.fill(QColor("#888888"))
    t2._icon_full = QIcon(pix2)
    win.sleeper.sleep(t2)
    pump(50)
    i2 = win.tabs.indexOf(t2)
    check("a sleeping tab in a collapsed group shows only the group label (no icon sliver)",
          is_asleep(t2) and win.tabs.tabBar().tabIcon(i2).isNull() and win.tabs.tabBar().tabRect(i2).width() < 120,
          str(win.tabs.tabBar().tabRect(i2)))
    strip.ungroup(gid2)
    win.select_tab(t2)
    pump(300)
    win.select_tab(tab)
    strip.set_pinned(t2, False)
    st.set("tab_sleep", False)
    t2._last_active -= 3600
    win.sleeper.check()
    check("the setting turns it off", not is_asleep(t2))
    st.set("tab_sleep", True)

    # ---------------------------------------------------------------- dark mode extension
    from atlasbrowser.app import DARKMODE_SOURCE
    exts = win.ctx.extensions
    dm = [e for e in exts.items if e.get("source") == DARKMODE_SOURCE]
    check("dark mode extension is installed", len(dm) == 1)
    tab.load(win.to_qurl(site + "/light"))
    wait_until(lambda: not tab.loading and tab.title() == "Light")
    pump(500)
    has_style = "document.documentElement.dataset.pelagicDark === '1'"
    check("light pages are made dark", js(tab, has_style) is True)
    tab.load(win.to_qurl(site + "/dark"))
    wait_until(lambda: not tab.loading and tab.title() == "Dark")
    pump(500)
    check("already-dark pages are left alone", js(tab, has_style) is False)
    tab.load(win.to_qurl(site + "/app"))
    wait_until(lambda: not tab.loading and tab.title() == "App")
    wait_until(lambda: js(tab, "document.documentElement.className") == "theme-dark", 5)
    pump(700)
    check("a web app that paints its dark theme late (like Discord) is left alone", js(tab, has_style) is False)
    js(tab, "document.getElementById('mount').style.background='#ffffff';"
            "document.getElementById('mount').style.color='#111';document.documentElement.className='theme-light'")
    pump(700)
    check("and is darkened when it switches to its light theme", js(tab, has_style) is True)
    tab.load(win.to_qurl(site + "/slides"))
    wait_until(lambda: not tab.loading and tab.title() == "Slides")
    pump(1200)
    filt = "getComputedStyle(document.getElementById('%s')).filter"
    check("an editor like Google Slides is darkened", js(tab, has_style) is True)
    check("but its slides keep their real colours", "invert" in str(js(tab, filt % "slide")), str(js(tab, filt % "slide")))
    check("including slides added later (thumbnails)", "invert" in str(js(tab, filt % "thumb")),
          str(js(tab, filt % "thumb")))
    check("small icons are still darkened with the page", js(tab, filt % "icon") == "none", str(js(tab, filt % "icon")))
    tab.load(win.to_qurl(site + "/scheme"))
    wait_until(lambda: not tab.loading and tab.title() == "Scheme")
    pump(500)
    check("pages with a dark color scheme are left alone", js(tab, has_style) is False)
    frame_on = ("(function(f){try{return f.contentDocument.documentElement.dataset.pelagicDark==='1'}"
                "catch(e){return 'cross'}})(document.getElementById('%s'))")
    tab.load(win.to_qurl(site + "/portal"))
    wait_until(lambda: not tab.loading and tab.title() == "Portal")
    pump(800)
    check("a portal page is darkened", js(tab, has_style) is True)
    check("its same-site frame is darkened too", js(tab, frame_on % "same") is True, str(js(tab, frame_on % "same")))
    check("another site's frame is left as it is", js(tab, frame_on % "other") == "cross")
    tab.load(win.to_qurl(site + "/frames"))
    wait_until(lambda: not tab.loading and tab.title() == "Frames")
    pump(800)
    check("framesets are darkened inside each frame",
          js(tab, "Array.from(document.querySelectorAll('frame')).every(function(f){"
                  "return f.contentDocument.documentElement.dataset.pelagicDark==='1'})") is True)
    tab.load(win.to_qurl(site + "/csp"))
    wait_until(lambda: not tab.loading and tab.title() == "Strict")
    pump(800)
    check("works on sites that block injected styles (CSP)",
          "invert" in str(js(tab, "getComputedStyle(document.documentElement).filter")),
          str(js(tab, "getComputedStyle(document.documentElement).filter")))
    from atlasbrowser.extensions import parse_meta
    tab.load(win.to_qurl(site + "/video"))
    wait_until(lambda: not tab.loading and tab.title() == "Video")
    pump(800)
    check("video players keep a black background in dark mode", "invert" in str(js(
        tab, "getComputedStyle(document.getElementById('player')).filter")) and js(
        tab, "getComputedStyle(document.getElementById('v')).filter") == "none")
    panel_before = win.dock.isVisible()
    stored_panel = st.get("panel")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint, Qt as _Qt
    import json as _json
    pos = _json.loads(js(tab, "(function(r){return JSON.stringify([r.left+r.width/2, r.top+r.height/2])})("
                              "document.getElementById('fs').getBoundingClientRect())"))
    QTest.mouseClick(tab.focusProxy() or tab, _Qt.LeftButton, _Qt.NoModifier, QPoint(int(pos[0]), int(pos[1])))
    wait_until(lambda: js(tab, "!!document.fullscreenElement"), 5)
    pump(500)
    check("a video going full screen fills the whole window", win.isFullScreen() and not win.toolbar.isVisible()
          and not win.tabs.row.isVisible() and not win.bm_bar.isVisible() and not win.dock.isVisible(),
          f"fs={win.isFullScreen()} tb={win.toolbar.isVisible()} row={win.tabs.row.isVisible()}")
    check("dark mode steps aside while a video is full screen", js(tab, has_style) is False)
    js(tab, "document.exitFullscreen()")
    wait_until(lambda: not win.isFullScreen(), 5)
    pump(800)
    check("leaving full screen brings the browser back", win.toolbar.isVisible() and win.tabs.row.isVisible()
          and win.dock.isVisible() == panel_before and st.get("panel") == stored_panel)
    check("and dark mode comes back", js(tab, has_style) is True)
    check("built-in dark mode is updated to the new version", exts.get(dm[0]["id"])["version"] == parse_meta(
        (Path(__file__).resolve().parent.parent / "atlasbrowser/assets/darkmode.user.js").read_text())["version"])
    tab.load(win.to_qurl(site + "/light"))
    wait_until(lambda: not tab.loading and tab.title() == "Light")
    pump(500)
    from atlasbrowser.extensions import menu_commands_js, run_menu_command_js
    cmds = js(tab, menu_commands_js())
    import json as _j
    mine = lambda: [c for c in _j.loads(js(tab, menu_commands_js()) or "[]") if c[0] == dm[0]["id"]]
    check("menu has the per-site switch", [c[2] for c in mine()] == ["Turn off for this site"], str(cmds))
    tab.page().runJavaScript(run_menu_command_js(dm[0]["id"], mine()[0][1]))
    pump(300)
    check("switching it off removes it at once", js(tab, has_style) is False)
    check("and the menu then offers to turn it back on", [c[2] for c in mine()] == ["Turn on for this site"],
          str(mine()))
    tab.reload()
    wait_until(lambda: not tab.loading)
    pump(500)
    check("and it stays off for that site", js(tab, has_style) is False)
    check("still offering to turn it back on after a reload", [c[2] for c in mine()] == ["Turn on for this site"])
    tab.page().runJavaScript(run_menu_command_js(dm[0]["id"], mine()[0][1]))
    pump(300)
    check("turning it back on works", js(tab, has_style) is True and
          [c[2] for c in mine()] == ["Turn off for this site"])
    Browser_twice = [e for e in exts.items if e.get("source") == DARKMODE_SOURCE]
    check("not added twice", len(Browser_twice) == 1)

    # ---------------------------------------------------------------- CAPTCHA hand-off
    from atlasbrowser import providers
    from atlasbrowser.agent import Agent
    tab.load(win.to_qurl(site + "/captcha"))
    wait_until(lambda: not tab.loading and tab.title() == "Verify")
    pump(300)
    ag = Agent(win, providers.find_provider(st, "openai"), "test-key", st)
    asked, thought = [], []
    ag.question.connect(asked.append)
    ag._think = lambda *a, **k: thought.append(1)
    ag._observed = lambda token, raw: thought.append(1)
    ag.start("log in")
    wait_until(lambda: asked or thought, 5)
    check("agent stops and asks you to solve the CAPTCHA", asked and "CAPTCHA" in asked[0] and not thought,
          f"{asked} {thought}")
    check("agent waits for you", ag.waiting_for_user and ag.running)
    ag.resume("Done, I solved it.")
    wait_until(lambda: thought, 5)
    check("after you reply it carries on (and doesn't ask again on the same page)", thought and len(asked) == 1)
    ag.stop()
    tab.load(win.to_qurl(site + "/plain"))
    wait_until(lambda: not tab.loading and tab.title() == "Plain")
    asked.clear()
    thought.clear()
    ag.start("next")
    wait_until(lambda: asked or thought, 5)
    check("no CAPTCHA, no pause", thought and not asked)
    ag.stop()

    win.close()
    hub.stop_all()
    srv.shutdown()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
