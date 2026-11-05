"""Certificate regression checks using only a local HTTPS server and real Qt pages.

Run: python tests/certificate_selftest.py  (add --visible to show the test tabs)
The embedded self-signed certificates and private keys are test-only fixtures.
"""
from __future__ import annotations

import os
import ssl
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
if "ignore-certificate-errors" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
    raise RuntimeError("Certificate checks require Chromium certificate validation enabled")

# Generated for localhost/127.0.0.1, valid 2020-2040. Never use these keys outside tests.
FIXTURES = [('-----BEGIN CERTIFICATE-----\nMIIC+DCCAeCgAwIBAgIUd7zptCRbsuRI6enHIZHIFfs43R4wDQYJKoZIhvcNAQEL\nBQAwHzEdMBsGA1UEAwwUQXRsYXMgdGVzdCBsb2NhbGhvc3QwHhcNMjAwMTAxMDAw\nMDAwWhcNNDAwMTAxMDAwMDAwWjAfMR0wGwYDVQQDDBRBdGxhcyB0ZXN0IGxvY2Fs\naG9zdDCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBANRIu8Kj5jtitHmq\nOIhCIoo5DADZ6mX8mJpa6XX2IJdZEKqOGoZogZbo5/sRpqLjNcfqclry42ACUoh1\nvH+mWjiHbCgxlRpRa/+Rdqj528cwua0PHg7MRiYgW+LpW4r6dpmCFDtUb5/2Td9r\nhaSO67OSJxWSPa+HkCAok7JpCqtOLg+uaApzJ/A0mfXYmCg8JCdMOblF8m2ENl4s\n/lJSZ48njv8SSUIlYC/Z19CXKgGG4FiE7vbLLMF5QY/B3eXOFhkJZcYFheIy/3md\nHNy3I/0qkXFz9TCkZBqwGzs8esbPJDsNchoaYHTWCZLHBBed4bqEJLawNA2aZpDm\nBDWeUd0CAwEAAaMsMCowGgYDVR0RBBMwEYIJbG9jYWxob3N0hwR/AAABMAwGA1Ud\nEwEB/wQCMAAwDQYJKoZIhvcNAQELBQADggEBABRfALPfkYTAcdujEsjh9ei70Jla\n6EIzK1IG+qAqqacxV7dNYP4FeOahvH5KS69OMqtlnbDqdW2WBTeJRoBJMaj7tOL6\nCBmpVIsNN2p4Zfj0js4SkqJATERPsoaGxj8oeoE+rW4AR2XCFVzL2Zfk33yzUdFR\nNjq2Is+9D3JsqagHLAx5wedVPx5ZolRDqhyHaR08S3tCpAzz6/Kb7Ce4wKAoLtW7\n49Yc0Q2uYpRELLoc8KWQlHVyc+5yiUFQlpzv0Nb5CpJSdKvDTjpgEuFKQ7/A0zlA\nXUM1w06i7shs6n5Z6AeEFwUUDCSFqbsJCxt+WTG084zEqnFd12D0fVLLnv8=\n-----END CERTIFICATE-----\n', '-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDUSLvCo+Y7YrR5\nqjiIQiKKOQwA2epl/JiaWul19iCXWRCqjhqGaIGW6Of7Eaai4zXH6nJa8uNgAlKI\ndbx/plo4h2woMZUaUWv/kXao+dvHMLmtDx4OzEYmIFvi6VuK+naZghQ7VG+f9k3f\na4WkjuuzkicVkj2vh5AgKJOyaQqrTi4PrmgKcyfwNJn12JgoPCQnTDm5RfJthDZe\nLP5SUmePJ47/EklCJWAv2dfQlyoBhuBYhO72yyzBeUGPwd3lzhYZCWXGBYXiMv95\nnRzctyP9KpFxc/UwpGQasBs7PHrGzyQ7DXIaGmB01gmSxwQXneG6hCS2sDQNmmaQ\n5gQ1nlHdAgMBAAECggEAJvnStXYzyaACDFuPRR9FabT3KfnYslB6MU7zUeP2kGs7\nJuFv59Esx+kr3JpdSsdmQrYeOGojiqdqgWECkrpXksz0c/3Eh0A/UL1juLslWdFt\nqeNebK+fSpVC4argUqhRWbZ7IfiLBSbrHdQHRdMy3fW95NVEq6N7eBgTJBzqp1Bd\npyGyUHlvrIa4EnZTuDHV+a7IXVGrosDkjURfj3DoVBeWV6YuCAkeENw3XvgYqeLJ\nbpuw8fPpr4fNKQzaP5JXhaeVvFo2U859sIa5sA91yNbrtykq65QImspdokceq2QO\n4tbkhk33z/fEmFn7xc0jpMQczUedEU6S4XnFQlMHuQKBgQD/qQqNUvZ438iDZ+8x\nN3dZVzXQdN8vtkJp57yjsJb9Xg+7ixsKv1p5Zt2jrCG66ameUQHRPdIdleOgDjqc\n5crEBHEHsYJRAvaJ2lrjOWtEAb+D4uqvHMOCrM+QG3ATyN7UF9+DPRdJjaC6ynfq\n3H6z8JIkTeVWF8CebGqfzUrXtQKBgQDUkPBBR/u8kcXXT0uhqOeuGJ1haL0joFZv\nPICqSlLFoKg06PPlEgZxiZ24edkD7hi/WSXoc5eJKfJSu2xjNPyJggcPSze5Lrl1\nApQq6MiZY8OA871m2NMYe5Leekg3AV6tjHWg17xnvA4Ryf5NlrFC6BTkP52v2myD\nasGd7FaaiQKBgCH4UBKfJ2jAM2BiewHLIOyaDeh43v7z9Lclt4b4e9eGnAiLXzh6\nXIctB94rjP/M9GC42sj2seiEdg5aVadrURnijTI8f9hL0H5YqSLwCjSrFstrZ0uF\nQuUmGR5IxweZ9SGxWl2RzHpVeznWlUB7s8os+P4h64sY9NsYBMLfAEbRAoGBALVu\nqMLvr/y558XpFsL7KhS9SceU4KuB9YSofaHcIl4wzKGsnFBPXFSYg5ir2AG0vkbE\nzshjsVoQBZd8Bf1/gnXUGDaDmyJisUUgWFtvqZjTQFHWuTkJpNRm1WszsGPStX8o\nPlZ1DYj1SIUChh6vmsli0kIn0m4A31IkUvJ6gUkRAoGBANWv2Hq94VB6j82dVfK/\nOmCs4PF/Tk4zxnQD2MD+qckiWJhhiGub9dSmzBnwQi2d3MiU9V34oCvA0V57nMUt\ngAP0AjoyjvOcsq5g5QNMhb79z5ttBO3q8WGjtmqs7qJhhnCsiYy+svMczuIKTD1k\nzVHb4zTQoGx8kyKvHULsz4Ky\n-----END PRIVATE KEY-----\n'), ('-----BEGIN CERTIFICATE-----\nMIIC+DCCAeCgAwIBAgIUQLzTLXUoCzJWYNOpU6KGBqvLJRMwDQYJKoZIhvcNAQEL\nBQAwHzEdMBsGA1UEAwwUQXRsYXMgdGVzdCBsb2NhbGhvc3QwHhcNMjAwMTAxMDAw\nMDAwWhcNNDAwMTAxMDAwMDAwWjAfMR0wGwYDVQQDDBRBdGxhcyB0ZXN0IGxvY2Fs\naG9zdDCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALRiVxtjgnEb46UX\nmW/TaptAmnW+x5VDJEvhvofNX2XfznSd/GFClfUMlRtxRVh9iEL5+4c4bmwSfNdo\nJrywbOu3zjxhv6uCaubw9tFULyubPdEphFDBVffqo87bKykphPcdH9vh/NDQq+sa\nhj3d3AyvOSY4rqw7KjSNTdUbnpvHhpi9HNItXCFTSuOrU+GN4Av+2mUidTUkiAMA\nIg1avoY2kWdM35t8/l7P0hPYv0z7AoqI2xzKwF1ukzZs2SkA1QXWIN+k9wcOE15z\nQCN5dWlpWpj3HZSt985iVNoi52SH2pHxkEMT/fiVbf9nsPxMu5JWzuCR3oVRcM0d\nK1SlOT8CAwEAAaMsMCowGgYDVR0RBBMwEYIJbG9jYWxob3N0hwR/AAABMAwGA1Ud\nEwEB/wQCMAAwDQYJKoZIhvcNAQELBQADggEBAKUi7NjpaYql0twL6xtUyXvAxL83\nesWk6WQyRW9CTwv7N/2WOvTNfmIMAhKEKS0N2bLvndKYKDNz5sSWJwz4mqWJUtwE\nqdrgee7OQKmhzDPIxRCTjLU6dz/B50bNechMBlUz0p5bfz00T2i4+z0tNZRxyiIR\nanBIFqsdcWlxjcCr5TA6FKuuq6P4SzDCqPciPhf2I9g3XwumeAZJRQc8RMmNSC6Z\nxxulVF83N6Tkk2Ukc5LMMvegCsjXL3n3C8QrQIKLdTQIi92y7vIn2Xz/2y6C1yIA\ntDrMVYyZZtmzXAGKChZFoTnz6LKMZd+ooJmCNrpGckU6I9cktqbpMvL8Urs=\n-----END CERTIFICATE-----\n', '-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC0YlcbY4JxG+Ol\nF5lv02qbQJp1vseVQyRL4b6HzV9l3850nfxhQpX1DJUbcUVYfYhC+fuHOG5sEnzX\naCa8sGzrt848Yb+rgmrm8PbRVC8rmz3RKYRQwVX36qPO2yspKYT3HR/b4fzQ0Kvr\nGoY93dwMrzkmOK6sOyo0jU3VG56bx4aYvRzSLVwhU0rjq1PhjeAL/tplInU1JIgD\nACINWr6GNpFnTN+bfP5ez9IT2L9M+wKKiNscysBdbpM2bNkpANUF1iDfpPcHDhNe\nc0AjeXVpaVqY9x2UrffOYlTaIudkh9qR8ZBDE/34lW3/Z7D8TLuSVs7gkd6FUXDN\nHStUpTk/AgMBAAECggEAE4qHvIwrfbdeEkIb5CpiD87lghXt0coD7O3X/Hw6IR4o\nDn1tnC0Lc7rY4wUtVFMdEixknEHNFzYVgicNSJRQPbpGxEcj7XTjwdWe12R9oQVg\noqpoZBszBfghphobczUalhlN8ehpwUap09P8G52k5gGMI7Yw7gWRd+n1jD2WvByo\nczQu7RNT0Ox1Vmtj+88P3IWz4nauIjKY8h6uXMMHNc+2wDEKqsNkyZyC6SMXgaT+\nqkZFXvhFNleFTWISTf5tpufH228r9H2EAVJt+p9Y2sSkLIBM512Z1ADblN5DFBUY\njPQIAX5QGuVf/kCH2nz9RkjsmZIjRjwtNRxXBAS5EQKBgQDa6a0Ks70+PvlBf+4l\nRaqghbsSA+am46Q9HrkKFzT38fiVGBeU4gOaZ7FX03v9Lsg96EpnGxfnjjtPpec/\nqjCB/uB3STkAdOYJDi1UGfhObdS/XF7A//v3I14TgzJSVYw+TowmseWreXzGQRf9\nUlj+oD6ML1qkUIl/Ti4zD6JYFwKBgQDS8anE+z+J2Esr3ZCZjMQFkfaal5a5BkUO\nWTQMsggpOkSfwHlTk+la16ppdgdTW3FdnkemEg7P9xDmxEOBJE5DhbAgiQf45A0f\nhYPiBexJmzcun/ElXS8OkIyhMRWgt4YZNu9lWns/nlp0AGYaIMsDWFkiEOAIWTgt\nELt/mC65GQKBgQDDBC7KfOqWnCUSy7PMcm6Zh+jqGJ2OiPcUF92B9sCSLXZk48yG\nLn5FPCDJe7ZWCyoJtHkrtwApoRSHVOVYWvXRqMwwmAN2u6z93ipVZLlGrSM8wj4L\nM0A0nsY9HcBjhqBkFTdXdV2Dz7tvJigH3Sc41mpCGiFmhfSne28+v6vBSwKBgQC5\nG4Qk7W2WYw2kEqwfcp1ZXfsPMdL7znqu2qyIL3pl41Hw9hABvZxbMUHDheVryqSy\nyICLRPFmoaJdPwEVxGxBaIFkK5upV0YE0T8oCpaNCP3llkkgxqLSnxopIU+fVyz/\n12tAf6QD8cviW689YmWEK/Ubpb9S1Cgts681irAFkQKBgH6c6b7pl6RUEkc/b/W/\nDqoFIIs1xK0S2Qlt/g2BVnZcZr9gYFYHrmIcLuKeTmTMZGorH3S9/DnIN+JMPR2i\n9e8/yDHnKCUy2biuxngAzO0SPs1qcU14JaUeNhiWKr6en1A4LTSLPK8EydphF7qE\n7SjnIJlM8K/PlisLSCrZsPLo\n-----END PRIVATE KEY-----\n')]

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtNetwork import QSslCertificate  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineCertificateError  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from atlasbrowser.webview import BrowserTab, make_profile  # noqa: E402

