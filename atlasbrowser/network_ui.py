"""Settings → Connection (proxy / VPN) and the Blocked domains editor (Settings → Privacy)."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from . import blocklist, proxy, secretbox


def _note(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setObjectName("muted")
    return lab


class ConnectionPage(QWidget):
    """Proxy / VPN settings. save() is called by the Settings dialog's OK button."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        cfg = proxy.config(store)
        v = QVBoxLayout(self)
        v.addWidget(_note("Send Pelagic's browsing through a proxy server or a VPN service's proxy (SOCKS5 or "
                          "HTTP). A VPN app on this computer already covers Pelagic with the first choice. This "
                          "applies to every profile and takes effect when Pelagic restarts."))
        self.mode = QComboBox()
        for k, text in proxy.MODES.items():
            self.mode.addItem(text, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(cfg["mode"])))
        v.addWidget(self.mode)

        self.manual = QWidget()
        f = QFormLayout(self.manual)
        f.setContentsMargins(0, 0, 0, 0)
        self.scheme = QComboBox()
        for k, text in proxy.SCHEMES.items():
            self.scheme.addItem(text, k)
        self.scheme.setCurrentIndex(max(0, self.scheme.findData(cfg["scheme"])))
        self.host = QLineEdit(str(cfg["host"]))
        self.host.setPlaceholderText("127.0.0.1 or proxy.example.com")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(cfg["port"] or 1080))
        row = QHBoxLayout()
        row.addWidget(self.scheme)
        row.addWidget(self.host, 1)
        row.addWidget(QLabel("Port"))
        row.addWidget(self.port)
        f.addRow("Server", row)
        self.user = QLineEdit(str(cfg.get("user") or ""))
        self.user.setPlaceholderText("only if the proxy asks for one")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        try:
            has_pw = bool(store.get_key(proxy.KEY_NAME))
        except Exception:
            has_pw = False
        self.password.setPlaceholderText("saved (type to change)" if has_pw else "")
        f.addRow("User name", self.user)
        f.addRow("Password", self.password)
        self.bypass = QLineEdit(str(cfg.get("bypass") or ""))
        f.addRow("Don't use the proxy for", self.bypass)
        f.addRow("", _note("User names and passwords work with HTTP and HTTPS proxies. The browser engine can't "
                           "sign in to SOCKS5 proxies, so use one that checks your IP address (most VPN services' "
                           "SOCKS5 proxies only work while you're connected to them), or their HTTP proxy."))
        v.addWidget(self.manual)

        self.pac_box = QWidget()
        pf = QFormLayout(self.pac_box)
        pf.setContentsMargins(0, 0, 0, 0)
        self.pac = QLineEdit(str(cfg.get("pac") or ""))
        self.pac.setPlaceholderText("http://wpad.example.com/proxy.pac")
        pf.addRow("PAC address", self.pac)
        v.addWidget(self.pac_box)

        self.webrtc = QCheckBox("Keep video calls (WebRTC) from going around the proxy and showing my real address")
        self.webrtc.setChecked(cfg.get("webrtc_private", True) is not False)
        v.addWidget(self.webrtc)
        self.result = _note("")
        test = QPushButton("Test proxy")
        test.clicked.connect(self._test)
        tr = QHBoxLayout()
        tr.addWidget(test)
        tr.addWidget(self.result, 1)
        v.addLayout(tr)
        v.addWidget(_note("Tip: for Tor, run Tor and use SOCKS5, 127.0.0.1, port 9050. With a SOCKS proxy, Pelagic's "
                          "AI assistant and list downloads still connect directly; with an HTTP proxy they use it "
                          "too. To check, open a page such as https://ifconfig.me after restarting."))
        v.addStretch(1)
        self.mode.currentIndexChanged.connect(self._show)
        self._show()

    def _show(self):
        m = self.mode.currentData()
        self.manual.setVisible(m == "manual")
        self.pac_box.setVisible(m == "pac")
        self.webrtc.setVisible(m in ("manual", "pac"))

    def value(self) -> dict:
        return {"mode": self.mode.currentData(), "scheme": self.scheme.currentData(), "host": self.host.text().strip(),
                "port": self.port.value(), "user": self.user.text().strip(), "bypass": self.bypass.text().strip(),
                "pac": self.pac.text().strip(), "webrtc_private": self.webrtc.isChecked()}

    def _test(self):
        from .agent import run_in_pool
        self.result.setText("Testing…")
        run_in_pool(0, lambda: proxy.test_connection(self.value()),
                    lambda _t, out: self.result.setText(str(out)))

    def problem(self) -> str | None:
        return proxy.problem(self.value())

    def save(self) -> bool:
        """Saves; True when Pelagic must restart for the change to take effect."""
        cfg = self.value()
        self.store.set("proxy", cfg)
        if self.password.text():
            try:
                self.store.set_key(proxy.KEY_NAME, self.password.text())
            except secretbox.KeyringMissing as e:
                QMessageBox.warning(self, "Proxy password not saved", str(e))
        elif cfg["mode"] != "manual" or not cfg["user"]:
            try:
                self.store.set_key(proxy.KEY_NAME, "")
            except Exception:
                pass
        return proxy.needs_restart(self.store)


