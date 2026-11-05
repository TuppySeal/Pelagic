"""Dark mode for websites, done by the browser engine (darkmode.py) instead of a page-wide CSS filter.

Run:  python tests/darkmode_test.py          (add --visible to show the window)
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_darkmode_test_")
os.environ.pop("PELAGIC_DARKMODE_SCRIPT", None)

from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


LIGHT = "<title>{t}</title><body style='background:#fff;color:#000;margin:0'><h1>Light page</h1>" \
        "<div style='height:3000px'></div></body>"
PAGES = {
    "/light": LIGHT.format(t="Light"),
    "/other": LIGHT.format(t="Other"),
    "/dark": "<title>Dark</title><body style='background:#111;color:#eee;margin:0'><h1>Dark page</h1></body>",
    # a site turned off with the old userscript's menu: its switch is in the site's own storage
    "/old": LIGHT.format(t="Old") + "<script>localStorage.setItem('__wf_gm_EXTID_darkmode-off','true')</script>",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], "<title>x</title>ok").replace(
            "EXTID", self.server.ext_id).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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


def shade(tab):
    """Brightness (0-255) of the page's background as drawn on screen."""
    img = tab.grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() - 40)
    return (c.red() + c.green() + c.blue()) // 3


def reloads(tab):
    """Counts the page's loads from now on (on some graphics cards a page only changes after one)."""
    n = [0]
    tab.loadStarted.connect(lambda: n.__setitem__(0, n[0] + 1))
    return n


def settle(tab):
    pump(300)
    wait_until(lambda: not tab.loading)
    pump(600)


def open_page(win, tab, url, title):
    tab.load(win.to_qurl(url))
    wait_until(lambda: not tab.loading and tab.title() == title)
    pump(600)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.ext_id = ""
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{srv.server_port}"
    other = f"http://localhost:{srv.server_port}"
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import darkmode
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    if not darkmode.NATIVE:
        print("SKIP: this Qt has no built-in dark mode (Qt 6.7+); Pelagic uses the userscript instead")
        return 0
    apply_theme(app)
    hub = ProfileHub(app, Store(), Browser)
    win = hub.open_profile(DEFAULT_ID, [site + "/light"])
    win.resize(1200, 800)
    win.show()
    tab = win.current_tab()
    wait_until(lambda: not tab.loading and tab.title() == "Light")
    pump(600)
    exts, st = win.ctx.extensions, win.store
    ext = darkmode.builtin(exts)
    srv.ext_id = ext["id"]

    check("the built-in dark mode extension is installed and on", ext is not None and darkmode.enabled(exts))
    names = [s.name() for s in win.profile.scripts().toList()]
    check("its slow userscript isn't injected any more", not any(ext["id"] in n or "Dark mode" in n for n in names),
          str(names))
    check("light pages are drawn dark", shade(tab) < 80, str(shade(tab)))
    check("without a filter on the page (the cause of the lag)",
          js(tab, "getComputedStyle(document.documentElement).filter + ''") == "none"
          and js(tab, "'pelagicDark' in document.documentElement.dataset") is False,
          str((js(tab, "getComputedStyle(document.documentElement).filter"), js(tab, "JSON.stringify(document.documentElement.dataset)"))))
    open_page(win, tab, site + "/dark", "Dark")
    check("already-dark pages stay dark", shade(tab) < 80, str(shade(tab)))

    # the per-site switch in the extensions (puzzle) menu
    open_page(win, tab, site + "/light", "Light")
    win.ext_btn._fill()
    acts = {a.text(): a for a in win.ext_btn.menu_.actions()}
    item = acts.get("Dark mode on 127.0.0.1")
    check("the puzzle menu has a per-site switch", item is not None and item.isChecked(), str(list(acts)))
    n = reloads(tab)
    item.setChecked(False)
    settle(tab)
    check("switching it off shows the site as it is", shade(tab) > 200, str(shade(tab)))
    check("and the page is redrawn from scratch, so it changes on every graphics card", n[0] == 1, str(n))
    check("and it's remembered", darkmode.site_off(st, "127.0.0.1") and st.get(darkmode.OFF_SITES) == ["127.0.0.1"])
    open_page(win, tab, other + "/other", "Other")
    check("other sites stay dark", shade(tab) < 80, str(shade(tab)))
    open_page(win, tab, site + "/light", "Light")
    check("it stays off for that site next time", shade(tab) > 200, str(shade(tab)))
    win.ext_btn._fill()
    acts = {a.text(): a for a in win.ext_btn.menu_.actions()}
    check("the menu then shows it unticked", not acts["Dark mode on 127.0.0.1"].isChecked())
    acts["Dark mode on 127.0.0.1"].setChecked(True)
    settle(tab)
    check("ticking it again darkens the page at once", shade(tab) < 80 and not darkmode.site_off(st, "127.0.0.1"),
          str(shade(tab)))
    check("off for a site covers its subdomains", (darkmode.set_site_off(st, "www.example.com", True),
          darkmode.site_off(st, "mail.example.com"), darkmode.set_site_off(st, "example.com", False))[1])

    # turning the whole extension off and on
    t2 = win.open_tab(other + "/other", background=True)
    wait_until(lambda: not t2.loading and t2.title() == "Other")
    pump(300)
    n, n2 = reloads(tab), reloads(t2)
    win.ext_btn._toggle_ext(ext["id"], False)   # the puzzle menu's tick box
    settle(tab)
    settle(t2)
    check("turning the extension off shows pages as they are", shade(tab) > 200, str(shade(tab)))
    check("every open site tab is redrawn once (not twice)", n[0] == 1 and n2[0] == 1, f"{n} {n2}")
    n[0] = 0
    exts.set_enabled(ext["id"], True)           # Manage extensions' tick box
    settle(tab)
    check("and on again darkens them", shade(tab) < 80 and n[0] == 1, f"{shade(tab)} {n}")
    win.close_tab_obj(t2)
    exts.set_enabled(ext["id"], True)
    check("setting it to what it already is reloads nothing", n[0] == 1)

    # sites switched off with the old script stay off
    open_page(win, tab, other + "/old", "Old")
    tab.reload()
    wait_until(lambda: darkmode.site_off(st, "localhost"), 5)
    pump(600)
    check("a site turned off with the old script's menu stays off", darkmode.site_off(st, "localhost")
          and shade(tab) > 200, f"{st.get(darkmode.OFF_SITES)} {shade(tab)}")
    darkmode.set_site_off(st, "localhost", False)

    # Pelagic's own pages and private windows
    tab.load(QUrl("about:blank"))
    wait_until(lambda: not tab.loading)
    check("Pelagic's own pages aren't touched", not darkmode.page_is_dark(tab.page()))
    priv = hub.browsers[DEFAULT_ID].new_window(private=True, urls=[site + "/light"]) \
        if hasattr(hub, "browsers") else win.ctx.new_window(private=True, urls=[site + "/light"])
    ptab = priv.current_tab()
    wait_until(lambda: not ptab.loading and ptab.title() == "Light")
    pump(600)
    check("private windows stay without extensions, dark mode included", shade(ptab) > 200, str(shade(ptab)))
    priv.close()

    win.close()
    hub.stop_all()
    srv.shutdown()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
