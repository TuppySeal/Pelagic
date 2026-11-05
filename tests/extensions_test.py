"""Extensions: ad blocker (network + element hiding, per-site pause), userscripts and site styles per profile.

Run:  python tests/extensions_test.py          (add --visible to show the window)
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_ext_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


PAGE = """<title>Ads</title><div class="ad-box" id="adbox">ad</div><div id="content">hello</div>
<script src="/static/app.js"></script><script src="/adserver/adscript.js"></script>"""
USERSCRIPT = """// ==UserScript==
// @name        Test Marker
// @version     1.0
// @description marks pages
// @include     http://127.0.0.1:*/*
// @grant       GM_getValue
// ==/UserScript==
GM_setValue('n', (GM_getValue('n', 0) + 1));
document.documentElement.setAttribute('data-us', 'ran');
GM_registerMenuCommand('Say hi', function () { document.documentElement.setAttribute('data-cmd', 'hi'); });
"""


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ctype = "text/html; charset=utf-8"
        if self.path == "/static/app.js":
            body = "window.appLoaded = true;"
            ctype = "text/javascript"
        elif self.path == "/adserver/adscript.js":
            body = "window.adLoaded = true;"
            ctype = "text/javascript"
        elif self.path == "/scripts/1/My%20Script%20%E2%80%93%20HD%20%28Video%2C%20X%29.user.js":
            body = USERSCRIPT    # a Greasy Fork-style address with the script's name in it
            ctype = "text/javascript"
        elif self.path == "/test.user.js":
            body = USERSCRIPT
            ctype = "text/javascript"
        else:
            body = PAGE
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atlasbrowser.adblock import FilterEngine, _RT  # noqa: E402
from atlasbrowser.extensions import parse_meta, site_patterns  # noqa: E402
from atlasbrowser.store import Store  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, timeout=20, step=100):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(step)
    return False


def js(tab, code):
    box = {}
    tab.page().runJavaScript(code, lambda r: box.setdefault("v", r))
    wait_until(lambda: "v" in box, 10)
    return box.get("v")


def load(tab, url):
    done = []

    def finished(ok):
        done.append(ok)
    tab.loadFinished.connect(finished)
    tab.load(url)
    ok = wait_until(lambda: bool(done))
    tab.loadFinished.disconnect(finished)
    pump(300)
    return ok and done[0]


def main():
    # -------- filter engine --------
    e = FilterEngine()
    e.add_text("""! comment