class BlocklistDialog(QDialog):
    """Pi-hole style blocked domains: your own list, downloaded lists, and domains never to block."""

    def __init__(self, store, domains: blocklist.DomainBlocker | None, parent=None):
        super().__init__(parent)
        self.store, self.domains = store, domains
        self.setWindowTitle("Blocked domains")
        self.resize(640, 520)
        self.enabled = QCheckBox("Block these domains and all their subdomains, everywhere in this profile")
        self.enabled.setChecked(store.get("domain_block") is not False)
        tabs = QTabWidget()

        self.mine = QPlainTextEdit("\n".join(store.get("blocked_domains") or []))
        self.mine.setPlaceholderText("example.com\nads.example.net\n0.0.0.0 tracker.example.org")
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.addWidget(_note("One domain per line. Blocking example.com also blocks www.example.com and every other "
                           "subdomain. Hosts-file lines (0.0.0.0 example.com) and # comments are fine."))
        l1.addWidget(self.mine, 1)
        tabs.addTab(w1, "My blocked domains")

        self.urls = QPlainTextEdit("\n".join(store.get("blocklist_urls") or []))
        self.urls.setPlaceholderText("https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts")
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.addWidget(_note("Addresses of blocklists to download, one per line: hosts files or plain domain lists, "
                           "like the ones Pi-hole uses. They're refreshed every few days."))
        add = QComboBox()
        add.addItem("Add a well-known list…", "")
        for name, url in blocklist.SUGGESTED_LISTS.items():
            add.addItem(name, url)
        add.activated.connect(lambda i: self._add_url(add.itemData(i)) or add.setCurrentIndex(0))
        l2.addWidget(add)
        l2.addWidget(self.urls, 1)
        self.status = _note("")
        upd = QPushButton("Update lists now")
        upd.clicked.connect(self._update)
        ur = QHBoxLayout()
        ur.addWidget(self.status, 1)
        ur.addWidget(upd)
        l2.addLayout(ur)
        tabs.addTab(w2, "Blocklists")

        self.allowed = QPlainTextEdit("\n".join(store.get("allowed_domains") or []))
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        l3.addWidget(_note("Never blocked, even when a downloaded list has them (and their subdomains)."))
        l3.addWidget(self.allowed, 1)
        tabs.addTab(w3, "Never block")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.enabled)
        lay.addWidget(tabs, 1)
        lay.addWidget(_note("Blocked domains work in private windows too, and whether or not the ad blocker is on."))
        lay.addWidget(buttons)
        if domains is not None:
            domains.lists.ready.connect(self._show_status)
        self._show_status()

    def _add_url(self, url: str):
        if url and url not in self.urls.toPlainText().split():
            text = self.urls.toPlainText().rstrip()
            self.urls.setPlainText((text + "\n" if text else "") + url)

    def _show_status(self):
        if self.domains is None:
            return
        try:
            mine, listed = self.domains.counts()
        except RuntimeError:
            return
        errs = self.domains.lists.errors
        text = f"{mine:,} of your own domains and {listed:,} from lists are blocked."
        if errs:
            text += " Couldn't download: " + ", ".join(errs)
        self.status.setText(text)

    def _lines(self, edit: QPlainTextEdit) -> list[str]:
        return [x.strip() for x in edit.toPlainText().splitlines() if x.strip()]

    def _save(self):
        self.store.set("domain_block", self.enabled.isChecked())
        self.store.set("blocked_domains", self._lines(self.mine))
        self.store.set("allowed_domains", self._lines(self.allowed))
        self.store.set("blocklist_urls", [u for u in self._lines(self.urls) if u.lower().startswith(("http://", "https://"))])

    def _update(self):
        self._save()
        if self.domains is not None:
            self.status.setText("Updating blocklists…")
            self.domains.update_lists(force=True)

    def _ok(self):
        bad = [x for x in self._lines(self.mine) if not x.startswith(("#", "!")) and not blocklist.parse_domain(x)]
        if bad and QMessageBox.question(self, "Blocked domains", "These lines aren't domains and will be ignored:\n"
                                        + "\n".join(bad[:10]) + "\n\nSave anyway?") != QMessageBox.Yes:
            return
        before = list(self.store.get("blocklist_urls") or [])
        self._save()
        if self.domains is not None:
            if before != list(self.store.get("blocklist_urls") or []):
                self.domains.update_lists()
            else:
                self.domains.refresh()
        self.accept()
