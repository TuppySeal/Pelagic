"""Proxy / VPN connection (proxy.py) and Pi-hole style blocked domains (blocklist.py).

A local HTTP server plays the proxy: Pelagic is set to use it, so made-up domains (shop.test, ads.example.test)
reach it, which shows both that the proxy setting is applied and that blocked domains never get there.

Run:  python tests/network_test.py          (add --visible to show the window)
"""
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_network_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")
for _name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_name, None)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


from PySide6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SEEN = []   # (host, path) of every request that reached the proxy
HOSTS_LIST = "# test list\n0.0.0.0 tracker.example.test\n127.0.0.1 localhost\n0.0.0.0 0.0.0.0\n"


class Proxy(BaseHTTPRequestHandler):
    def do_GET(self):
        url = QUrl(self.path)
        host = url.host() or self.headers.get("Host", "").split(":")[0]
        SEEN.append((host, url.path() or self.path))
        if url.path() == "/hosts.txt":
            body, kind = HOSTS_LIST.encode(), "text/plain"
        elif url.path() == "/page":
            body = (b"<title>Shop</title><p>shop</p><img id=a src='http://ads.example.test/ad.png'>"
                    b"<img id=b src='http://cdn.example.test/ok.png'>"
                    b"<img id=c src='http://tracker.example.test/t.png'>")
            kind = "text/html"
        else:
            body, kind = f"<title>{host}</title>ok".encode(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
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


def unit_checks(port):
    from atlasbrowser import blocklist, proxy
    pd = blocklist.parse_domain
    check("domain lines: plain, wildcard, adblock style and hosts files",
          pd("Example.COM") == "example.com" and pd("*.ads.net") == "ads.net" and pd("||t.co^") == "t.co"
          and pd("0.0.0.0 ads.example.com # x") == "ads.example.com" and pd("https://www.x.org/path") == "www.x.org")
    check("comments, addresses and localhost are ignored",
          not any(pd(x) for x in ("# c", "! c", "127.0.0.1 localhost", "0.0.0.0 0.0.0.0", "10.0.0.1", "nodot",
                                  "bad domain.com", "")))

    class S(dict):
        def get(self, k):
            return dict.get(self, k)

        def set(self, k, v):
            self[k] = v
    st = S(blocked_domains=["example.com"], allowed_domains=[], blocklist_urls=[])
    db = blocklist.DomainBlocker(st, blocklist.Lists(Path(tempfile.mkdtemp())))
    check("a blocked domain covers its subdomains", db.match("www.Example.com") == "example.com"
          and db.match("example.com") and not db.match("notexample.com") and not db.match("example.org"))
    st["allowed_domains"] = ["safe.example.com"]
    db.refresh()
    check("never-block list wins", not db.match("a.safe.example.com") and db.match("other.example.com"))
    st["domain_block"] = False
    check("switched off, nothing is blocked", not db.match("www.example.com"))
    st["domain_block"] = True
    db.add("https://bad.test/x")
    check("add() takes a pasted address", "bad.test" in st["blocked_domains"] and db.match("x.bad.test"))
    db.remove("bad.test")
    check("remove() unblocks it", not db.match("x.bad.test"))

    good = {"mode": "manual", "scheme": "socks5", "host": "127.0.0.1", "port": 9050, "bypass": "localhost; <local>",
            "webrtc_private": True}
    flags = proxy.chromium_flags(good)
    check("manual proxy switches", flags[:2] == ["--proxy-server=socks5://127.0.0.1:9050",
                                                 "--proxy-bypass-list=localhost;<local>"]
          and "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in flags, flags)
    check("direct and system settings", proxy.chromium_flags({"mode": "direct"}) == ["--no-proxy-server"]
          and proxy.chromium_flags({"mode": "system"}) == [])
    check("bad settings are refused and add no switches",
          proxy.problem({**good, "host": "a b"}) and proxy.problem({**good, "port": 0})
          and proxy.problem({"mode": "pac", "pac": "javascript:x"}) and not proxy.chromium_flags({**good, "host": ""}))
    check("PAC address", proxy.chromium_flags({"mode": "pac", "pac": "http://wpad/p.pac", "webrtc_private": False})
          == ["--proxy-pac-url=http://wpad/p.pac"])
    # the Test button against a fake SOCKS5 server, and against nothing at all
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def answer():
        c, _ = srv.accept()
        c.recv(4)
        c.sendall(b"\x05\x00")
        c.close()
    threading.Thread(target=answer, daemon=True).start()
    out = proxy.test_connection({**good, "port": srv.getsockname()[1]})
    check("Test proxy recognises a SOCKS5 server", out.startswith("Connected"), out)
    srv.close()
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    dead = free.getsockname()[1]
    free.close()
    out = proxy.test_connection({**good, "port": dead}, timeout=2)
    check("Test proxy says when nothing answers", out.startswith("Couldn't reach"), out)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port
    unit_checks(port)

    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser import proxy
    from atlasbrowser.app import Browser
    from atlasbrowser.profiles import DEFAULT_ID, ProfileHub
    from atlasbrowser.store import Store
    store = Store()
    store.set("proxy", {"mode": "manual", "scheme": "http", "host": "127.0.0.1", "port": port, "bypass": ""})
    store.set("blocked_domains", ["ads.example.test", "blocked.test"])
    store.set("blocklist_urls", ["http://lists.test/hosts.txt"])
    flags = proxy.apply_environment(store)   # as app.main does, before the engine starts
    check("the proxy switch is passed to the engine",
          f"--proxy-server=http://127.0.0.1:{port}" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""), flags)
    check("Pelagic's own requests use an HTTP proxy too", os.environ.get("HTTPS_PROXY") == f"http://127.0.0.1:{port}")
    hub = ProfileHub(app, store, Browser)
    win = hub.open_profile(DEFAULT_ID, ["http://shop.test/page"])
    win.resize(1100, 700)
    win.show()
    tab = win.current_tab()
    domains = win.ctx.domains
    check("downloaded blocklist (through the proxy) is used",
          wait_until(lambda: domains.match("tracker.example.test"), 15) and ("lists.test", "/hosts.txt") in SEEN,
          SEEN)
    tab.reload()
    wait_until(lambda: not tab.loading and tab.title() == "Shop", 15)
    pump(1500)
    hosts = {h for h, _p in SEEN}
    check("pages on made-up domains load through the proxy", tab.title() == "Shop" and "shop.test" in hosts,
          tab.title())
    check("allowed parts of the page load", "cdn.example.test" in hosts, hosts)
    check("blocked domains never reach the network", "ads.example.test" not in hosts
          and "tracker.example.test" not in hosts, hosts)
    check("blocked requests are counted for the page", win.ctx.blocker.counts.get("shop.test", 0) >= 2,
          win.ctx.blocker.counts)

    tab.load(QUrl("http://www.blocked.test/"))
    wait_until(lambda: not tab.loading and tab.title().startswith("Blocked"), 10)
    from atlasbrowser.tools import page_url
    check("a blocked site shows the blocked page", tab.title().startswith("Blocked"), tab.title())
    check("the address bar keeps the blocked address", page_url(tab).host() == "www.blocked.test")
    check("the blocked site wasn't contacted", "www.blocked.test" not in {h for h, _p in SEEN})
    tab.page().runJavaScript("document.querySelector('a.l').click()")
    wait_until(lambda: not tab.loading and tab.title() == "www.blocked.test", 10)
    check("Unblock opens the site and removes it from the list",
          tab.title() == "www.blocked.test" and "blocked.test" not in (store.get("blocked_domains") or []),
          tab.title())

    win.ctx.domains.add("shop.test")
    win.ctx.new_private_window()
    pwin = next(w for w in win.ctx.windows if w.private)
    ptab = pwin.current_tab()
    ptab.load(QUrl("http://shop.test/page"))
    wait_until(lambda: not ptab.loading and ptab.title().startswith("Blocked"), 10)
    check("blocked domains apply in private windows", ptab.title().startswith("Blocked"), ptab.title())
    pwin.close()

    from atlasbrowser.network_ui import BlocklistDialog, ConnectionPage
    page = ConnectionPage(store)
    check("Connection page shows the saved proxy", page.value()["host"] == "127.0.0.1"
          and page.value()["port"] == port and not page.problem())
    page.port.setValue(port + 1)
    check("changing the proxy asks for a restart", page.save())
    dlg = BlocklistDialog(store, win.ctx.domains, win)
    dlg.mine.setPlainText("one.test\n0.0.0.0 two.test\n")
    dlg._ok()
    check("the Blocked domains editor saves and applies at once",
          win.ctx.domains.match("a.two.test") and not win.ctx.domains.match("shop.test"))

    win.close()
    hub.stop_all()
    srv.shutdown()
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