||ads.example^
||tracker.example^$third-party
/adscript.js$script
@@||ads.example/allowed/*
example.org##.sponsored
example.org#@#.sponsored-ok
||weird.example^$redirect=noop.js
""")
    S, I = _RT.ResourceTypeScript, _RT.ResourceTypeImage
    check("blocks listed ad domain", e.should_block("https://ads.example/x.js", "ads.example", S, "news.test"))
    check("blocks subdomains too", e.should_block("https://cdn.ads.example/x.js", "cdn.ads.example", S, "news.test"))
    check("exception rule wins", not e.should_block("https://ads.example/allowed/a.js", "ads.example", S, "news.test"))
    check("third-party option", e.should_block("https://tracker.example/p", "tracker.example", I, "news.test")
          and not e.should_block("https://tracker.example/p", "tracker.example", I, "tracker.example"))
    check("type option", e.should_block("https://x.test/adscript.js", "x.test", S, "x.test")
          and not e.should_block("https://x.test/adscript.js", "x.test", I, "x.test"))
    check("unsupported options are skipped, not half-applied",
          not e.should_block("https://weird.example/a", "weird.example", S, "news.test"))
    check("ordinary requests pass", not e.should_block("https://cdn.test/app.js", "cdn.test", S, "news.test"))
    check("site element hiding", ".sponsored" in e.hide_css("www.example.org") and e.hide_css("other.test") == "")

    check("userscript header parsed", parse_meta(USERSCRIPT)["name"] == "Test Marker"
          and parse_meta(USERSCRIPT)["include"] == ["http://127.0.0.1:*/*"])
    check("plain site names become match patterns", site_patterns("youtube.com") == ["*://youtube.com/*", "*://*.youtube.com/*"])

    # -------- in the browser --------
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{srv.server_address[1]}"

    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import ProfileHub
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    root = Store()
    hub = ProfileHub(app, root, Browser)
    ctx = hub.context("default")
    engine = FilterEngine()
    engine.add_text("/adserver/*$script\n127.0.0.1##.ad-box\n")
    wait_until(lambda: not ctx.blocker.lists._loading, 60)   # the real lists load in the background first
    ctx.blocker.lists.engine = engine
    win = hub.open_profile("default", ["about:blank"])
    tab = win.current_tab()
    check("toolbar has the extensions button", win.ext_btn is not None)

    check("page loads", load(tab, site + "/"))
    check("ad script blocked", js(tab, "!!window.adLoaded") is False and js(tab, "!!window.appLoaded") is True)
    check("blocked count shown", ctx.blocker.counts.get("127.0.0.1", 0) >= 1 and win.ext_btn.text() != "",
          f"{ctx.blocker.counts} '{win.ext_btn.text()}'")
    check("ad element hidden", wait_until(lambda: js(tab, "getComputedStyle(document.getElementById('adbox')).display") == "none", 5))
    check("page content untouched", js(tab, "getComputedStyle(document.getElementById('content')).display") != "none")

    ctx.blocker.set_paused("127.0.0.1", True)
    load(tab, site + "/?2")
    check("pausing on a site lets its ads through", js(tab, "!!window.adLoaded") is True)
    ctx.blocker.set_paused("127.0.0.1", False)
    root.set("adblock", False)
    load(tab, site + "/?3")
    check("turning the blocker off works", js(tab, "!!window.adLoaded") is True)
    root.set("adblock", True)

    # userscripts
    code = ctx.extensions.fetch(site + "/test.user.js")
    try:
        named = ctx.extensions.fetch(site + "/scripts/1/My Script – HD %28Video%2C X%29.user.js")
    except Exception as e:
        named = str(e)
    check("scripts whose address has spaces and dashes in it download", named == code, named[:120])
    ext = ctx.extensions.install(code, source_url=site + "/test.user.js")
    load(tab, site + "/?4")
    check("userscript runs on matching pages", js(tab, "document.documentElement.dataset.us") == "ran")
    check("GM storage works", js(tab, "localStorage.getItem('__wf_gm_" + ext["id"] + "_n')") == "1")
    cmds = json.loads(js(tab, __import__("atlasbrowser.extensions", fromlist=["x"]).menu_commands_js()) or "[]")
    check("script menu commands are listed", [c[2] for c in cmds if not c[2].endswith("for this site")] == ["Say hi"],
          str(cmds))
    from atlasbrowser.extensions import run_menu_command_js
    js(tab, run_menu_command_js(ext["id"], 0))
    check("menu command runs", js(tab, "document.documentElement.dataset.cmd") == "hi")
    win.ext_btn._fill()
    labels = [a.text() for a in win.ext_btn.menu_.actions()]
    check("toolbar menu lists the script and site toggle",
          "Test Marker" in labels and any(t.startswith("Block ads on 127.0.0.1") for t in labels), str(labels))

    ctx.extensions.set_enabled(ext["id"], False)
    load(tab, site + "/?5")
    check("disabled script doesn't run", js(tab, "String(document.documentElement.dataset.us)") == "undefined",
          f"{js(tab, 'document.documentElement.dataset.us')!r} {[x.name() for x in ctx.profile.scripts().toList()]}")
    ctx.extensions.set_enabled(ext["id"], True)

    # your own site style
    from atlasbrowser.extensions_ui import ScriptEditor
    ed = ScriptEditor(win)
    ed.name.setText("Hide content")
    ed.sites.setText("127.0.0.1")
    ed.editor.setPlainText("#content { visibility: hidden !important; }")
    style_code, kind = ed.result_code()
    ctx.extensions.install(style_code, kind=kind)
    load(tab, site + "/?6")
    check("custom site style applies", js(tab, "getComputedStyle(document.getElementById('content')).visibility") == "hidden",
          f"{js(tab, 'document.title')} {js(tab, 'document.styleSheets.length')} {[x.name() for x in ctx.profile.scripts().toList()]}")

    # private windows and other profiles
    pwin = ctx.new_window(private=True, urls=["about:blank"])
    ptab = pwin.current_tab()
    load(ptab, site + "/?7")
    check("scripts don't run in private windows", js(ptab, "String(document.documentElement.dataset.us)") == "undefined",
          f"{js(ptab, 'document.documentElement.dataset.us')!r} {js(ptab, 'location.href')}")
    check("ad blocker still works in private windows", js(ptab, "String(!!window.adLoaded)") == "false",
          str(js(ptab, "String(!!window.adLoaded)")))
    pwin.close()
    work_id = hub.profiles.add("Work")["id"]
    wctx = hub.context(work_id)
    wctx.blocker.lists.engine = engine
    wwin = hub.open_profile(work_id, ["about:blank"])
    wtab = wwin.current_tab()
    load(wtab, site + "/?8")
    check("another profile has its own extensions", js(wtab, "String(document.documentElement.dataset.us)") == "undefined"
          and [e["source"] for e in wctx.extensions.items] == ["pelagic:darkmode"])   # only the built-in one
    wwin.close()

    ctx.extensions.remove(ext["id"])
    check("remove", ctx.extensions.get(ext["id"]) is None)
    win.close()
    srv.shutdown()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
