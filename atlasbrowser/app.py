"""Application controller and entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from PySide6.QtGui import QIcon

from PySide6.QtCore import Qt, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .downloads import DownloadsPage, choose_path
from .adblock import Blocker, shared_lists
from .extensions import Extensions, parse_meta
from . import darkmode, safebrowsing
from . import sync as sync_mod
from .autofill import Autofill, AutofillStore
from .sync import Collections, FolderSync
from .passwords import PasswordManager, PasswordStore
from .profiles import DEFAULT_ID, ProfileHub
from .store import Store
from .watches import Watches
from .webview import BrowserTab, make_profile
from .window import MainWindow, apply_theme

INSTANCE_NAME = "AtlasBrowserSingleInstance"
DARKMODE_SOURCE = darkmode.SOURCE


class Browser:
    def __init__(self, app: QApplication, store: Store, hub: ProfileHub | None = None, pid: str = DEFAULT_ID):
        self.app, self.store, self.hub, self.pid = app, store, hub, pid
        # The first profile keeps its original engine name so existing cookies and sign-ins stay.
        self.profile = make_profile("AtlasBrowser" if pid == DEFAULT_ID else f"Wayfinder-{pid}", str(store.root), app)
        self.private_profile = make_profile(None, None, app)
        threats = safebrowsing.shared_lists((store.shared or store).root / "safebrowsing")
        self.profile._safe = self.private_profile._safe = self.safe = safebrowsing.Guard(threats, store)
        self.windows: list[MainWindow] = []
        self.main_window: MainWindow | None = None
        self.crashed = store.get("running") is True   # never got to close last time: tabs come from the autosave
        store.set("running", True)
        self.downloads = DownloadsPage(store, current_tab=lambda: self.window().current_tab() if self.windows else None)
        self.watches = Watches(self)
        self.passwords = PasswordManager(PasswordStore(store.root), store)
        self.passwords.autofill = Autofill(AutofillStore(store.root), store)
        # Extensions are per profile and stay out of private windows; the ad blocker covers both.
        self.extensions = Extensions(store.root)
        self.extensions.attach_profile(self.profile)
        # the built-in dark mode extension: added once per profile, and updated with Pelagic (unless removed)
        code = (Path(__file__).parent / "assets" / "darkmode.user.js").read_text(encoding="utf-8")
        mine = next((e for e in self.extensions.items if e.get("source") == DARKMODE_SOURCE), None)
        if not store.get("darkmode_added"):
            store.set("darkmode_added", True)
            self.extensions.install(code, source_url=DARKMODE_SOURCE)
        elif mine and mine.get("version") != parse_meta(code).get("version", ""):
            self.extensions.install(code, source_url=DARKMODE_SOURCE)
        lists = shared_lists((store.shared or store).root / "adblock")
        from . import blocklist   # blocked domains (Pi-hole style): one per profile, private windows included
        self.domains = blocklist.DomainBlocker(store, blocklist.shared_lists((store.shared or store).root / "blocklists"))
        self.profile._domains = self.private_profile._domains = self.domains
        self.blocker = Blocker(lists, store, app, domains=self.domains)
        self.profile.setUrlRequestInterceptor(self.blocker)
        self.private_blocker = Blocker(lists, store, app, domains=self.domains)
        self.private_profile.setUrlRequestInterceptor(self.private_blocker)
        self._watches_loaded = False
        self._background: list = []
        for p in (self.profile, self.private_profile):
            p.downloadRequested.connect(self.on_download)
        from . import spellcheck
        spellcheck.apply(store, [self.profile, self.private_profile])
        from . import proxy
        if proxy.uses_proxy(proxy.config(store)) and proxy.config(store).get("webrtc_private", True):
            from PySide6.QtWebEngineCore import QWebEngineSettings
            for p in (self.profile, self.private_profile):   # WebRTC shows only the proxy's side, not local addresses
                p.settings().setAttribute(QWebEngineSettings.WebAttribute.WebRTCPublicInterfacesOnly, True)
        # folder sync (sync.py): soon after start, then every few minutes, and when the last window closes
        self.sync = FolderSync(store, pid, Collections(store, self.passwords.store, self.passwords.autofill.store))
        self._sync_job = None
        self._sync_timer = QTimer(interval=sync_mod.INTERVAL_MS, timeout=self.sync_now)
        self._sync_timer.start()
        QTimer.singleShot(8000, self.sync_now)

    def sync_now(self, done=None):
        """Runs one sync round off the UI thread; done(report) afterwards."""
        if not self.store.get("sync_folder"):
            if done:
                done("Sync is off.")
            return
        from .agent import run_in_pool

        def finished(_tok, out):
            self._sync_job = None
            report = f"Sync failed: {out}" if isinstance(out, Exception) else out
            for w in self.windows:
                w._rebuild_bookmarks()
                w.completer_refresh()
            if done:
                done(report)
        self._sync_job = run_in_pool(0, self.sync.run, finished)

    def window(self) -> MainWindow:
        """The window watchers and notifications talk to."""
        return self.main_window or next((w for w in self.windows if not w.private), self.windows[0])

    def background_tab(self) -> BrowserTab:
        """An invisible, fully rendered tab for watchers (never shown, never steals focus)."""
        tab = BrowserTab(self.profile)
        tab.background = True
        tab.setAttribute(Qt.WA_DontShowOnScreen, True)
        tab.resize(1280, 800)
        tab.show()
        return tab

    def watch_ended(self, watcher, why: str):
        self.watches.notify(f"Pelagic: {watcher.name}", f"Stopped: {why}")

    def new_window(self, private: bool = False, urls: list[str] | None = None) -> MainWindow:
        w = MainWindow(self, private)
        self.windows.append(w)
        if not private and self.main_window is None:
            self.main_window = w
        for u in urls or [None]:
            w.open_tab(u)
        w.show()
        w.raise_()
        w.activateWindow()
        w.completer_refresh()
        if not private and not self._watches_loaded:
            self._watches_loaded = True
            self.watches.load()
        return w

    def new_private_window(self):
        self.new_window(private=True)

    def window_closed(self, w: MainWindow):
        if w in self.windows:
            self.windows.remove(w)
        if self.main_window is w:
            self.main_window = next((x for x in self.windows if not x.private), None)
        if not any(not x.private for x in self.windows):
            self.store.set("running", False)
            if self.store.get("sync_folder"):
                try:
                    self.sync.run()      # so the other computer sees the latest
                except Exception:
                    pass

    def show_downloads(self):
        self.downloads.show()
        self.downloads.raise_()

    def on_download(self, req):
        if self.passwords.intercept_download(req):
            return
        kind = self.safe.check(req.url())
        if kind:
            req.cancel()
            win = self.window() if self.windows else None
            if win is not None:
                win.notify(f"Pelagic blocked a download from {req.url().host()}: it's on public {kind} lists.")
            return
        path = choose_path(self.store, req, QApplication.activeWindow())
        if not path:
            req.cancel()
            return
        req.setDownloadDirectory(os.path.dirname(path))
        req.setDownloadFileName(os.path.basename(path))
        req.accept()
        page = req.page()
        self.downloads.track(req, private=bool(page and page.profile().isOffTheRecord()))
        self.show_downloads()

    def open_urls(self, urls: list[str]):
        win = self.main_window or next((w for w in self.windows if not w.private), None)
        if win is None:
            self.new_window(urls=urls)
            return
        for u in urls:
            win.open_tab(u)
        win.raise_()
        win.activateWindow()


def _send_to_running(urls: list[str]) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(("\n".join(urls) + "\n").encode("utf-8") if urls else b"\n")
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    urls = [a for a in argv[1:] if not a.startswith("-")]
    app = QApplication(argv)
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Pelagic.Desktop')
    else:
        app.setDesktopFileName('pelagic')   # matches pelagic.desktop, so Linux docks show the right icon
    icon = 'pelagic.ico' if sys.platform == 'win32' else 'pelagic.png'
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets' / icon)))
    app.setApplicationName("Pelagic")
    app.setOrganizationName("AtlasBrowser")
    if _send_to_running(urls):
        return 0
    apply_theme(app)
    store = Store()
    from . import spellcheck
    spellcheck.prepare_environment()   # before the browser engine starts
    from . import proxy
    proxy.apply_environment(store)     # proxy / VPN connection (Settings → Connection), also before the engine
    hub = ProfileHub(app, store, Browser)

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)
    server.listen(INSTANCE_NAME)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            data = bytes(conn.readAll()).decode("utf-8", "replace")
            hub.open_urls([u for u in data.split("\n") if u.strip()])
            conn.disconnectFromServer()
        conn.readyRead.connect(read)
    server.newConnection.connect(on_connection)

    hub.open_profile(hub.profiles.last, urls or None)
    from . import secretbox
    problem = secretbox.available()
    if problem and not store.get("keyring_warning_shown"):   # Linux without a keyring: once, so it isn't a surprise
        from PySide6.QtWidgets import QMessageBox
        store.set("keyring_warning_shown", True)
        QTimer.singleShot(800, lambda: QMessageBox.warning(app.activeWindow(), "Pelagic", problem))
    app.setQuitOnLastWindowClosed(True)
    code = app.exec()
    hub.stop_all()
    server.close()
    return code
