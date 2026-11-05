"""Homepage: shortcuts instead of bookmarks, editing them from the page, background colour/photo, show/hide options,
most visited mode and the Settings → Homepage tab.

Run:  python tests/homepage_test.py          (add --visible to show the window)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_home_test_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
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
    from atlasbrowser import homepage
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
    st = win.store
    tab = win.current_tab()

    wait_until(lambda: not tab.loading)

    def reload_home():
        done = []
        tab.loadFinished.connect(done.append)
        tab.load(win.start_page_url())
        wait_until(lambda: done)
        tab.loadFinished.disconnect(done.append)
        pump(200)

    st.add_bookmark("https://bookmarked.example/", "Bookmarked site")
    reload_home()
    body = js(tab, "document.body.innerText")
    check("bookmarks are no longer on the homepage", "Bookmarked site" not in body, body)
    check("an empty homepage offers Add shortcut", "Add shortcut" in body, body)

    homepage.add_shortcut(st, "Example", "https://example.com/")
    homepage.add_shortcut(st, "", "https://news.example.org/")
    reload_home()
    body = js(tab, "document.body.innerText")
    check("shortcuts show as tiles", "Example" in body and "news.example.org" in body, body)

    calls = []
    real = homepage.handle_action
    homepage.handle_action = lambda w, a, i: calls.append((a, i))
    js(tab, "document.querySelectorAll('.more')[1].click()")
    wait_until(lambda: calls, 3)
    check("the ⋮ on a tile asks to edit that shortcut", calls == [("edit", 1)], str(calls))
    check("and the page stays put", win.is_start(tab.url()) and "pelagic" not in tab.url().query())
    calls.clear()
    js(tab, "document.querySelector('.customize').click()")
    wait_until(lambda: calls, 3)
    check("Customize opens the Homepage settings", calls == [("customize", -1)], str(calls))
    homepage.handle_action = real

    homepage.set_shortcut(st, 0, "Renamed", "https://example.com/x")
    homepage.remove_shortcut(st, 1)
    check("shortcuts edit and remove", homepage.shortcuts(st) == [{"title": "Renamed", "url": "https://example.com/x"}],
          str(homepage.shortcuts(st)))
    check("parse_action ignores other pages", homepage.parse_action(
        __import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl("https://evil.example/start.html?pelagic=add")) is None)

    # background photo, colour, parts
    img = QImage(64, 40, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    src = Path(tempfile.mkdtemp()) / "beach.jpg"
    img.save(str(src))
    w = homepage.HomepageSettings(st)
    w.bg.setCurrentIndex(w.bg.findData("image"))
    w.image = str(src)
    w.dim[1].setValue(40)
    w.blur[1].setValue(6)
    w.show["home_show_clock"].setChecked(True)
    w.show["home_show_tagline"].setChecked(False)
    w.save()
    saved = st.get("home_bg_image")
    check("the photo is copied into the profile", saved and Path(saved).exists() and Path(saved).parent.name == "homepage"
          and saved != str(src), saved)
    src.unlink()
    reload_home()
    bg = js(tab, "getComputedStyle(document.querySelector('.bg')).backgroundImage")
    check("the photo is the background", "background" in str(bg) and "homepage" in str(bg), str(bg))
    check("dim and blur apply", js(tab, "getComputedStyle(document.querySelector('.bg')).filter") == "blur(6px)"
          and "0.4" in js(tab, "getComputedStyle(document.querySelector('.dim')).backgroundColor"))
    check("clock shows", bool(js(tab, "document.getElementById('clock').textContent")))
    check("tagline hidden", "let AI do the browsing" not in js(tab, "document.body.innerText"))
    w = homepage.HomepageSettings(st)
    w.bg.setCurrentIndex(w.bg.findData("color"))
    w.color = QColor("#f4efe6")
    for k in ("home_show_logo", "home_show_search"):
        w.show[k].setChecked(False)
    w.save()
    reload_home()
    check("solid color background", js(tab, "getComputedStyle(document.querySelector('.bg')).backgroundColor")
          == "rgb(244, 239, 230)")
    check("light color switches to dark text", js(tab, "getComputedStyle(document.body).color") == "rgb(16, 32, 43)")
    check("logo and search box can be hidden", js(tab, "!document.querySelector('form') && !document.querySelector('h1')"))

    # most visited
    for _ in range(3):
        st.add_history("https://often.example/page", "Often - site")
    st.add_history("https://rare.example/", "Rare")
    check("most visited ranks by visits, one per site", [s["url"] for s in homepage.most_visited(st)][:2] ==
          ["https://often.example/", "https://rare.example/"], str(homepage.most_visited(st)))
    w = homepage.HomepageSettings(st)
    w.mode.setCurrentIndex(w.mode.findData("most_visited"))
    w.save()
    reload_home()
    body = js(tab, "document.body.innerText")
    check("most visited mode shows your top sites", "Often" in body and "Add shortcut" not in body
          and not js(tab, "document.querySelector('.more')"), body)

    # settings tab
    from atlasbrowser.dialogs import SettingsDialog
    d = SettingsDialog(st, win, win=win, start="homepage")
    tabs = d.findChild(__import__("PySide6.QtWidgets", fromlist=["QTabWidget"]).QTabWidget)
    check("Settings has its own Homepage tab", tabs.tabText(tabs.currentIndex()) == "Homepage")
    d.close()

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
