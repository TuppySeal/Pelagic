"""Chromium-backed tab (QtWebEngine) with helpers the AI agent uses to drive it."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QCryptographicHash, QEvent, QIODevice, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFocusEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import (QWebEngineCertificateError, QWebEnginePage, QWebEngineProfile,
                                     QWebEngineScript, QWebEngineSettings, QWebEnginePermission)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMessageBox

_APP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld

_KEYS = {
    "enter": Qt.Key_Return, "return": Qt.Key_Return, "tab": Qt.Key_Tab, "escape": Qt.Key_Escape, "esc": Qt.Key_Escape,
    "backspace": Qt.Key_Backspace, "delete": Qt.Key_Delete, "space": Qt.Key_Space, "arrowdown": Qt.Key_Down,
    "arrowup": Qt.Key_Up, "arrowleft": Qt.Key_Left, "arrowright": Qt.Key_Right, "down": Qt.Key_Down, "up": Qt.Key_Up,
    "left": Qt.Key_Left, "right": Qt.Key_Right, "pagedown": Qt.Key_PageDown, "pageup": Qt.Key_PageUp,
    "home": Qt.Key_Home, "end": Qt.Key_End,
}
_MODS = {"control": Qt.ControlModifier, "ctrl": Qt.ControlModifier, "shift": Qt.ShiftModifier, "alt": Qt.AltModifier}


def make_profile(name: str | None, storage: str | None, parent=None) -> QWebEngineProfile:
    """name=None gives an off-the-record (private) profile."""
    profile = QWebEngineProfile(name, parent) if name else QWebEngineProfile(parent)
    # In-memory only; regular and private profiles never share trust decisions.
    profile._certificate_exceptions = set()
    if name and storage:
        profile.setPersistentStoragePath(storage + "/profile")
        profile.setCachePath(storage + "/cache")
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    s = profile.settings()
    for attr in (QWebEngineSettings.WebAttribute.JavascriptEnabled, QWebEngineSettings.WebAttribute.PluginsEnabled,
                 QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
                 QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
                 QWebEngineSettings.WebAttribute.PdfViewerEnabled,
                 QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows):
        s.setAttribute(attr, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    return profile


_SCREEN_SHARE = {getattr(QWebEnginePermission.PermissionType, n) for n in ("DesktopVideoCapture", "DesktopAudioVideoCapture")
                 if hasattr(QWebEnginePermission.PermissionType, n)}


class WebPage(QWebEnginePage):
    def __init__(self, profile, tab):
        super().__init__(profile, tab)
        self.tab = tab
        self._certificate_exceptions = profile._certificate_exceptions
        self._pending_certificates = {}
        self.certificateError.connect(self._on_certificate_error)
        self.loadStarted.connect(self._dismiss_certificate_warnings)
        self.permissionRequested.connect(self._on_permission)
        self.fullScreenRequested.connect(self._on_fullscreen)
        if hasattr(self, "desktopMediaRequested"):    # screen sharing (getDisplayMedia), Qt 6.7+
            self.desktopMediaRequested.connect(self._on_desktop_media)
        self.loadFinished.connect(self._darkmode_migrate)
        from . import darkmode
        darkmode.track(self)   # reloaded when dark mode is switched on or off

    def _darkmode_migrate(self, ok):
        win = self.tab.window()
        ctx = getattr(win, "ctx", None)
        if ok and ctx is not None and not self.profile().isOffTheRecord():
            from . import darkmode
            darkmode.migrate_page(self.tab, getattr(win, "store", None), getattr(ctx, "extensions", None))

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # the start page's "+", "⋮" and "Customize" links (only from the start page itself)
        if is_main_frame and self.url().isLocalFile() and self.url().fileName() == "start.html":
            from .homepage import parse_action
            act = parse_action(url)
            if act:
                QTimer.singleShot(0, lambda: self.tab.home_action.emit(*act))
                return False
        # reader mode's toolbar links (only from a reader page)
        if is_main_frame and self.url().isLocalFile() and self.url().fileName().startswith("reader-"):
            from .tools import parse_reader_action
            act = parse_reader_action(url)
            if act:
                QTimer.singleShot(0, lambda: self.tab.reader_action.emit(act))
                return False
        # files from the computer: Markdown and text files open in Pelagic's file view (and its bar's links)
        if is_main_frame:
            from . import fileview
            store = getattr(self.tab.window(), "store", None)
            ours = getattr(self.tab, "_file_rerender", False)
            self.tab._file_rerender = False
            if fileview.is_view(url) and nav_type == QWebEnginePage.NavigationType.NavigationTypeReload and not ours:
                QTimer.singleShot(0, lambda: fileview.handle_action(self.tab, "file-reload", store))   # F5: read it again
                return False
            if fileview.is_view(self.url()):
                act = fileview.parse_action(url)
                if act:
                    QTimer.singleShot(0, lambda: fileview.handle_action(self.tab, act, store))
                    return False
            if fileview.wants(url):
                QTimer.singleShot(0, lambda: fileview.show(self.tab, url, store))
                return False
        if is_main_frame:   # dark mode for websites: on or off for the page about to open (darkmode.py)
            from . import darkmode
            darkmode.apply_page(self, url, getattr(self.tab.window(), "store", None))
        # unsafe-site warnings: the warning page's own two links, then the check itself
        if is_main_frame:
            from . import safebrowsing
            guard = getattr(self.profile(), "_safe", None)
            if guard is not None and safebrowsing.is_warning(self.url()):
                act = safebrowsing.parse_action(url)
                if act:
                    QTimer.singleShot(0, lambda: safebrowsing.handle_action(self.tab, act, guard))
                    return False
            kind = guard.check(url) if guard is not None else None
            if kind:
                QTimer.singleShot(0, lambda: safebrowsing.show_warning(self.tab, url, kind, guard.store))
                return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, wtype):
        # target=_blank, window.open, middle-click: open as a new tab.
        background = wtype == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        new_tab = self.tab.open_tab_requested(background)
        return new_tab.page() if new_tab else None

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass

    def _on_certificate_error(self, error):
        url = error.url()
        chain = error.certificateChain()
        # Non-overridable errors must stay blocked, even after another error was accepted.
        if not error.isOverridable() or url.scheme() != "https" or not url.host() or not chain:
            error.rejectCertificate()
            return
        fingerprint = bytes(chain[0].digest(QCryptographicHash.Algorithm.Sha256)).hex().upper()
        key = (url.host().casefold(), url.port(443), fingerprint, error.type().value)
        if key in self._certificate_exceptions:
            error.acceptCertificate()
            return
        # Unrecognized failing resources cannot grant trust to a different site silently.
        if not error.isMainFrame():
            error.rejectCertificate()
            return
        if key in self._pending_certificates:
            error.rejectCertificate()
            return
        # Keep a copy alive and leave the Chromium callback before opening a dialog.
        deferred = QWebEngineCertificateError(error)
        deferred.defer()
        self._pending_certificates[key] = (deferred, None)
        QTimer.singleShot(0, self, lambda: self._show_certificate_warning(key))

    def _show_certificate_warning(self, key):
        pending = self._pending_certificates.get(key)
        if pending is None:
            return  # A different navigation dismissed the deferred request.
        error, _ = pending
        url = error.url()
        origin = QUrl()
        origin.setScheme("https")
        origin.setHost(url.host())
        if url.port(443) != 443:
            origin.setPort(url.port(443))
        site = origin.toString()
        dialog = QMessageBox(self.tab)
        dialog.setWindowTitle("Certificate warning — Pelagic")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"Pelagic cannot verify the identity of {site}.")
        dialog.setInformativeText(
            f"{error.description()}\n\n"
            "Only continue if you recognize this device or site and trust its certificate. "
            "Trust applies to this host and certificate until Pelagic closes."
        )
        fingerprint = ":".join(key[2][i:i + 2] for i in range(0, len(key[2]), 2))
        dialog.setDetailedText(f"Site: {site}\nCertificate SHA-256: {fingerprint}")
        trust = dialog.addButton("Trust for this session", QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        self._pending_certificates[key] = (error, dialog)

        def finish(_result):
            pending = self._pending_certificates.pop(key, None)
            if pending is not None:
                if dialog.clickedButton() is trust:
                    self._certificate_exceptions.add(key)
                    error.acceptCertificate()
                else:
                    error.rejectCertificate()
            dialog.deleteLater()

        dialog.finished.connect(finish)
        dialog.open()

    def _dismiss_certificate_warnings(self):
        pending, self._pending_certificates = self._pending_certificates, {}
        for error, dialog in pending.values():
            error.rejectCertificate()
            if dialog is not None:
                dialog.reject()

    def _on_permission(self, perm: QWebEnginePermission):
        names = {
            QWebEnginePermission.PermissionType.Geolocation: "your location",
            QWebEnginePermission.PermissionType.MediaAudioCapture: "your microphone",
            QWebEnginePermission.PermissionType.MediaVideoCapture: "your camera",
            QWebEnginePermission.PermissionType.MediaAudioVideoCapture: "your camera and microphone",
            QWebEnginePermission.PermissionType.Notifications: "show notifications",
            QWebEnginePermission.PermissionType.ClipboardReadWrite: "read your clipboard",
        }
        what = names.get(perm.permissionType())
        if getattr(self.tab, "background", False):   # background watcher tabs never ask or grant
            perm.deny()
            return
        if perm.permissionType() in _SCREEN_SHARE:
            perm.grant()    # screen sharing: the screen picker that follows asks, and Cancel there shares nothing
            return
        if what is None:
            perm.deny()
            return
        host = perm.origin().host() or "This page"
        ans = QMessageBox.question(self.tab.window(), "Permission request", f"{host} wants to access {what}. Allow?")
        perm.grant() if ans == QMessageBox.StandardButton.Yes else perm.deny()

    def _on_desktop_media(self, request):
        if getattr(self.tab, "background", False):
            request.cancel()
            return
        from . import screenshare
        screenshare.handle_request(self, request, self.tab.window())

    def _on_fullscreen(self, request):
        if getattr(self.tab, "background", False):
            request.reject()
            return
        request.accept()
        win = self.tab.window()
        if hasattr(win, "set_fullscreen"):
            win.set_fullscreen(request.toggleOn(), page=True)
        elif request.toggleOn():
            win.showFullScreen()
        else:
            win.showNormal()

    def javaScriptAlert(self, origin, msg):
        if getattr(self.tab, "background", False):
            return
        QMessageBox.information(self.tab.window(), origin.host() or "Page", msg)

    def javaScriptConfirm(self, origin, msg):
        if getattr(self.tab, "background", False):
            return False
        return QMessageBox.question(self.tab.window(), origin.host() or "Page", msg) == QMessageBox.StandardButton.Yes


class BrowserTab(QWebEngineView):
    ask_ai = Signal(str, str)        # kind ("selection"|"page"), text
    inspect_requested = Signal()
    home_action = Signal(str, int)   # start page: "add" | "edit" | "customize", shortcut index
    reader_action = Signal(str)      # reader mode toolbar: "reader-exit", "reader-bigger", …
    new_tab_requested = Signal(object, bool)

    def __init__(self, profile, factory=None, parent=None):
        super().__init__(parent)
        self._factory = factory
        self.loading = False
        self.private = profile.isOffTheRecord()
        self.background = False     # True for invisible watcher tabs
        self.setPage(WebPage(profile, self))
        self.loadStarted.connect(lambda: setattr(self, "loading", True))
        self.loadFinished.connect(lambda ok: setattr(self, "loading", False))

    def open_tab_requested(self, background: bool):
        return self._factory(self, background) if self._factory else None

    # A deferred TLS request can keep Chromium from starting the next navigation,
    # so dismiss it before submitting navigation rather than waiting for loadStarted.
    def load(self, url):
        self.page()._dismiss_certificate_warnings()
        super().load(url)

    def setUrl(self, url):
        self.page()._dismiss_certificate_warnings()
        super().setUrl(url)

    def reload(self):
        self.page()._dismiss_certificate_warnings()
        super().reload()

    def back(self):
        self.page()._dismiss_certificate_warnings()
        super().back()

    def forward(self):
        self.page()._dismiss_certificate_warnings()
        super().forward()

    def stop(self):
        self.page()._dismiss_certificate_warnings()
        super().stop()

    # -- context menu
    def contextMenuEvent(self, ev):
        menu = self.createStandardContextMenu()
        inspect = self.page().action(QWebEnginePage.WebAction.InspectElement)
        menu.removeAction(inspect)   # replaced by our own "Inspect", which opens the docked DevTools first
        req = self.lastContextMenuRequest()
        sel = (req.selectedText() if req else "").strip()
        if req is not None and req.misspelledWord():   # spelling suggestions first, like Chrome
            first = menu.actions()[0] if menu.actions() else None
            words = list(req.spellCheckerSuggestions())[:6]
            for w in words or ["(no suggestions)"]:
                a = QAction(w, menu)
                a.setEnabled(bool(words))
                f = a.font()
                f.setBold(True)
                a.setFont(f)
                a.triggered.connect(lambda _=False, w=w: self.page().replaceMisspelledWord(w))
                menu.insertAction(first, a)
            menu.insertSeparator(first)
        menu.addSeparator()
        if sel:
            a = QAction("Ask Pelagic AI about selection", menu)
            a.triggered.connect(lambda: self.ask_ai.emit("selection", sel))
            menu.addAction(a)
        b = QAction("Summarize this page with Pelagic AI", menu)
        b.triggered.connect(lambda: self.ask_ai.emit("page", ""))
        menu.addAction(b)
        menu.addSeparator()
        c = QAction("Inspect", menu)
        c.triggered.connect(lambda: self.window().inspect_element() if hasattr(self.window(), "inspect_element")
                            else None)
        menu.addAction(c)
        menu.popup(ev.globalPos())
        ev.accept()

    # -- agent helpers
    def run_js(self, code: str, cb=None):
        if self.page().lifecycleState() != self.page().LifecycleState.Active:
            self.page().setLifecycleState(self.page().LifecycleState.Active)   # a sleeping tab wakes for scripts
        if cb is None:
            self.page().runJavaScript(code, _APP_WORLD)
        else:
            self.page().runJavaScript(code, _APP_WORLD, cb)

    def _target(self):
        return self.focusProxy() or self

    def real_click(self, x: float, y: float):
        z = self.zoomFactor()
        pos = QPoint(round(x * z), round(y * z))
        w = self._target()
        QTest.mouseMove(w, pos)
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos, 25)

    def type_char(self, ch: str):
        """One real key press (trusted keydown/keypress/input events), like a person typing."""
        w = self._target()
        if not w.hasFocus():
            w.setFocus(Qt.FocusReason.OtherFocusReason)   # focus inside Pelagic only; never touches the OS cursor
        if not w.window().isActiveWindow():
            # Pelagic is in the background (the user is working elsewhere): tell Chromium its page has focus so it
            # still accepts the key presses, without activating the window or touching the user's keyboard/mouse.
            QApplication.sendEvent(w, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.ActiveWindowFocusReason))
        if ch in "\r\n":
            QTest.keyClick(w, Qt.Key_Return, Qt.KeyboardModifier.NoModifier, 10)
        elif ch.isascii() and ch.isprintable():
            QTest.keyClick(w, ch, Qt.KeyboardModifier.NoModifier, 10)
        else:
            from . import pagejs
            self.run_js(pagejs.call(pagejs.INSERT_CHAR, ch))

    def press_key(self, spec: str) -> bool:
        parts = [p for p in spec.replace(" ", "").split("+") if p]
        if not parts:
            return False
        mods = Qt.KeyboardModifier.NoModifier
        for m in parts[:-1]:
            if m.lower() not in _MODS:
                return False
            mods |= _MODS[m.lower()]
        last = parts[-1]
        w = self._target()
        if last.lower() in _KEYS:
            QTest.keyClick(w, _KEYS[last.lower()], mods, 20)
            return True
        if len(last) == 1:
            QTest.keyClick(w, last, mods, 20)
            return True
        return False

    def grab_png_b64(self, max_width: int = 1024, masks=None) -> str:
        """The page as a PNG for the agent. `masks` are [x, y, w, h] page rectangles (secret fields that show their
        text, like a password after "show password") that are painted over before the picture leaves this method."""
        pix = self.grab()
        if pix.isNull():
            return ""
        if masks:
            z = self.zoomFactor()
            p = QPainter(pix)
            for x, y, w, h in masks:
                p.fillRect(int(x * z) - 2, int(y * z) - 2, int(w * z) + 4, int(h * z) + 4, QColor(0, 0, 0))
            p.end()
        if pix.width() > max_width:
            pix = pix.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pix.save(buf, "PNG")
        return base64.b64encode(bytes(buf.data())).decode("ascii")