RESULTS = []


def check(name, condition):
    RESULTS.append((name, bool(condition)))
    print(("PASS " if condition else "FAIL ") + name, flush=True)


def pump(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(condition, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        pump()
    return bool(condition())


def warning(tab):
    return next((d for d in tab.findChildren(QMessageBox) if d.isVisible()), None)


def trust(dialog):
    button = next(b for b in dialog.buttons() if dialog.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole)
    button.click()


class Site(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # Close every connection so certificate rotation gets a new handshake.

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = f"<title>Certificate test {self.server.generation}</title><h1>Local TLS page</h1>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass  # Rejected or stopped navigations can close their socket.


class TLSLocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, fixture_dir):
        super().__init__(("127.0.0.1", 0), Site)
        self.fixture_dir = fixture_dir
        self.rotate(0)

    def rotate(self, index):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.fixture_dir / f"cert{index}.pem"),
                                str(self.fixture_dir / f"key{index}.pem"))
        # A fresh context prevents TLS session resumption hiding a changed certificate.
        self.tls_context = context
        self.generation = index + 1

    def get_request(self):
        sock, address = self.socket.accept()
        sock.settimeout(5)
        try:
            return self.tls_context.wrap_socket(sock, server_side=True), address
        except Exception:
            sock.close()
            raise


