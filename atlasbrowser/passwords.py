"""Saved passwords: an encrypted store (DPAPI, like API keys), save/update prompts, autofill and import from Google.

Passwords stay on the Python side until the user picks an account to fill; page scripts only ever see what is
filled into the form, and the AI agent never reads password fields (see pagejs) or receives anything from here.
"""
from __future__ import annotations

import base64
import csv
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, QPoint, QTimer, QUrl, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from .store import _dpapi

_APP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
GOOGLE_EXPORT_URL = "https://passwords.google.com/options?ep=1"


def origin_of(url: str | QUrl) -> str:
    """scheme://host[:port], lower-case; '' for anything that is not http(s)."""
    u = url if isinstance(url, QUrl) else QUrl(url.strip() if "://" in url else "https://" + url.strip())
    if u.scheme() not in ("http", "https") or not u.host():
        return ""
    default = 443 if u.scheme() == "https" else 80
    port = u.port(default)
    return f"{u.scheme()}://{u.host().lower()}" + ("" if port == default else f":{port}")


def _host(origin: str) -> str:
    return QUrl(origin).host()


def display_site(origin: str) -> str:
    host = _host(origin)
    return host[4:] if host.startswith("www.") else host


def _matches(saved: str, page: str) -> bool:
    """Same site: identical origin, www/non-www twins, or a saved http login used on the https page."""
    if saved == page:
        return True
    s, p = QUrl(saved), QUrl(page)
    if s.port(-1) != p.port(-1) and not (s.port(-1) in (-1, 80, 443) and p.port(-1) in (-1, 80, 443)):
        return False
    if s.scheme() == "https" and p.scheme() == "http":
        return False   # never hand an https password to a plain-http page
    strip = lambda h: h[4:] if h.startswith("www.") else h
    return strip(s.host().lower()) == strip(p.host().lower())


class PasswordStore:
    """Logins in passwords.dat, encrypted with the Windows account (DPAPI). Plain JSON off Windows (tests only)."""

    def __init__(self, root: Path):
        self.path = Path(root) / "passwords.dat"
        self._lock = threading.RLock()
        self._data: dict | None = None

    # -- persistence
    def _load(self) -> dict:
        if self._data is None:
            self._data = {"logins": [], "never": []}
            try:
                raw = base64.b64decode(self.path.read_text())
                plain = _dpapi(raw, False) if sys.platform == "win32" else raw
                self._data.update(json.loads(plain.decode("utf-8")))
            except FileNotFoundError:
                pass
            except Exception:
                # Never overwrite a file we could not read (e.g. copied from another Windows account).
                self._data["unreadable"] = True
        return self._data

    def _save(self):
        data = self._load()
        if data.get("unreadable"):
            raise RuntimeError("The saved passwords file could not be decrypted, so it was left untouched.")
        plain = json.dumps({"logins": data["logins"], "never": data["never"]}).encode("utf-8")
        raw = _dpapi(plain, True) if sys.platform == "win32" else plain
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(base64.b64encode(raw).decode("ascii"))
        os.replace(tmp, self.path)

    # -- queries
    def logins(self) -> list[dict]:
        with self._lock:
            return sorted((dict(x) for x in self._load()["logins"]),
                          key=lambda x: (display_site(x["origin"]), x["username"].lower()))

    def for_origin(self, origin: str) -> list[dict]:
        if not origin:
            return []
        with self._lock:
            found = [dict(x) for x in self._load()["logins"] if _matches(x["origin"], origin)]
        return sorted(found, key=lambda x: (x["origin"] != origin, -x.get("last_used", 0)))

    def get(self, login_id: str) -> dict | None:
        with self._lock:
            return next((dict(x) for x in self._load()["logins"] if x["id"] == login_id), None)

    def find(self, origin: str, username: str) -> dict | None:
        return next((x for x in self.for_origin(origin) if x["username"] == username), None)

    # -- changes
    def add(self, origin: str, username: str, password: str, note: str = "") -> dict:
        now = time.time()
        entry = {"id": uuid.uuid4().hex, "origin": origin, "username": username, "password": password,
                 "note": note, "created": now, "updated": now, "last_used": now}
        with self._lock:
            self._load()["logins"].append(entry)
            self._save()
        return dict(entry)

    def update(self, login_id: str, **fields):
        with self._lock:
            for x in self._load()["logins"]:
                if x["id"] == login_id:
                    x.update({k: v for k, v in fields.items() if k in ("origin", "username", "password", "note")})
                    x["updated"] = time.time()
                    self._save()
                    return

    def touch(self, login_id: str):
        with self._lock:
            for x in self._load()["logins"]:
                if x["id"] == login_id:
                    x["last_used"] = time.time()
                    self._save()
                    return

    def delete(self, login_id: str):
        with self._lock:
            data = self._load()
            data["logins"] = [x for x in data["logins"] if x["id"] != login_id]
            self._save()

    def is_never(self, origin: str) -> bool:
        with self._lock:
            return any(_matches(n, origin) for n in self._load()["never"])

    def never_sites(self) -> list[str]:
        with self._lock:
            return list(self._load()["never"])

    def add_never(self, origin: str):
        with self._lock:
            if origin not in self._load()["never"]:
                self._load()["never"].append(origin)
                self._save()

    def remove_never(self, origin: str):
        with self._lock:
            data = self._load()
            data["never"] = [n for n in data["never"] if n != origin]
            self._save()

    def import_csv(self, path: str | Path) -> tuple[int, int, int]:
        """Google Password Manager / Chrome export (name,url,username,password,note); Firefox/Edge CSVs work too.
        Returns (added, updated, skipped)."""
        added = updated = skipped = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        with self._lock:
            for row in rows:
                row = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
                origin = origin_of(row.get("url") or row.get("origin") or row.get("website") or "")
                username = row.get("username") or row.get("login") or ""
                password = row.get("password") or ""
                if not origin or not password:
                    skipped += 1
                    continue
                same = next((x for x in self._load()["logins"]
                             if x["origin"] == origin and x["username"] == username), None)
                if same is None:
                    self._load()["logins"].append({
                        "id": uuid.uuid4().hex, "origin": origin, "username": username, "password": password,
                        "note": row.get("note") or row.get("notes") or "", "created": time.time(),
                        "updated": time.time(), "last_used": 0})
                    added += 1
                elif same["password"] != password:
                    same["password"], same["updated"] = password, time.time()
                    updated += 1
                else:
                    skipped += 1
            if added or updated:
                self._save()
        return added, updated, skipped


