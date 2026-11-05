"""Chrome-style extras: the downloads page (pause / resume / retry), site permissions, spell check, autofill,
leaked-password and unsafe-site checks, and folder sync.

Run:  python tests/chrome_parity_test.py
"""
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_parity_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring
DL = tempfile.mkdtemp(prefix="atlas_parity_dl_")

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SIZE = 3 * 1024 * 1024
CHECKOUT = b"""<title>Checkout</title><form action="/checkout/done" onsubmit="return false">
<label for=fn>First name</label><input id=fn name=fname> <input id=ln name=lname placeholder="Last name">
<input id=addr name=address1 placeholder="Street address"> <input id=city name=city>
<select id=state name=state><option value="">State</option><option value="CA">California</option>
<option value="NY">New York</option></select> <input id=zip name=zip> <input id=em type=email name=email>
<input id=cc name=cardnumber> <select id=mm name=exp_month><option value="">MM</option>
<option value="1">01</option><option value="2">02</option><option value="3">03</option><option value="4">04</option>
<option value="5">05</option><option value="6">06</option><option value="7">07</option><option value="8">08</option>
<option value="9">09</option><option value="10">10</option><option value="11">11</option><option value="12">12</option>
</select> <input id=yy name=exp_year maxlength=2> <input id=cvc name=cvc> <button id=go type=submit>Pay</button>
</form>"""