class RejectedError:
    """Minimal error stand-in for branches that must reject before copying/defer()."""

    def __init__(self, url, chain, overridable=True, main_frame=True):
        self._url, self._chain = QUrl(url), chain
        self._overridable, self._main_frame = overridable, main_frame
        self.rejected = self.accepted = False

    def url(self):
        return self._url

    def certificateChain(self):
        return self._chain

    def isOverridable(self):
        return self._overridable

    def isMainFrame(self):
        return self._main_frame

    def type(self):
        return QWebEngineCertificateError.Type.CertificateAuthorityInvalid

    def rejectCertificate(self):
        self.rejected = True

    def acceptCertificate(self):
        self.accepted = True


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    tabs, profiles = [], []
    with tempfile.TemporaryDirectory(prefix="atlas_cert_test_") as temp:
        root = Path(temp)
        for index, (cert, key) in enumerate(FIXTURES):
            (root / f"cert{index}.pem").write_text(cert, encoding="ascii")
            (root / f"key{index}.pem").write_text(key, encoding="ascii")
        server = TLSLocalServer(root)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f"https://127.0.0.1:{server.server_port}"

        def new_tab(profile=None):
            if profile is None:
                profile = make_profile("certificate-selftest", str(root / "regular"), app)
                profiles.append(profile)
            tab = BrowserTab(profile)
            tab.resize(700, 500)
            tab.show()
            tabs.append(tab)
            return tab

        def open_warning(tab, suffix):
            tab.load(QUrl(origin + suffix))
            if not wait_until(lambda: warning(tab) is not None):
                raise AssertionError(f"No certificate warning for {suffix}; title={tab.title()!r}")
            return warning(tab)

        try:
            tab = new_tab()
            profile = profiles[0]
            errors = []
            tab.page().certificateError.connect(lambda error: errors.append(error.type()))
            finished = []
            tab.loadFinished.connect(finished.append)
            dialog = open_warning(tab, "/cancel")
            check("real self-signed HTTPS request produces a certificate warning", bool(errors))
            cancel = dialog.button(QMessageBox.StandardButton.Cancel)
            check("Cancel is the default and Escape action",
                  dialog.defaultButton() is cancel and dialog.escapeButton() is cancel)
            check("warning identifies the origin and certificate fingerprint",
                  origin in dialog.text() and "Certificate SHA-256:" in dialog.detailedText())
            cancel.click()
            check("Cancel rejects the load", wait_until(lambda: finished and finished[-1] is False))
            check("Cancel stores no trust", not profile._certificate_exceptions)

            finished.clear()
            dialog = open_warning(tab, "/trust")
            trust(dialog)
            check("Trust loads the actual HTTPS page", wait_until(lambda: tab.title() == "Certificate test 1"
                                                                  and finished and finished[-1] is True))
            check("Trust stores one certificate exception", len(profile._certificate_exceptions) == 1)
            finished.clear()
            tab.load(QUrl(origin + "/repeat"))
            check("same certificate loads again without a prompt",
                  wait_until(lambda: finished and finished[-1] is True and tab.url().path() == "/repeat")
                  and tab.title() == "Certificate test 1" and warning(tab) is None)

            other = new_tab(profile)
            other.load(QUrl(origin + "/same-profile"))
            check("a second tab in the same profile shares session trust",
                  wait_until(lambda: other.title() == "Certificate test 1" and not other.loading)
                  and warning(other) is None)

            private_profile = make_profile(None, None, app)
            profiles.append(private_profile)
            private = new_tab(private_profile)
            dialog = open_warning(private, "/private")
            check("private profile asks separately", not private_profile._certificate_exceptions)
            private.stop()
            check("Stop rejects and closes a deferred warning",
                  wait_until(lambda: not private.page()._pending_certificates and warning(private) is None)
                  and not private_profile._certificate_exceptions)

            dialog = open_warning(private, "/navigate")
            stale_trust = next(b for b in dialog.buttons()
                               if dialog.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole)
            private.load(QUrl("about:blank"))
            stale_trust.click()
            check("another navigation closes the old warning without granting trust",
                  wait_until(lambda: private.url().toString() == "about:blank"
                             and not private.page()._pending_certificates and warning(private) is None)
                  and not private_profile._certificate_exceptions)
            check("a stale Trust click after navigation cannot grant trust",
                  not private_profile._certificate_exceptions)
            private.stop()  # Isolate later checks if the navigation regression fails.

            server.rotate(1)
            dialog = open_warning(tab, "/changed-certificate")
            check("changed certificate at the same origin asks again", len(profile._certificate_exceptions) == 1)
            trust(dialog)
            check("explicit trust loads the replacement certificate",
                  wait_until(lambda: tab.title() == "Certificate test 2" and not tab.loading)
                  and len(profile._certificate_exceptions) == 2)

            # Use another host on the same loopback server to test origin isolation.
            tab.load(QUrl(f"https://localhost:{server.server_port}/other-host"))
            check("same certificate on another host still asks",
                  wait_until(lambda: warning(tab) is not None))
            tab.stop()

            cert = QSslCertificate(FIXTURES[0][0].encode("ascii"))
            for label, fake in (
                ("non-overridable errors stay rejected", RejectedError(origin, [cert], overridable=False)),
                ("missing certificate chain stays rejected", RejectedError(origin, [])),
                ("untrusted subresources stay rejected", RejectedError(origin + "/resource", [cert], main_frame=False)),
                ("non-HTTPS errors stay rejected", RejectedError("http://127.0.0.1/", [cert])),
            ):
                # A non-overridable error must reject even a previously trusted certificate.
                # A clean profile keeps subresource rejection independent of session trust.
                page = tab.page() if not fake.isOverridable() else private.page()
                page._on_certificate_error(fake)
                check(label, fake.rejected and not fake.accepted and not page._pending_certificates)
        finally:
            for tab in tabs:
                tab.stop()
                tab.close()
                tab.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pump()
            for profile in profiles:
                profile.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pump()
            server.shutdown()
            server.server_close()
    failed = [name for name, passed in RESULTS if not passed]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} certificate checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