# ---------------------------------------------------------------- page side
_PAGE_JS = r"""
(function () {
  if (window.__wfPw) return;
  window.__wfPw = true;
  var bridge = null, lastSent = '';
  function visible(el) { var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.disabled; }
  function isPw(el) { return el && el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'password'; }
  function isUser(el) {
    if (!el || el.tagName !== 'INPUT') return false;
    var t = (el.type || 'text').toLowerCase(), ac = (el.autocomplete || '').toLowerCase();
    return ac.indexOf('username') >= 0 || t === 'email' || ((t === 'text' || t === 'tel') && ac !== 'off' &&
      /user|login|mail|account|ident|phone|name/i.test((el.name || '') + ' ' + (el.id || '') + ' ' + (el.placeholder || '') + ' ' + (el.getAttribute('aria-label') || '')));
  }
  function scope(el) { return (el && el.form) || document; }
  function fields(from) {
    var root = scope(from), inputs = Array.prototype.slice.call(root.querySelectorAll('input')).filter(visible);
    var pw = inputs.filter(isPw), pwField = isPw(from) ? from : pw[0] || null, user = null;
    var limit = pwField ? inputs.indexOf(pwField) : inputs.length;
    for (var i = limit - 1; i >= 0; i--) { if (isUser(inputs[i])) { user = inputs[i]; break; } }
    if (!user) for (var j = limit - 1; j >= 0; j--) {
      var t = (inputs[j].type || 'text').toLowerCase();
      if (t === 'text' || t === 'email' || t === 'tel') { user = inputs[j]; break; }
    }
    return { user: user, pw: pwField, newPassword: pw.length > 1 };
  }
  function setValue(el, v) {
    var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    el.focus(); setter.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  window.__wfFill = function (u, p) {
    var a = document.activeElement, f = fields(isPw(a) || isUser(a) ? a : null);
    if (f.user && u) setValue(f.user, u);
    if (f.pw && p) setValue(f.pw, p);
    if (f.pw) f.pw.blur();
  };
  function capture(from) {
    if (!bridge) return;
    var f = fields(from);
    if (f.pw && f.pw.value) {
      var u = f.user ? f.user.value : '', key = u + '\u0000' + f.pw.value;
      if (key === lastSent) return;
      lastSent = key;
      bridge.submitted(u, f.pw.value, f.newPassword);
    } else if (f.user && f.user.value && !f.pw) {
      bridge.usernameSeen(f.user.value);      // first step of a two-page login (username, then password)
    }
  }
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!bridge || !e.isTrusted || !(isPw(el) || (isUser(el) && fields(el).pw))) return;
    var r = el.getBoundingClientRect();
    bridge.fieldFocused(r.left, r.bottom, isPw(el));
  }, true);
  document.addEventListener('submit', function (e) { capture(e.target.querySelector('input[type=password]') || e.target.querySelector('input')); }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target && (isPw(e.target) || isUser(e.target))) capture(e.target);
  }, true);
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest && e.target.closest('button, input[type=submit], input[type=button], [role=button]');
    if (!b) return;
    var pw = document.querySelector('input[type=password]');
    capture(b.form ? (b.form.querySelector('input[type=password]') || b.form.querySelector('input')) : pw);
  }, true);
  window.addEventListener('pagehide', function () { var pw = document.querySelector('input[type=password]'); if (pw && pw.value) capture(pw); }, true);
  new QWebChannel(qt.webChannelTransport, function (ch) { bridge = ch.objects.wfPasswords; window.__wfBridge = bridge; });
})();
"""


