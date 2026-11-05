"""Saved passwords: encrypted store, save prompt after sign-in, autofill, privacy rules and Google/CSV import.

Run:  python tests/passwords_test.py          (add --visible to show the window)
"""
import base64
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
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_pw_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


LOGIN = """<title>Login</title><form action="/done" method="get">
<input id=u name=email type=email placeholder="Email"><input id=p name=pw type=password>
<button id=go type=submit>Sign in</button></form>"""


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = "<title>Done</title><h1>Welcome</h1>" if self.path.startswith("/done") else LOGIN
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atlasbrowser.passwords import PasswordStore, _matches, origin_of  # noqa: E402
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


def center(tab, sel):
    r = js(tab, f"(function(){{var r=document.querySelector('{sel}').getBoundingClientRect();"
                f"return JSON.stringify([r.left+r.width/2, r.top+r.height/2])}})()")
    return json.loads(r)


def type_into(tab, sel, text):
    x, y = center(tab, sel)
    tab.real_click(x, y)
    pump(150)
    for ch in text:
        tab.type_char(ch)
    pump(100)


def main():
    # -------- store (no page) --------
    root = Path(tempfile.mkdtemp(prefix="atlas_pw_store_"))
    ps = PasswordStore(root)
    a = ps.add("https://example.com", "me@x.com", "hunter2")
    check("origin normalised", origin_of("HTTPS://Example.com:443/login?x") == "https://example.com")
    check("www twin matches", _matches("https://www.example.com", "https://example.com"))
    check("https login never offered to http page", not _matches("https://example.com", "http://example.com"))
    check("other site does not match", not _matches("https://example.com", "https://evil-example.com"))
    check("lookup by origin", [x["username"] for x in ps.for_origin("https://www.example.com")] == ["me@x.com"])
    check("survives reload", PasswordStore(root).get(a["id"])["password"] == "hunter2")
    check("file is encrypted", b"hunter2" not in base64.b64decode((root / "passwords.dat").read_bytes()))
    ps.update(a["id"], password="new-pass")
    check("update", PasswordStore(root).get(a["id"])["password"] == "new-pass")
    ps.add_never("https://bank.test")
    check("never list", ps.is_never("https://bank.test") and not ps.is_never("https://example.com"))
    csv_path = root / "Google Passwords.csv"
    csv_path.write_text("name,url,username,password,note\n"
                        "example.com,https://example.com/,me@x.com,new-pass,\n"
                        "github.com,https://github.com/login,octo,gh-secret,work\n"
                        "app,android://abc@com.app/,u,p,\n", encoding="utf-8")
    added, updated, skipped = ps.import_csv(csv_path)
    check("Google CSV import", (added, updated, skipped) == (1, 0, 2), str((added, updated, skipped)))
    check("imported login usable", ps.find("https://github.com", "octo")["password"] == "gh-secret")
    ps.delete(a["id"])
    check("delete", ps.find("https://example.com", "me@x.com") is None)

    # -------- in the browser --------
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{srv.server_address[1]}"

    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    browser = Browser(app, store)
    win = browser.new_window(urls=[site + "/login"])
    tab = win.current_tab()
    win.show()
    check("login page loads", wait_until(lambda: tab.title() == "Login" and not tab.loading))
    pump(400)
    check("helpers hidden from page scripts", js(tab, "typeof window.__wfFill") == "undefined")

    type_into(tab, "#u", "alice@test.dev")
    type_into(tab, "#p", "s3cret!")
    x, y = center(tab, "#go")
    tab.real_click(x, y)
    check("save prompt after sign-in", wait_until(lambda: win.save_bar.isVisible()))
    pending = win.save_bar.pending
    check("prompt holds the typed login", pending and pending[2:4] == ("alice@test.dev", "s3cret!"), str(pending))
    win.save_bar.save_btn.click()
    pw = browser.passwords.store
    saved = pw.find(origin_of(site), "alice@test.dev")
    check("saved", saved and saved["password"] == "s3cret!")

    # autofill: focusing the field offers the account; choosing it fills both fields
    calls = []
    orig = browser.passwords.field_focused
    browser.passwords.field_focused = lambda t, fx, fy: (calls.append((t, fx, fy)), orig(t, fx, fy))
    tab.load(site + "/login")
    check("back on login", wait_until(lambda: tab.title() == "Login" and not tab.loading))
    pump(400)
    x, y = center(tab, "#u")
    tab.real_click(x, y)
    check("focusing login field asks for accounts", wait_until(lambda: bool(calls), 5))
    browser.passwords.fill(tab, saved["id"])
    check("autofill fills username and password", wait_until(
        lambda: js(tab, "document.getElementById('u').value + '|' + document.getElementById('p').value")
        == "alice@test.dev|s3cret!", 5))

    # same login again: no prompt
    win.save_bar.dismiss()
    x, y = center(tab, "#go")
    tab.real_click(x, y)
    pump(1200)
    check("no prompt when nothing changed", not win.save_bar.isVisible())

    # a changed password offers an update
    tab.load(site + "/login")
    wait_until(lambda: tab.title() == "Login" and not tab.loading)
    pump(400)
    type_into(tab, "#u", "alice@test.dev")
    type_into(tab, "#p", "changed")
    x, y = center(tab, "#go")
    tab.real_click(x, y)
    check("update prompt", wait_until(lambda: win.save_bar.isVisible() and win.save_bar.save_btn.text() == "Update"))
    win.save_bar.save_btn.click()
    check("updated", pw.find(origin_of(site), "alice@test.dev")["password"] == "changed")

    # agent running: no prompts, no fill menu
    class FakeAgent:
        running, waiting_for_user = True, False
    win.panel.agent = FakeAgent()
    calls.clear()
    browser.passwords.submitted(tab, "bob", "pw")
    browser.passwords.field_focused(tab, 0, 0)
    pump(900)
    check("agent run never triggers save prompt", not win.save_bar.isVisible())
    win.panel.agent = None

    # private windows never save
    pwin = browser.new_window(private=True, urls=[site + "/login"])
    ptab = pwin.current_tab()
    wait_until(lambda: ptab.title() == "Login" and not ptab.loading)
    browser.passwords.submitted(ptab, "carol", "pw")
    pump(900)
    check("private window never offers to save", not pwin.save_bar.isVisible())
    pwin.close()

    # never for this site
    store.set("save_passwords", True)
    browser.passwords.submitted(tab, "dave", "pw1")
    wait_until(lambda: win.save_bar.isVisible(), 5)
    win.save_bar.never_btn.click()
    browser.passwords.submitted(tab, "erin", "pw2")
    pump(900)
    check("'Never for this site' is respected", not win.save_bar.isVisible() and pw.is_never(origin_of(site)))

    # Google export: caught, imported, deleted
    class FakePage:
        def url(self):
            from PySide6.QtCore import QUrl
            return QUrl("https://passwords.google.com/options")

    class FakeReq:

        def __init__(self):
            self.dir = self.name = None
            self.done = False

        def page(self):
            return FakePage()

        def downloadFileName(self):
            return "Google Passwords.csv"

        def setDownloadDirectory(self, d):
            self.dir = d

        def setDownloadFileName(self, n):
            self.name = n

        def accept(self):
            Path(self.dir, self.name).write_text("name,url,username,password,note\n"
                                                 "x,https://shop.test/,zed,zz-pass,\n", encoding="utf-8")

        class _Sig:
            def connect(self, fn):
                pass
        stateChanged = _Sig()

        def state(self):
            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest as R
            return R.DownloadState.DownloadCompleted

    from atlasbrowser import passwords as P
    P.PasswordManager._report = staticmethod(lambda w, r: None)
    req = FakeReq()
    check("other downloads untouched", not browser.passwords.intercept_download(req))
    browser.passwords._google_until = time.time() + 60
    browser.passwords._google_win = win
    check("Google export intercepted", browser.passwords.intercept_download(req))
    check("Google passwords imported", (pw.find("https://shop.test", "zed") or {}).get("password") == "zz-pass")
    check("exported file deleted", not Path(req.dir, req.name).exists())

    win.close()
    srv.shutdown()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