class Slow(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/file"):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(SIZE))
            self.send_header("Content-Disposition", 'attachment; filename="big.bin"')
            self.end_headers()
            chunk = b"x" * 65536
            try:
                for _ in range(SIZE // len(chunk)):
                    self.wfile.write(chunk)
                    time.sleep(0.12)
            except OSError:
                pass
            return
        if self.path.startswith("/checkout"):
            body = CHECKOUT
        else:
            body = b"<title>Form</title><form><input id=name name=name autocomplete=name>" \
                   b"<input id=email name=email type=email><input id=street autocomplete=street-address></form>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(cond, ms=10000):
    for _ in range(ms // 50):
        if cond():
            return True
        pump(50)
    return cond()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import downloads
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    downloads.downloads_folder = lambda: DL
    store = Store()
    sb = (store.shared or store).root / "safebrowsing"
    sb.mkdir(parents=True, exist_ok=True)
    (sb / "openphish.txt").write_text(f"{base}/phish\nhttps://sites.google.com/view/fake-bank\n")
    (sb / "phishing-army.txt").write_text("# test list\nevil-login.example\nsites.google.com\n")
    (sb / "urlhaus-hosts.txt").write_text("127.0.0.1\tmalware.example\n127.0.0.1\tlocalhost\n")
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, [base + "/form"])
    win.resize(1200, 800)
    win.show()
    tab = win.current_tab()
    wait(lambda: not tab.loading and tab.title() == "Form")
    ctx = win.ctx

    # ---------------------------------------------------------------- downloads
    page = ctx.downloads
    store.set("download_ask", False)
    tab.page().download(QUrl(base + "/file"), "big.bin")
    check("a download shows on the downloads page", wait(lambda: page.rows and page.rows[0].req is not None, 5000))
    row = page.rows[0]
    check("it saves straight to Downloads when not asking", row.entry["path"] == os.path.join(DL, "big.bin"),
          row.entry["path"])
    wait(lambda: row.req.receivedBytes() > 200_000, 8000)
    pump(1200)
    page._tick()
    check("it shows progress, speed and time left", " of " in row.status.text() and "/s" in row.status.text()
          and "left" in row.status.text(), row.status.text())
    labels = lambda: [row.buttons.itemAt(i).widget().text() for i in range(row.buttons.count())  # noqa: E731
                      if row.buttons.itemAt(i).widget() is not None]
    check("Pause and Cancel while running", labels() == ["Pause", "Cancel"], str(labels()))
    row.req.pause()
    check("Pause pauses it", wait(lambda: row.state() == "paused", 3000) and "Paused" in row.status.text())
    pump(200)
    check("Resume while paused", "Resume" in labels(), str(labels()))
    row.req.resume()
    check("Resume finishes it", wait(lambda: row.state() == "done", 30000), row.status.text())
    pump(300)
    check("the file is complete", os.path.getsize(row.entry["path"]) == SIZE)
    check("Open and Show in folder when done", labels()[:2] == ["Open", "Show in folder"], str(labels()))
    check("finished downloads are remembered", store.get("downloads_history")
          and store.get("downloads_history")[0]["path"] == row.entry["path"])
    tab.page().download(QUrl(base + "/file"), "big.bin")
    check("a second copy gets a new name", wait(lambda: len(page.rows) == 2) and
          page.rows[0].entry["path"] == os.path.join(DL, "big (1).bin"), page.rows[0].entry["path"])
    page.rows[0].req.cancel()
    check("Cancel", wait(lambda: page.rows[0].state() == "cancelled"))
    pump(200)
    r0 = page.rows[0]
    check("Retry after cancelling", "Retry" in [r0.buttons.itemAt(i).widget().text() for i in range(r0.buttons.count())
                                               if r0.buttons.itemAt(i).widget() is not None])
    page.retry(r0)
    check("Retry downloads it again", wait(lambda: len(page.rows) == 2 and page.rows[0].req is not None
                                           and page.rows[0].state() == "running", 5000))
    page.rows[0].req.cancel()
    wait(lambda: page.rows[0].state() == "cancelled")
    page.search.setText("nothing-like-this")
    check("search filters the list", all(not r.isVisibleTo(page) for r in page.rows))
    page.search.setText("")
    again = downloads.DownloadsPage(store)
    check("the list is still there after a restart", any(r.entry["path"].endswith("big.bin") for r in again.rows))
    os.remove(os.path.join(DL, "big.bin"))
    again2 = downloads.DownloadsPage(store)
    check("a deleted file shows as removed", any(r.state() == "missing" for r in again2.rows))
    page.clear_finished()
    check("Clear list empties finished ones", not page.rows and not store.get("downloads_history"))

    # ---------------------------------------------------------------- site permissions
    from atlasbrowser.sitesettings import SitePermissionsDialog, S, T
    prof = win.profile
    prof.queryPermission(QUrl(base), T.Geolocation).grant()
    prof.queryPermission(QUrl(base), T.Notifications).deny()
    d = SitePermissionsDialog(prof, win)
    head = d.tree.topLevelItem(0)
    check("site permissions lists the site", head is not None and head.text(0) == "127.0.0.1" and head.childCount() == 2,
          head.text(0) if head else "")
    kids = {head.child(i).text(0): d.tree.itemWidget(head.child(i), 1) for i in range(head.childCount())}
    check("with each permission and its setting", kids["Location"].currentText() == "Allow"
          and kids["Notifications"].currentText() == "Block", str({k: v.currentText() for k, v in kids.items()}))
    kids["Location"].setCurrentIndex(1)
    check("switching to Block blocks it", prof.queryPermission(QUrl(base), T.Geolocation).state() == S.Denied)
    d.tree.setCurrentItem(head)
    d.reset_site()
    check("Reset this site forgets its choices", prof.queryPermission(QUrl(base), T.Geolocation).state() == S.Ask
          and prof.queryPermission(QUrl(base), T.Notifications).state() == S.Ask)
    check("the menu has Site permissions", any("Site permissions" in a.text() for a in win.menu_btn.menu().actions()))
    check("the menu has Print with Ctrl+P", "Print…\tCtrl+P" in [a.text() for a in win.menu_btn.menu().actions()])

    # ---------------------------------------------------------------- spell check
    import base64
    import io
    from atlasbrowser import spellcheck
    fetched = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        fetched.append(req.full_url)
        return Resp(base64.b64encode(b"BDic" + b"\0" * 64))
    spellcheck.urllib.request.urlopen = fake_urlopen
    check("spell check is off by default", not prof.isSpellCheckEnabled())
    store.set("spellcheck", True)
    store.set("spellcheck_lang", "en-GB")
    notes = []
    spellcheck.ensure(store, [prof], notes.append)
    check("turning it on downloads the dictionary once", wait(lambda: spellcheck.have("en-GB"), 5000)
          and "en-GB-10-1.bdic" in fetched[0], str(fetched))
    # (the engine itself only switches on with a real dictionary, which this test doesn't download)
    check("then spell check is set to that language", wait(lambda: prof.spellCheckLanguages() == ["en-GB"], 3000),
          str(prof.spellCheckLanguages()))
    check("and you're told", any("Spell check is on" in n for n in notes), str(notes))
    store.set("spellcheck", False)
    spellcheck.ensure(store, [prof])
    check("turning it off", not prof.isSpellCheckEnabled() and len(fetched) == 1)

    # ---------------------------------------------------------------- addresses and cards
    import json as _json
    from atlasbrowser import autofill, pagejs
    af = ctx.passwords.autofill
    check("Luhn check", autofill.luhn_ok("4242 4242 4242 4242") and not autofill.luhn_ok("4242 4242 4242 4243"))
    check("card label is masked", autofill.card_label({"cc_number": "4242424242424242"}) == "Visa •••• 4242")
    win.navigate(base + "/checkout") if hasattr(win, "navigate") else tab.setUrl(QUrl(base + "/checkout"))
    wait(lambda: not tab.loading and tab.title() == "Checkout")
    pump(500)

    def js(code):
        box = {}
        tab.page().runJavaScript(code, lambda r: box.setdefault("v", r))
        wait(lambda: "v" in box, 5000)
        return box.get("v")

    def center(sel):
        return _json.loads(js(f"(function(){{var r=document.querySelector('{sel}').getBoundingClientRect();"
                              f"return JSON.stringify([r.left+r.width/2, r.top+r.height/2])}})()"))
    check("autofill helpers are hidden from page scripts", js("typeof window.__pfFill") == "undefined")
    js("""(function(){var v={fn:'Ada',ln:'Lovelace',addr:'12 Analytical St',city:'Springfield',zip:'94016',
          em:'ada@example.com',cc:'4242 4242 4242 4242',yy:'29',cvc:'123'};
          for (var k in v) document.getElementById(k).value=v[k];
          document.getElementById('state').value='CA'; document.getElementById('mm').value='7'; return 1})()""")
    snap = _json.loads(js(pagejs.SNAPSHOT))
    shown = {it.get("placeholder") or it.get("text"): it.get("value") for it in snap["items"]}
    check("the agent never sees card fields", "4242" not in _json.dumps(snap) and "123" not in
          [it.get("value") for it in snap["items"]], _json.dumps(snap["items"])[:400])
    check("but still sees the address", any(v == "12 Analytical St" for v in shown.values()))
    tab.real_click(*center("#go"))
    check("after paying it offers to save the card", wait(lambda: win.save_bar.isVisible(), 4000)
          and "Visa •••• 4242" in win.save_bar.label.text() and "security code" in win.save_bar.label.text(),
          win.save_bar.label.text())
    win.save_bar.save_btn.click()
    card = (af.store.items("cards") or [{}])[0]
    check("the card is saved without the security code", card.get("cc_number") == "4242424242424242"
          and card.get("cc_month") == "7" and card.get("cc_year") == "2029" and "123" not in _json.dumps(card),
          str(card))
    check("then it offers the address", win.save_bar.isVisible() and "12 Analytical St" in win.save_bar.label.text(),
          win.save_bar.label.text())
    win.save_bar.save_btn.click()
    addr = (af.store.items("addresses") or [{}])[0]
    check("the address is saved", addr.get("name") == "Ada Lovelace" and addr.get("city") == "Springfield"
          and addr.get("state") == "California" and addr.get("email") == "ada@example.com", str(addr))
    if sys.platform != "win32":
        check("addresses and cards survive a restart", autofill.AutofillStore(store.root).items("cards"))
    tab.real_click(*center("#go"))
    pump(1200)
    check("the same card and address aren't offered again", not win.save_bar.isVisible())

    tab.setUrl(QUrl(base + "/checkout?again"))
    wait(lambda: not tab.loading)
    pump(500)
    tab.real_click(*center("#fn"))
    check("focusing an address field offers saved addresses", wait(lambda: QApplication.activePopupWidget()
          is not None, 3000) and "Ada Lovelace" in QApplication.activePopupWidget().actions()[0].text())
    QApplication.activePopupWidget().actions()[0].trigger()
    QApplication.activePopupWidget() and QApplication.activePopupWidget().close()
    pump(400)
    got = _json.loads(js("JSON.stringify(['fn','ln','addr','city','state','zip','em'].map(function(i){"
                         "return document.getElementById(i).value}))"))
    check("picking one fills the whole address", got == ["Ada", "Lovelace", "12 Analytical St", "Springfield", "CA",
                                                         "94016", "ada@example.com"], str(got))
    check("but not the card", js("document.getElementById('cc').value") == "")
    tab.real_click(*center("#cc"))
    check("focusing the card field offers saved cards, masked", wait(lambda: QApplication.activePopupWidget()
          is not None, 3000) and QApplication.activePopupWidget().actions()[0].text().startswith("Visa •••• 4242"))
    QApplication.activePopupWidget().actions()[0].trigger()
    QApplication.activePopupWidget() and QApplication.activePopupWidget().close()
    pump(400)
    got = _json.loads(js("JSON.stringify(['cc','mm','yy','cvc'].map(function(i){return document.getElementById(i).value}))"))
    check("picking it fills number and expiry, never the security code", got == ["4242424242424242", "7", "29", ""],
          str(got))
    store.set("autofill", False)
    js("document.activeElement.blur()")
    tab.real_click(*center("#fn"))
    pump(800)
    check("no offers when turned off", QApplication.activePopupWidget() is None)
    store.set("autofill", True)
    check("the menu has Addresses and cards",
          any("Addresses and cards" in a.text() for a in win.menu_btn.menu().actions()))
    from atlasbrowser.autofill_ui import AutofillDialog
    d = AutofillDialog(af, win)
    check("the Addresses and cards page lists both", d.lists["cards"].count() == 1 and d.lists["addresses"].count() == 1
          and "•••• 4242" in d.lists["cards"].item(0).text())

    # ---------------------------------------------------------------- password checkup
    from atlasbrowser import pwcheck
    leaked = pwcheck.sha1("hunter2")

    def fake_range(prefix):
        lines = ["0018A45C4D1DEF81644B54AB7F969B88D65:1"]
        if prefix == leaked[:5]:
            lines.append(leaked[5:] + ":17000")
        asked.append(prefix)
        return "\r\n".join(lines)
    asked = []
    logins = [{"id": "a", "password": "hunter2"}, {"id": "b", "password": "Tr0ub4dor&3-horse-staple"},
              {"id": "c", "password": "Tr0ub4dor&3-horse-staple"}, {"id": "d", "password": "qwerty"},
              {"id": "e", "password": "xK9#mP2$vL7!qR4w"}]
    out = pwcheck.checkup(logins, fetch=fake_range)
    iss = out["issues"]
    check("checkup finds the leaked password", iss.get("a", {}).get("leaked") == 17000, str(iss))
    check("and reused ones", iss.get("b", {}).get("reused") == 1 and iss.get("c", {}).get("reused") == 1)
    check("and weak ones", iss.get("d", {}).get("weak") and "e" not in iss, str(iss))
    check("only 5-character hash prefixes are sent", all(len(p) == 5 for p in asked)
          and "hunter2" not in "".join(asked) and len(asked) == 4, str(asked))

    def offline(prefix):
        raise OSError("no network")
    out = pwcheck.checkup(logins, fetch=offline)
    check("offline it still reports reuse and weak passwords", out["error"] and "b" in out["issues"]
          and "d" in out["issues"])
    from atlasbrowser.passwords_ui import PasswordsDialog
    pd = PasswordsDialog(ctx.passwords, win)
    check("the Passwords page has a Checkup tab",
          any(pd.findChild(type(pd.check_btn)) for _ in [0]) and pd.check_btn.text() == "Check passwords")

    # ---------------------------------------------------------------- unsafe sites
    from atlasbrowser import safebrowsing
    guard = ctx.safe
    check("threat lists load", wait(lambda: guard.lists.hosts, 5000), str(guard.lists.hosts))
    check("a listed host is flagged", guard.check(QUrl("https://www.evil-login.example/x")) == "phishing")
    check("a malware host is flagged as malware", guard.check(QUrl("http://malware.example/a.exe")) == "malware")
    check("big shared hosts are never flagged as a whole", guard.check(QUrl("https://sites.google.com/view/ok"))
          is None and guard.check(QUrl("https://sites.google.com/view/fake-bank")) == "phishing")
    check("localhost and normal pages are fine", guard.check(QUrl(base + "/form")) is None
          and guard.check(QUrl("http://localhost/")) is None)
    tab.setUrl(QUrl(base + "/phish/login.html"))
    check("opening a phishing address shows the warning", wait(lambda: safebrowsing.is_warning(tab.url())
          and tab.title() == "Deceptive site ahead", 5000), tab.url().toString())
    pump(300)
    check("the address bar still shows the blocked address", win.addr.text() == base + "/phish/login.html",
          win.addr.text())
    js("document.querySelector('a.b').click()")
    check("Back to safety goes back", wait(lambda: tab.title() == "Checkout" or "checkout" in tab.url().toString(),
                                           5000), tab.url().toString())
    tab.setUrl(QUrl(base + "/phish/login.html"))
    wait(lambda: safebrowsing.is_warning(tab.url()), 5000)
    pump(300)
    js("document.querySelector('details').open = true; document.querySelector('details a').click()")
    check("Visit anyway opens it", wait(lambda: tab.url().toString() == base + "/phish/login.html", 5000),
          tab.url().toString())
    check("and it isn't blocked again this session", guard.check(QUrl(base + "/phish/other")) is None)
    guard.allowed.clear()
    store.set("safe_browsing", False)
    check("turning it off stops the warnings", guard.check(QUrl("https://evil-login.example/")) is None)
    store.set("safe_browsing", True)

    # ---------------------------------------------------------------- sync settings
    from atlasbrowser.dialogs import SettingsDialog
    from PySide6.QtWidgets import QTabWidget
    sd = SettingsDialog(store, win, win, start="sync")
    tw = sd.findChild(QTabWidget)
    check("Settings has a Sync tab that opens directly", tw.tabText(tw.currentIndex()) == "Sync"
          and tw.tabText(tw.count() - 1) == "Agent", tw.tabText(tw.currentIndex()))
    sync_dir = tempfile.mkdtemp(prefix="atlas_parity_sync_")
    store.set("sync_folder", sync_dir)
    reports = []
    ctx.sync_now(reports.append)
    check("Sync now writes this computer's file", wait(lambda: reports, 5000)
          and list(Path(sync_dir, "Pelagic Sync", DEFAULT_ID).glob("*.json")), str(reports))
    store.set("sync_folder", "")

    win.close()
    hub.stop_all()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