def _qwebchannel_js() -> str:
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


class _Bridge(QObject):
    def __init__(self, manager: "PasswordManager", tab):
        super().__init__(tab)
        self.manager, self.tab = manager, tab

    @Slot(float, float, bool)
    def fieldFocused(self, x, y, is_password):
        self.manager.field_focused(self.tab, x, y)

    @Slot(str, str, bool)
    def submitted(self, username, password, new_password):
        self.manager.submitted(self.tab, username, password)

    @Slot(str)
    def usernameSeen(self, username):
        self.manager.username_seen(self.tab, username)

    # addresses and cards (autofill.py) share this channel
    @Slot(float, float, str)
    def autofillFocused(self, x, y, section):
        if self.manager.autofill is not None:
            self.manager.autofill.field_focused(self.tab, x, y, section)

    @Slot(str)
    def autofillSubmitted(self, payload):
        if self.manager.autofill is not None:
            self.manager.autofill.submitted(self.tab, payload)


class SaveBar(QWidget):
    """'Save password?' strip shown above the page, like Chrome's bubble."""

    def __init__(self, manager: "PasswordManager", win):
        super().__init__(win)
        self.manager, self.win, self.pending = manager, win, None
        self._custom = None
        self.setObjectName("savebar")
        self.setStyleSheet("#savebar{background:#1d2133;border-bottom:1px solid #2f3547}")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 12, 6)
        self.label = QLabel()
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primary")
        self.never_btn = QPushButton("Never for this site")
        self.later_btn = QPushButton("Not now")
        h.addWidget(self.label, 1)
        for b in (self.save_btn, self.never_btn, self.later_btn):
            h.addWidget(b)
        self.save_btn.clicked.connect(self._save)
        self.never_btn.clicked.connect(self._never)
        self.later_btn.clicked.connect(self.dismiss)
        self.hide()

    def offer(self, tab, origin, username, password, existing):
        self.pending = (tab, origin, username, password, existing)
        who = f" for <b>{_esc(username)}</b>" if username else ""
        if existing:
            self.label.setText(f"Update saved password{who} on {_esc(display_site(origin))}?")
            self.save_btn.setText("Update")
        else:
            self.label.setText(f"Save password{who} for {_esc(display_site(origin))}?")
            self.save_btn.setText("Save")
        self.never_btn.setVisible(existing is None)
        self._custom = None
        self.show()

    def offer_custom(self, text: str, button: str, on_save):
        """The same strip for other things worth keeping (addresses and cards)."""
        self.pending, self._custom = None, on_save
        self.label.setText(text)
        self.save_btn.setText(button)
        self.never_btn.hide()
        self.show()

    def dismiss(self):
        self.pending = self._custom = None
        self.hide()

    def _save(self):
        if self._custom is not None:
            act, self._custom = self._custom, None
            self.hide()
            act()
            return
        if not self.pending:
            return
        _tab, origin, username, password, existing = self.pending
        if existing:
            self.manager.store.update(existing["id"], password=password)
        else:
            self.manager.store.add(origin, username, password)
        self.dismiss()

    def _never(self):
        if self.pending:
            self.manager.store.add_never(self.pending[1])
        self.dismiss()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class PasswordManager:
    """Wires the store into tabs: injects the page script, shows the fill menu and the save bar."""

    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self._script_src = None
        self.autofill = None   # an autofill.Autofill, set by the browser
        self._usernames: dict[str, tuple[str, float]] = {}   # origin -> (username, time) for two-page logins

    def enabled(self) -> bool:
        return self.settings.get("save_passwords") is not False

    def attach(self, tab, win):
        if getattr(tab, "background", False):
            return
        tab._pw_win = win
        page = tab.page()
        channel = QWebChannel(page)
        channel.registerObject("wfPasswords", _Bridge(self, tab))
        page.setWebChannel(channel, _APP_WORLD)
        if self._script_src is None:
            from .autofill import PAGE_JS as AUTOFILL_JS
            self._script_src = _qwebchannel_js() + "\n" + _PAGE_JS + "\n" + AUTOFILL_JS
        script = QWebEngineScript()
        script.setName("wayfinder-passwords")
        script.setSourceCode(self._script_src)
        script.setWorldId(_APP_WORLD)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setRunsOnSubFrames(False)
        page.scripts().insert(script)

    # -- helpers
    @staticmethod
    def _agent_busy(win) -> bool:
        agent = getattr(getattr(win, "panel", None), "agent", None)
        return bool(agent and agent.running and not agent.waiting_for_user)

    def _origin(self, tab) -> str:
        return origin_of(tab.url())

    # -- events from the page
    def field_focused(self, tab, x, y):
        win = getattr(tab, "_pw_win", None)
        origin = self._origin(tab)
        if win is None or self._agent_busy(win) or win.current_tab() is not tab:
            return
        logins = self.store.for_origin(origin)
        if not logins:
            return
        menu = QMenu(tab)
        for login in logins[:8]:
            label = login["username"] or "(no username)"
            if login["origin"] != origin:
                label += f"   ·  {display_site(login['origin'])}"
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, lid=login["id"]: self.fill(tab, lid))
        menu.addSeparator()
        menu.addAction("Manage passwords…").triggered.connect(lambda: win.show_passwords())
        z = tab.zoomFactor()
        menu.popup(tab.mapToGlobal(QPoint(round(x * z), round(y * z) + 2)))

    def fill(self, tab, login_id: str):
        login = self.store.get(login_id)
        if not login or not _matches(login["origin"], self._origin(tab)):
            return
        tab.run_js(f"window.__wfFill && window.__wfFill({json.dumps(login['username'])}, {json.dumps(login['password'])})")
        self.store.touch(login_id)

    def username_seen(self, tab, username):
        origin = self._origin(tab)
        if origin:
            self._usernames[origin] = (username, time.time())

    def submitted(self, tab, username, password):
        win = getattr(tab, "_pw_win", None)
        origin = self._origin(tab)
        if (win is None or not origin or not password or not self.enabled() or tab.private
                or self._agent_busy(win) or self.store.is_never(origin)):
            return
        if not username:
            recent = self._usernames.get(origin)
            if recent and time.time() - recent[1] < 600:
                username = recent[0]
        existing = self.store.find(origin, username)
        if existing and existing["password"] == password:
            self.store.touch(existing["id"])
            return
        # Let the page navigate first, then ask (like Chrome's post-login bubble).
        QTimer.singleShot(600, lambda: win.save_bar.offer(tab, origin, username, password, existing)
                          if tab in win.tab_list() else None)

    # -- import from Google Password Manager (its own export, caught on the way to disk)
    def start_google_import(self, win):
        self._google_until = time.time() + 900
        self._google_win = win
        win.open_tab(GOOGLE_EXPORT_URL)

    def intercept_download(self, req) -> bool:
        """Called for every download. Takes Google's password export when an import is pending."""
        if time.time() > getattr(self, "_google_until", 0):
            return False
        page = req.page()
        host = page.url().host() if page is not None else ""
        if host != "passwords.google.com" or not req.downloadFileName().lower().endswith(".csv"):
            return False
        self._google_until = 0
        folder = Path(self.store.path).parent / "import-tmp"
        folder.mkdir(exist_ok=True)
        name = uuid.uuid4().hex + ".csv"
        req.setDownloadDirectory(str(folder))
        req.setDownloadFileName(name)
        req.accept()
        path = folder / name
        win = getattr(self, "_google_win", None)

        def state(_s=None):
            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest as R
            st = req.state()
            if st == R.DownloadState.DownloadCompleted:
                try:
                    result = self.store.import_csv(path)
                except Exception as e:
                    result = e
                finally:
                    _shred(path)
                self._report(win, result)
            elif st in (R.DownloadState.DownloadCancelled, R.DownloadState.DownloadInterrupted):
                _shred(path)
        req.stateChanged.connect(state)
        state()
        return True

    @staticmethod
    def _report(win, result):
        from PySide6.QtWidgets import QMessageBox
        if win is None:
            return
        if isinstance(result, Exception):
            QMessageBox.warning(win, "Import from Google", f"The import failed: {result}")
        else:
            added, updated, skipped = result
            QMessageBox.information(win, "Import from Google",
                                    f"Imported your Google passwords: {added} added, {updated} updated, "
                                    f"{skipped} unchanged.\nThe exported file was deleted.")


def _shred(path: Path):
    """Overwrite then delete a temporary export so the plaintext does not linger on disk."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
