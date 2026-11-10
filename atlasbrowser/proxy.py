"""Proxy and VPN connection (Settings → Connection), shared by every profile.

Pelagic can send its browsing through a proxy server: an HTTP/HTTPS proxy, a SOCKS5 or SOCKS4 proxy (what most VPN
services offer for use in one app: Mullvad, NordVPN, Proton VPN, Private Internet Access, Windscribe and others, and
Tor on 127.0.0.1:9050), or a PAC script address. A VPN app installed on the computer (WireGuard, OpenVPN, the VPN
service's own app) already covers Pelagic with the "system" setting; Pelagic can't start a VPN tunnel itself.

The browser engine reads the proxy once, when it starts, so a change takes effect after Pelagic restarts. Chromium
resolves host names through SOCKS5 proxies, so DNS lookups go through the proxy too.

Settings: "proxy" = {"mode": "system" | "direct" | "manual" | "pac", "scheme": "http" | "https" | "socks5" |
"socks4", "host", "port", "user", "bypass", "pac", "webrtc_private"}. A password is kept encrypted with the API
keys (store.set_key(KEY_NAME, ...)).
"""
from __future__ import annotations

import os
import re
import socket

KEY_NAME = "pelagic-proxy-password"
SCHEMES = {"http": "HTTP", "https": "HTTPS", "socks5": "SOCKS5", "socks4": "SOCKS4"}
MODES = {
    "system": "Use the computer's settings (and any VPN app)",
    "direct": "No proxy: connect directly",
    "manual": "Use this proxy server",
    "pac": "Use a proxy auto-configuration (PAC) address",
}
DEFAULT = {"mode": "system", "scheme": "socks5", "host": "", "port": 1080, "user": "",
           "bypass": "localhost, 127.0.0.1, <local>", "pac": "", "webrtc_private": True}
_HOST = re.compile(r"^[A-Za-z0-9._-]+$|^\[[0-9A-Fa-f:.]+\]$")
_started_with: dict | None = None   # the settings the engine was started with, to tell when a restart is needed


def config(store) -> dict:
    return {**DEFAULT, **(store.get("proxy") or {})}


def problem(cfg: dict) -> str | None:
    """What's wrong with cfg, or None when it can be used."""
    mode = cfg.get("mode")
    if mode not in MODES:
        return "Choose how to connect."
    if mode == "manual":
        host = str(cfg.get("host") or "").strip()
        if not host or not _HOST.match(host):
            return "Enter the proxy server's address, for example 127.0.0.1 or proxy.example.com."
        try:
            port = int(cfg.get("port"))
        except (TypeError, ValueError):
            return "Enter the proxy server's port."
        if not 0 < port < 65536:
            return "The port must be between 1 and 65535."
        if cfg.get("scheme") not in SCHEMES:
            return "Choose the type of proxy."
    if mode == "pac":
        pac = str(cfg.get("pac") or "").strip()
        if not re.match(r"^(https?|file|data):", pac, re.I) or any(c.isspace() for c in pac):
            return "Enter the PAC script's address, starting with http://, https:// or file://."
    return None


def server(cfg: dict) -> str:
    return f"{cfg['scheme']}://{str(cfg['host']).strip()}:{int(cfg['port'])}"


def _bypass(cfg: dict) -> str:
    items = [x.strip() for x in re.split(r"[,;\s]+", str(cfg.get("bypass") or "")) if x.strip()]
    return ";".join(x for x in items if re.match(r"^[A-Za-z0-9.*_:<>\[\]/-]+$", x))


def chromium_flags(cfg: dict) -> list[str]:
    """Command-line switches for the browser engine (empty for the computer's own settings or a bad config)."""
    mode = cfg.get("mode")
    if mode == "system" or problem(cfg):
        return []
    if mode == "direct":
        return ["--no-proxy-server"]
    if mode == "pac":
        return [f"--proxy-pac-url={str(cfg['pac']).strip()}"] + _webrtc(cfg)
    flags = [f"--proxy-server={server(cfg)}"]
    bypass = _bypass(cfg)
    if bypass:
        flags.append(f"--proxy-bypass-list={bypass}")
    return flags + _webrtc(cfg)


def _webrtc(cfg: dict) -> list[str]:
    # WebRTC (video calls) can otherwise reach out over UDP around the proxy and show your real address
    return ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"] if cfg.get("webrtc_private", True) else []


def uses_proxy(cfg: dict) -> bool:
    return cfg.get("mode") in ("manual", "pac") and not problem(cfg)


def apply_environment(store) -> list[str]:
    """Call before the browser engine starts. Adds the switches to QTWEBENGINE_CHROMIUM_FLAGS and, for HTTP(S)
    proxies, sets the proxy for Pelagic's own requests (AI providers, filter lists) too. Returns the switches."""
    global _started_with
    cfg = config(store)
    _started_with = dict(cfg)
    flags = chromium_flags(cfg)
    if flags:
        old = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        kept = " ".join(f for f in old.split() if not f.startswith(("--proxy-", "--no-proxy-server",
                                                                  "--force-webrtc-ip-handling-policy")))
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(filter(None, [kept, *flags]))
    if cfg.get("mode") == "manual" and not problem(cfg) and cfg["scheme"] in ("http", "https"):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[name] = server(cfg)
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = ",".join(
            x for x in _bypass(cfg).split(";") if x and x != "<local>")
    elif cfg.get("mode") == "direct":
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
    return flags


def needs_restart(store) -> bool:
    if _started_with is None:
        return False
    now, then = config(store), _started_with
    keys = ("mode", "scheme", "host", "port", "bypass", "pac")
    return any(str(now.get(k)) != str(then.get(k)) for k in keys)


def test_connection(cfg: dict, timeout: float = 6) -> str:
    """Runs off the UI thread: can Pelagic reach the proxy server? Returns a sentence for the user."""
    err = problem(cfg)
    if err:
        return err
    if cfg["mode"] != "manual":
        return "Nothing to test: this setting doesn't use a proxy server of its own."
    host, port = str(cfg["host"]).strip().strip("[]"), int(cfg["port"])
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            if cfg["scheme"] == "socks5":   # greeting: version 5, offering "no auth" and "user/password"
                s.settimeout(timeout)
                s.sendall(b"\x05\x02\x00\x02")
                reply = s.recv(2)
                if len(reply) < 2 or reply[0] != 5:
                    return f"{host}:{port} answered, but it doesn't look like a SOCKS5 proxy."
                if reply[1] == 0xFF:
                    return f"{host}:{port} is a SOCKS5 proxy, but it refused the sign-in methods Pelagic offers."
                if reply[1] == 2:
                    return (f"{host}:{port} is a SOCKS5 proxy that wants a user name and password. The browser "
                            "engine can't send those to SOCKS5 proxies; use the VPN service's HTTP proxy, or one "
                            "that checks your IP address instead.")
                return f"Connected: {host}:{port} is a working SOCKS5 proxy."
    except OSError as e:
        return f"Couldn't reach {host}:{port}: {getattr(e, 'strerror', None) or e}."
    return f"Connected to {host}:{port}."


def credentials(store) -> tuple[str, str]:
    cfg = config(store)
    try:
        pw = store.get_key(KEY_NAME)
    except Exception:   # keyring missing on Linux: prompt instead
        pw = ""
    return str(cfg.get("user") or ""), pw


def answer_auth(page, url, auth, proxy_host: str, store, parent=None):
    """QWebEnginePage.proxyAuthenticationRequired: the saved user name and password once, then ask."""
    user, pw = credentials(store)
    tried = getattr(page, "_proxy_auth_tried", set())
    page._proxy_auth_tried = tried
    if user and pw and proxy_host not in tried:
        tried.add(proxy_host)
        auth.setUser(user)
        auth.setPassword(pw)
        return
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit
    dlg = QDialog(parent)
    dlg.setWindowTitle("Proxy sign-in")
    f = QFormLayout(dlg)
    lab = QLabel(f"The proxy server {proxy_host} needs a user name and password.")
    lab.setWordWrap(True)
    f.addRow(lab)
    u, p = QLineEdit(user), QLineEdit()
    p.setEchoMode(QLineEdit.Password)
    f.addRow("User name", u)
    f.addRow("Password", p)
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    f.addRow(b)
    if dlg.exec():
        auth.setUser(u.text())
        auth.setPassword(p.text())
    # cancelled: leaving auth empty makes the page fail with a proxy error
