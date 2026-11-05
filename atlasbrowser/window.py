"""Main browser window: tabs, address bar, bookmarks bar, find bar and the docked AI panel."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut, QIcon, QGuiApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QTabBar, QToolButton,
                               QVBoxLayout, QWidget)

from . import homepage, icons, tabviews, tools
from .bookmarks_ui import BookmarksBar, BookmarksDialog, BookmarkStrip, save_favicon
from .dialogs import SettingsDialog, UsageDialog
from .library import HistoryDialog, ReadingListDialog
from .panel import AIPanel
from .passwords import SaveBar
from .sleeper import TabSleeper, is_asleep, touch
from .store import SEARCH_ENGINES
from .webview import BrowserTab

HOSTLIKE = re.compile(r"^(localhost|(\d{1,3}\.){3}\d{1,3}|\[[0-9a-f:]+\]|[\w-]+(\.[\w-]+)+)(:\d+)?([/?#].*)?$", re.I)
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)

STYLE = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow, QDialog, QWidget { background: #14161c; color: #e6e8ee; }
QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QComboBox, QSpinBox {
  background: #1d2029; border: 1px solid #2b3040; border-radius: 8px; padding: 5px 8px; selection-background-color: #1B8C9A; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #2FB3B4; }
QComboBox QAbstractItemView { background: #1d2029; selection-background-color: #3a3d47; border: 1px solid #2b3040; }
QPushButton, QToolButton { background: #232734; border: 1px solid #2f3547; border-radius: 8px; padding: 5px 10px; }
QPushButton:hover, QToolButton:hover { background: #2a2d35; border-color: #3a3e4a; }
QPushButton:checked { background: #0B4A6B; border-color: #2FB3B4; }
QPushButton:disabled { color: #6b7185; }
QPushButton#primary { background: #1B8C9A; border-color: #2FB3B4; font-weight: 600; }
QPushButton#primary:hover { background: #22A0AE; }
QToolButton { padding: 4px 8px; font-size: 15px; }
QTabWidget::pane { border: none; }
QWidget#tabrow { background: #0c0e12; }
QTabBar::tab { background: transparent; padding: 7px 10px; margin: 6px 1px 0 1px; border-top-left-radius: 8px;
  border-top-right-radius: 8px; color: #a9afc2; }
QTabBar::tab:selected { background: #14161c; color: #ffffff; }
QTabBar::tab:hover:!selected { background: rgba(255, 255, 255, 0.06); }
QTabBar::tear { width: 0; border: none; }
QTabBar::scroller { width: 52px; }
QTabBar QToolButton { background: #1e2129; border: none; border-radius: 6px; margin: 6px 1px 2px 1px; }
QTabBar QToolButton:hover { background: #2a2d35; }
QTabBar QToolButton::left-arrow { image: url(ASSETS/chevron-left.svg); }
QTabBar QToolButton::right-arrow { image: url(ASSETS/chevron-right.svg); }
QDockWidget { titlebar-close-icon: none; font-weight: 600; }
QDockWidget::title { background: #181b24; padding: 8px; }
QProgressBar { background: transparent; border: none; max-height: 3px; }
QProgressBar::chunk { background: #2FB3B4; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #3a4058; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QLabel#muted { color: #8b93a7; }
QMenu { background: #1d2029; border: 1px solid #2f3547; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: rgba(255, 255, 255, 0.10); }
QCheckBox { spacing: 8px; }
QCheckBox::indicator, QListView::indicator, QTreeView::indicator { width: 16px; height: 16px; border-radius: 4px;
  border: 1.5px solid #7d8499; background: #14161c; }
QCheckBox::indicator:hover, QListView::indicator:hover { border-color: #b7bdcc; }
QCheckBox::indicator:checked, QListView::indicator:checked, QTreeView::indicator:checked { background: #1B8C9A;
  border-color: #2FB3B4; image: url(ASSETS/check.svg); }
QCheckBox::indicator:disabled { border-color: #3a3e4a; background: #191b22; }
QWidget#toolbar QToolButton { background: #1e2129; border: 1px solid #2c303c; border-radius: 9px; padding: 0; }
QWidget#toolbar QToolButton:hover { background: #2a2d35; border-color: #3a3e4a; }
QWidget#toolbar QToolButton:pressed { background: #33363f; }
QWidget#toolbar QToolButton:disabled { background: #191b22; border-color: #23262f; }
QWidget#toolbar QToolButton::menu-indicator { image: none; width: 0; }
QWidget#toolbar QLineEdit { border-radius: 16px; padding: 6px 14px; background: #1d2029; border: 1px solid #262a36; }
QWidget#toolbar QLineEdit:focus { border-color: #2FB3B4; }
"""


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, col in ((QPalette.Window, "#14161c"), (QPalette.WindowText, "#e6e8ee"), (QPalette.Base, "#1d2029"),
                      (QPalette.AlternateBase, "#14161c"), (QPalette.Text, "#e6e8ee"), (QPalette.Button, "#232734"),
                      (QPalette.ButtonText, "#e6e8ee"), (QPalette.Highlight, "#1B8C9A"),
                      (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#1d2029"),
                      (QPalette.ToolTipText, "#e6e8ee"), (QPalette.PlaceholderText, "#7b8296")):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(STYLE.replace("ASSETS", (Path(__file__).parent / "assets").as_posix()))


def _dark_title_bar(win):
    """Ask Windows 10/11 for a dark title bar (with the normal minimize, maximize and close buttons)."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        on = ctypes.c_int(1)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on Windows 10 before 20H1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(int(win.winId()), attr, ctypes.byref(on), 4) == 0:
                break
    except Exception:
        pass


def _person_icon(color: str) -> QIcon:
    """Outline person glyph like the other toolbar icons, with a small dot in the profile's colour."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap
    icon = QIcon()
    for size in (20, 40):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        k = size / 20
        p.setPen(QPen(QColor(icons.FG), 1.7 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawEllipse(QRectF(6.5 * k, 2.5 * k, 7 * k, 7 * k))
        body = QPainterPath()
        body.moveTo(3 * k, 18 * k)
        body.cubicTo(3 * k, 13 * k, 6.5 * k, 11.5 * k, 10 * k, 11.5 * k)
        body.cubicTo(13.5 * k, 11.5 * k, 17 * k, 13 * k, 17 * k, 18 * k)
        p.drawPath(body)
        p.setPen(QPen(QColor("#14161c"), 1.4 * k))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(13.2 * k, 12.6 * k, 6 * k, 6 * k))
        p.end()
        icon.addPixmap(pix)
    return icon



class _Central(QWidget):
    """The page side of the window. Whatever is on it (a long bookmarks bar, a wide toolbar) never asks for more
    than CENTRAL_MIN pixels of width, so a maximised window always leaves the AI panel its full width instead of
    pushing it past the right edge of the screen."""
    CENTRAL_MIN = 420

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.CENTRAL_MIN), hint.height())

class MainWindow(QMainWindow):
    def __init__(self, ctx, private: bool = False):
        super().__init__()
        self.ctx, self.store, self.private = ctx, ctx.store, private
        self.profile = ctx.private_profile if private else ctx.profile
        self.setAcceptDrops(True)   # files dropped on the tab strip or toolbar open in tabs
        self._devtools: dict = {}
        self._set_title("")
        assets = Path(__file__).parent / 'assets'
        self.setWindowIcon(QIcon(str(assets / 'pelagic.ico')))
        self.resize(1360, 860)

        central = _Central()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setSizeConstraint(QLayout.SetNoConstraint)   # see _Central
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # --- toolbar
        bar = self.toolbar = QWidget()
        bar.setObjectName("toolbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)
        self.back_btn = self._tool("back", "Back (Alt+←)", lambda: self._cur(lambda t: t.back()))
        self.fwd_btn = self._tool("forward", "Forward (Alt+→)", lambda: self._cur(lambda t: t.forward()))
        self.reload_btn = self._tool("reload", "Reload (F5)", self._reload_or_stop)
        self.home_btn = self._tool("home", "Home", lambda: self._cur(lambda t: t.load(self.home_url())))
        self.addr = QLineEdit()
        self.addr.setPlaceholderText("Search or enter address")
        self.addr.returnPressed.connect(self._go)
        from .omnibox import Omnibox
        self.omnibox = Omnibox(self)
        self.star = self._tool("star", "Bookmark this page (Ctrl+D)", lambda: self.toggle_bookmark(edit=True))
        self.ai_btn = self._tool("ai", "Pelagic AI (Ctrl+Shift+A)", lambda: self.toggle_panel())
        self.settings_btn = self._tool("gear", "Settings (Ctrl+,)", lambda: self.open_settings())
        from .extensions_ui import ExtensionsButton
        self.ext_btn = ExtensionsButton(self)
        self.menu_btn = self._tool("more", "Menu", None)
        for w in (self.back_btn, self.fwd_btn, self.reload_btn, self.home_btn):
            h.addWidget(w)
        h.addWidget(self.addr, 1)
        for w in (self.star, self.ext_btn, self.ai_btn, self.settings_btn, self.menu_btn):
            h.addWidget(w)
        self.profile_btn = None
        if getattr(ctx, "hub", None) is not None:
            self.profile_btn = self._tool("", "", None)
            self.profile_btn.setPopupMode(QToolButton.InstantPopup)
            self.profile_menu = QMenu(self)
            self.profile_menu.aboutToShow.connect(self._fill_profile_menu)
            self.profile_btn.setMenu(self.profile_menu)
            self.refresh_profile()
            h.addWidget(self.profile_btn)
        v.addWidget(bar)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setRange(0, 100)
        v.addWidget(self.progress)

        self.bm_bar = BookmarkStrip()
        self.bm_lay = self.bm_bar.lay
        self.bm_lay.setContentsMargins(8, 2, 8, 4)
        self.bm_lay.setSpacing(4)
        v.addWidget(self.bm_bar)
        self.bm = BookmarksBar(self)

        self.save_bar = SaveBar(ctx.passwords, self)
        v.addWidget(self.save_bar)

        self.notice = QWidget()   # one-line messages, e.g. after a crash
        self.notice.setObjectName("toolbar")
        nh = QHBoxLayout(self.notice)
        nh.setContentsMargins(12, 4, 8, 4)
        self.notice_text = QLabel()
        self.notice_text.setWordWrap(True)
        ok = QPushButton("OK")
        ok.clicked.connect(self.notice.hide)
        nh.addWidget(self.notice_text, 1)
        nh.addWidget(ok)
        self.notice.hide()
        v.addWidget(self.notice)

        from .tabstrip import TabStrip
        self.sleeper = TabSleeper(self)
        self.strip = TabStrip(self)
        self.tabs = self.strip.tabs
        self.tabs.currentChanged.connect(self._tab_changed)
        plus = QToolButton()
        plus.setIcon(icons.icon("plus"))
        plus.setToolTip("New tab (Ctrl+T)")
        plus.clicked.connect(lambda: self.open_tab())
        for b in (plus, self.strip.search_btn):
            b.setFixedSize(30, 28)
        self.tabs.row.add_buttons(plus, self.strip.search_btn)
        self.window_buttons = self._window_buttons()
        self.tabs.row.add_window_buttons(self.window_buttons)
        self.setMenuWidget(self.tabs.row)   # tabs on top, full width above the address bar and side panel
        self.previews = tabviews.PreviewHover(self)
        self.vtabs = tabviews.VerticalTabs(self)
        self.vtabs.hide()
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.vtabs)
        body.addWidget(self.tabs, 1)
        v.addLayout(body, 1)

        # --- developer tools, docked like Chrome's (one per tab, shown with its tab)
        self.dev_dock = QDockWidget("Developer tools", self)
        self.dev_stack = QStackedWidget()
        self.dev_dock.setWidget(self.dev_stack)
        self.dev_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dev_dock)
        self.dev_dock.hide()
        self._dev_switching = False
        self.dev_dock.visibilityChanged.connect(self._dev_visibility)

        # --- find bar
        self.find_bar = QWidget()
        self.find_bar.setObjectName("toolbar")
        fh = QHBoxLayout(self.find_bar)
        fh.setContentsMargins(8, 4, 8, 4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find in page")
        self.find_edit.textChanged.connect(lambda: self._find())
        self.find_edit.returnPressed.connect(lambda: self._find())
        prev = self._tool("up", "Previous", lambda: self._find(backward=True))
        nxt = self._tool("down", "Next", lambda: self._find())
        close = self._tool("close", "Close", self.hide_find)
        for w in (self.find_edit, prev, nxt, close):
            fh.addWidget(w)
        self.find_bar.hide()
        v.addWidget(self.find_bar)

        # --- AI dock
        self.panel = AIPanel(self, self.store)
        self.panel.open_settings.connect(lambda: self.open_settings("ai"))
        self.dock = QDockWidget("Pelagic AI", self)
        self.dock.setWindowIcon(icons.icon("ai"))
        self.dock.setWidget(self.panel)
        self.dock.setFeatures(QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._dock_visibility)
        # opening or closing the panel can leave a maximised window hanging off the screen (Windows): fit it again
        self._refit_timer = QTimer(self, singleShot=True, interval=120, timeout=self._refit)
        self.dock.visibilityChanged.connect(lambda _v: self._refit_timer.start())
        self.resizeDocks([self.dock], [400], Qt.Horizontal)
        self.dock.setVisible(bool(self.store.get("panel") if self.store.settings.get("panel") is not None else True))

        self._build_menu()
        self._shortcuts()
        self._rebuild_bookmarks()
        g = self.store.get("window").get("geom") if not private else None
        if g:
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        if self.isFullScreen():   # never start without a title bar (older versions saved full-screen state)
            self.setWindowState(Qt.WindowMaximized)
        self._fit_on_screen()
        self._normal_geom = None
        self._video_hidden = None   # browser parts hidden while a page (a video) is full screen
        self.apply_tab_layout()
        if not private:   # keep the saved tabs current, so a crash or power cut doesn't lose them
            self._autosave = QTimer(self, interval=15_000, timeout=self.save_session)
            self._autosave.start()
        _dark_title_bar(self)

    def _fit_on_screen(self):
        """Keep a restored window inside the screen it's on (a size saved on a bigger monitor or at another display
        scale would otherwise hang off the bottom and hide the AI panel's buttons)."""
        if self.isMaximized() or self.isFullScreen():
            return
        screen = QGuiApplication.screenAt(self.geometry().center()) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        extra_w, extra_h = frame.width() - self.width(), frame.height() - self.height()
        w = min(self.width(), avail.width() - extra_w)
        h = min(self.height(), avail.height() - extra_h)
        if (w, h) != (self.width(), self.height()):
            self.resize(max(w, 400), max(h, 300))
        frame = self.frameGeometry()
        x = min(max(frame.x(), avail.left()), avail.right() - frame.width() + 1)
        y = min(max(frame.y(), avail.top()), avail.bottom() - frame.height() + 1)
        if (x, y) != (frame.x(), frame.y()):
            self.move(x, y)

    def download_media(self):
        """YouTube / YouTube Music downloader, filled in with this tab's video when it is one."""
        from . import ytdl
        t = self.current_tab()
        dlg = ytdl.DownloadDialog(tools.page_url(t).toString() if t else "", self.store, self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()

    def open_file(self):
        """Ctrl+O: open files from the computer (Markdown and text files get a readable view)."""
        from . import fileview
        start = self.store.get("open_file_dir") or str(Path.home() / "Documents")
        paths, _ = QFileDialog.getOpenFileNames(self, "Open file", start, fileview.DIALOG_FILTER)
        if paths:
            self.store.set("open_file_dir", str(Path(paths[0]).parent))
            self.open_paths(paths)

    def open_paths(self, paths):
        cur = self.current_tab()
        for n, p in enumerate(paths):
            url = QUrl.fromLocalFile(str(p))
            if n == 0 and cur is not None and (self.is_start(cur.url()) or cur.url().isEmpty()):
                cur.load(url)    # use the new-tab page instead of leaving it empty behind
            else:
                self.open_tab(url.toString())

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() and any(u.isLocalFile() for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        # files dropped on the tab strip or toolbar (a page itself opens a file dropped on it)
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        if paths:
            self.open_paths(paths)
            ev.acceptProposedAction()

    # ------------------------------------------------------------ profiles
    def profile_info(self) -> dict | None:
        hub = getattr(self.ctx, "hub", None)
        return hub.info(self.ctx.pid) if hub is not None else None

    def _set_title(self, page_title: str):
        info = self.profile_info()
        name = f" ({info['name']})" if info and self.ctx.hub.many() else ""
        tail = "Pelagic" + name + (" — Private" if self.private else "")
        self.setWindowTitle(f"{page_title} — {tail}" if page_title else tail)

    def refresh_profile(self):
        info = self.profile_info()
        if info is None or self.profile_btn is None:
            return
        self.profile_btn.setIcon(_person_icon(info["color"]))
        self.profile_btn.setToolTip(f"Profile: {info['name']}" + (" (private window)" if self.private else ""))
        t = self.current_tab() if hasattr(self, "tabs") else None
        self._set_title(t.title() if t and t.title() else "")

    def _fill_profile_menu(self):
        from .profiles_ui import add_profile, ManageProfilesDialog
        hub, m = self.ctx.hub, self.profile_menu
        m.clear()
        me = hub.info(self.ctx.pid)
        head = m.addAction(f"● {me['name']}")
        head.setEnabled(False)
        others = [p for p in hub.profiles.items if p["id"] != self.ctx.pid]
        if others:
            m.addSeparator()
            for p in others:
                a = m.addAction(f"Open {p['name']}")
                a.triggered.connect(lambda _=False, pid=p["id"]: hub.open_profile(pid))
        m.addSeparator()
        m.addAction("Add profile…").triggered.connect(lambda: add_profile(hub, self))
        m.addAction("Manage profiles…").triggered.connect(lambda: ManageProfilesDialog(hub, self).exec())

    def changeEvent(self, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and not self.private:
            hub = getattr(self.ctx, "hub", None)
            if hub is not None:
                hub.window_activated(self.ctx)
        super().changeEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_refit_timer") and self.isVisible():
            self._refit_timer.start()

    def _screen_room(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _refit(self):
        """Put the window back inside its screen, like restoring and maximising again by hand."""
        if not self.isVisible() or self.isFullScreen() or self.isMinimized() or self._video_hidden is not None:
            return
        avail = self._screen_room()
        if avail is None:
            return
        # the panel never takes more than half the window, so the page always has room
        if self.dock.isVisible() and not self.dock.isFloating() and self.dock.width() > self.width() // 2:
            self.resizeDocks([self.dock], [max(self.dock.minimumWidth(), self.width() // 2)], Qt.Horizontal)
        if self.isMaximized():
            frame = self.frameGeometry()
            slack = 16   # a maximised frame overlaps the screen edge by a few pixels on Windows
            if frame.width() > avail.width() + slack or frame.height() > avail.height() + slack:
                now = time.monotonic()
                if now - getattr(self, "_last_refit", 0.0) < 2.0:   # it didn't take: don't keep flickering
                    return
                self._last_refit = now
                self.setWindowState(self.windowState() & ~Qt.WindowMaximized)
                self.setWindowState(self.windowState() | Qt.WindowMaximized)
        else:
            self._fit_on_screen()

    def _dock_visibility(self, visible: bool):
        if self.isVisible() and not self.private and self._video_hidden is None:
            self.store.set("panel", bool(visible))

    # ------------------------------------------------------------ small helpers
    def _tool(self, name, tip, slot):
        """Borderless icon button. The text is kept (hidden) as state, e.g. ★ when bookmarked."""
        b = QToolButton()
        if name:
            b.setIcon(icons.icon(name))
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(34, 32)
        b.setToolTip(tip)
        if slot:
            b.clicked.connect(lambda _=False: slot())
        return b

    def _cur(self, fn):
        t = self.current_tab()
        if t:
            fn(t)

    def current_tab(self) -> BrowserTab | None:
        return self.tabs.currentWidget()

    def tab_list(self) -> list[BrowserTab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def select_tab(self, tab):
        if tab is not None and self.tabs.indexOf(tab) >= 0:
            self.tabs.setCurrentWidget(tab)

    # ------------------------------------------------------------ URL handling
    def search_engine_name(self) -> str:
        return SEARCH_ENGINES.get(self.store.get("search_engine"), SEARCH_ENGINES["duckduckgo"])[0]

    def search_url(self, q: str) -> str:
        tmpl = SEARCH_ENGINES.get(self.store.get("search_engine"), SEARCH_ENGINES["duckduckgo"])[1]
        return tmpl % QUrl.toPercentEncoding(q).data().decode()

    def start_page_url(self) -> QUrl:
        eng = SEARCH_ENGINES.get(self.store.get("search_engine"), SEARCH_ENGINES["duckduckgo"])
        action, _, _ = eng[1].partition("?")
        path = self.store.root / "start.html"
        path.write_text(homepage.build(self.store, eng[0], action), encoding="utf-8")
        return QUrl.fromLocalFile(str(path))

    def home_url(self) -> QUrl:
        home = (self.store.get("home") or "atlas:start").strip()
        return self.start_page_url() if home.startswith("atlas:") else self.to_qurl(home)

    def is_start(self, url: QUrl) -> bool:
        return url.isLocalFile() and url.fileName() == "start.html"

    def to_qurl(self, text: str) -> QUrl:
        t = (text or "").strip()
        from . import playground   # the hidden challenges page (pelagic:playground)
        if playground.is_address(t):
            return playground.url()
        if not t or t.startswith("atlas:"):
            return self.start_page_url()
        from . import fileview
        path = fileview.to_url(t)   # a file on this computer (typed, or passed by "Open with Pelagic")
        if path is not None:
            return path
        if SCHEME.match(t) and not re.match(r"^[\w.-]+:\d+", t):
            return QUrl.fromUserInput(t)
        if " " not in t and HOSTLIKE.match(t):
            return QUrl.fromUserInput(t)
        return QUrl(self.search_url(t))

    def _go(self):
        self.omnibox.hide()
        url = self.to_qurl(self.addr.text())
        # picking a suggestion with Enter also sends Enter to the address bar: load it once
        now = time.monotonic()
        if getattr(self, "_last_go", None) and self._last_go[0] == url and now - self._last_go[1] < 0.5:
            return
        self._last_go = (url, now)
        t = self.current_tab()
        if t:
            t.load(url)
            t.setFocus()

    # ------------------------------------------------------------ tabs
    def open_tab(self, url: str | None = None, background: bool = False, blank: bool = False) -> BrowserTab:
        tab = BrowserTab(self.profile, factory=lambda opener, bg: self.open_tab(blank=True, background=bg),
                         parent=self.tabs)
        tab._pinned, tab._group, tab._title_full, tab._icon_full = False, None, "New tab", None
        touch(tab)
        idx = self.tabs.addTab(tab, "New tab")
        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Close tab")
        close.setStyleSheet("QToolButton{border:none;background:transparent;color:#8b93a7;padding:0 4px;font-size:11px}"
                            "QToolButton:hover{color:#fff;background:rgba(255,255,255,0.12);border-radius:4px}")
        close.clicked.connect(lambda _=False, t=tab: self.close_tab_obj(t))
        self.tabs.tabBar().setTabButton(idx, QTabBar.RightSide, close)
        tab.titleChanged.connect(lambda title, t=tab: self._title(t, title))
        tab.iconChanged.connect(lambda icon, t=tab: self._icon(t, icon))
        tab.urlChanged.connect(lambda u, t=tab: self._url_changed(t, u))
        tab.loadStarted.connect(lambda t=tab: (touch(t), self.ctx.blocker.reset(t.url().host()),
                                               self._load_state(t, True)))
        tab.loadProgress.connect(lambda p, t=tab: (self.progress.setValue(p), self.ext_btn.refresh())
                                 if t is self.current_tab() else None)
        tab.loadFinished.connect(lambda ok, t=tab: self._finished(t, ok))
        tab.ask_ai.connect(self._ask_ai)
        tab.page().recentlyAudibleChanged.connect(lambda _a, t=tab: self.strip.refresh(t))
        tab.inspect_requested.connect(lambda t=tab: self.toggle_devtools(element=True, tab=t))
        tab.home_action.connect(lambda action, i: homepage.handle_action(self, action, i))
        tab.reader_action.connect(lambda action, t=tab: tools.reader_action(self, t, action))
        tab.printRequested.connect(lambda t=tab: self.print_page(t))
        self.ctx.passwords.attach(tab, self)
        if not background:
            self.tabs.setCurrentIndex(idx)
        if not blank:
            tab.load(self.to_qurl(url) if url else self.home_url())
            if not url and not background:
                QTimer.singleShot(0, self.addr.setFocus)
        return tab

    def close_tab_obj(self, tab, remember: bool = True):
        i = self.tabs.indexOf(tab)
        if i < 0:
            return
        if self.tabs.count() <= 1:
            self.close()
            return
        if remember:
            self.strip.remember_closed(tab)
        self.tabs.removeTab(i)
        view = self._devtools.pop(tab, None)
        if view is not None:
            self.dev_stack.removeWidget(view)
            view.deleteLater()
        tab.stop()
        tab.deleteLater()
        self.strip.normalize()

    def _title(self, tab, title):
        i = self.tabs.indexOf(tab)
        if is_asleep(tab) and not title:
            return   # a sleeping tab keeps its title
        if i >= 0:
            tab._title_full = title or "New tab"
            self.strip.refresh(tab)
        if tab is self.current_tab():
            self._set_title(title)

    def _icon(self, tab, icon):
        i = self.tabs.indexOf(tab)
        if is_asleep(tab) and icon.isNull():
            return   # and its icon
        if i >= 0:
            tab._icon_full = icon
            self.strip.refresh(tab)
            url = tab.url().toString()
            # site icons for bookmarks and homepage shortcuts (one small file per site; none in private windows)
            if not self.private and not icon.isNull() and not self.store.favicon_path(url).exists():
                save_favicon(self.store, url, icon)
                if self.store.is_bookmarked(url):
                    self._rebuild_bookmarks()

    def _url_changed(self, tab, url):
        if tab is self.current_tab():
            self._sync_bar(tab)

    def _load_state(self, tab, loading):
        if tab is self.current_tab():
            self.reload_btn.setText("✕" if loading else "⟳")
            self.reload_btn.setIcon(icons.icon("stop" if loading else "reload"))
            self.reload_btn.setToolTip("Stop" if loading else "Reload (F5)")
            if loading:
                self.progress.setValue(5)

    def _finished(self, tab, ok):
        self._load_state(tab, False)
        if ok:
            self._auto_group_soon()
        if tab is self.current_tab():
            self.progress.setValue(0)
        url = tab.url()
        if ok and not self.private and url.scheme() in ("http", "https"):
            self.store.add_history(url.toString(), tab.title())
            self.completer_refresh()
        if ok and url.scheme() in ("http", "https"):
            self._hide_ads(tab)
            from .extensions_ui import offer_install
            offer_install(self, url)
        if tab is self.current_tab():
            self.ext_btn.refresh()

    def _hide_ads(self, tab):
        """Site-specific element hiding from the filter lists (network blocking happens in the interceptor)."""
        blocker, host = self.ctx.blocker, tab.url().host()
        engine = blocker.lists.engine
        if engine is None or not blocker.enabled() or blocker.paused_on(host):
            return
        css = engine.hide_css(host)
        if css:
            import json
            tab.run_js("(function(c){if(document.getElementById('__wf_hide'))return;var s=document.createElement('style');"
                       "s.id='__wf_hide';s.textContent=c;(document.head||document.documentElement).appendChild(s);})("
                       + json.dumps(css) + ")")

    def _tab_changed(self, _i):
        t = self.current_tab()
        prev = getattr(self, "_prev_tab", None)
        if prev is not None and prev is not t:
            touch(prev)   # its sleep timer starts when you leave it
        self._prev_tab = t
        if t:
            self.sleeper.wake(t)
        if t and hasattr(self, "dev_dock"):
            self._show_devtools(self._devtools.get(t) if getattr(t, "_devtools_open", False) else None)
        if t:
            self.ext_btn.refresh()
            self._sync_bar(t)
            self._load_state(t, t.loading)
            self._set_title(t.title() or "New tab")

    def _sync_bar(self, tab):
        url = tools.page_url(tab)
        if not self.addr.hasFocus():
            self.addr.setText("" if self.is_start(url) or url.toString() in ("about:blank", "") else url.toString())
            self.addr.setCursorPosition(0)
        marked = self.store.is_bookmarked(url.toString())
        self.star.setText("★" if marked else "☆")
        self.star.setIcon(icons.icon("star-filled" if marked else "star"))
        self.back_btn.setEnabled(tab.history().canGoBack())
        self.fwd_btn.setEnabled(tab.history().canGoForward())

    def _reload_or_stop(self):
        t = self.current_tab()
        if t:
            t.stop() if t.loading else t.reload()

    # ------------------------------------------------------------ bookmarks / find / zoom
    def toggle_bookmark(self, edit: bool = False):
        """Adds or removes the current page. From the star or Ctrl+D a newly added bookmark opens the editor, so
        it can be renamed or put in a folder straight away."""
        t = self.current_tab()
        if not t or self.is_start(t.url()) or not t.url().isValid():
            return
        url = tools.page_url(t).toString()
        added = self.store.toggle_bookmark(url, t.title())
        if added:
            save_favicon(self.store, url, t.icon())
        self._sync_bar(t)
        self._rebuild_bookmarks()
        if added and edit:
            self.bm.edit(url)

    def _rebuild_bookmarks(self):
        self.bm.rebuild()

    def show_find(self):
        self.find_bar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def hide_find(self):
        self.find_bar.hide()
        self._cur(lambda t: t.findText(""))

    def _find(self, backward: bool = False):
        flags = QWebEnginePage.FindFlag.FindBackward if backward else QWebEnginePage.FindFlag(0)
        self._cur(lambda t: t.findText(self.find_edit.text(), flags))

    def _zoom(self, delta):
        def f(t):
            t.setZoomFactor(1.0 if delta == 0 else max(0.25, min(5.0, t.zoomFactor() + delta)))
        self._cur(f)

    # ------------------------------------------------------------ panel / dialogs
    def toggle_panel(self, show: bool | None = None):
        self.dock.setVisible(not self.dock.isVisible() if show is None else show)
        if self.dock.isVisible():
            self.panel.input.setFocus()

    def _ask_ai(self, kind, text):
        self.toggle_panel(True)
        self.panel.ask_about(kind, text)

    def open_settings(self, start: str = "general"):
        if SettingsDialog(self.store, self, win=self, start=start).exec():
            homepage.refresh_open_pages(self)
            for w in self.ctx.windows:
                w.apply_tab_layout()
            from . import spellcheck
            spellcheck.ensure(self.store, [self.ctx.profile, self.ctx.private_profile], self.notify)
        self.panel.refresh_providers()
        self.panel.vision.setChecked(bool(self.store.get("vision")))
        self.panel.human.setChecked(bool(self.store.get("humanize")))
        self.panel.batch.setChecked(bool(self.store.get("batch")))

    def show_site_permissions(self):
        from .sitesettings import SitePermissionsDialog
        SitePermissionsDialog(self.profile, self).exec()

    def show_passwords(self):
        from .passwords_ui import PasswordsDialog
        PasswordsDialog(self.ctx.passwords, self).exec()

    def show_autofill(self):
        from .autofill_ui import AutofillDialog
        AutofillDialog(self.ctx.passwords.autofill, self).exec()

    def show_automations(self):
        from .automation_ui import AutomationsDialog
        AutomationsDialog(self, self).exec()

    def show_usage(self):
        UsageDialog(self.panel.session, self.panel.usage_log, self).exec()

    def show_history(self):
        d = HistoryDialog(self.store, self)
        d.open_url.connect(lambda u: (self.open_tab(u), d.close()))
        d.exec()

    def add_to_reading_list(self, tab=None):
        t = tab or self.current_tab()
        if not t or self.is_start(t.url()) or t.url().scheme() not in ("http", "https", "file"):
            return
        added = self.store.add_to_reading_list(tools.page_url(t).toString(), t.title())
        self.notify(f"Added “{t.title()[:60]}” to your reading list." if added else "That page is already in your reading list.")
        QTimer.singleShot(4000, self.notice.hide)

    def show_reading_list(self):
        d = ReadingListDialog(self.store, self)
        d.open_url.connect(lambda u: (self.open_tab(u), d.close()))
        d.exec()

    def show_bookmarks(self):
        d = BookmarksDialog(self.store, self)
        d.open_url.connect(lambda u: (self.open_tab(u), d.close()))
        d.changed.connect(self._rebuild_bookmarks)
        d.exec()
        self._rebuild_bookmarks()
        self._cur(self._sync_bar)

    def open_devtools(self):
        self.toggle_devtools()

    def toggle_devtools(self, element: bool = False, tab=None):
        """Ctrl+Shift+I / F12 open or close the current tab's developer tools; Ctrl+Shift+C (element=True) opens
        them with the element picker on, like Chrome."""
        t = tab or self.current_tab()
        if not t:
            return
        view = self._devtools.get(t)
        if view is not None and getattr(t, "_devtools_open", False) and self.dev_dock.isVisible() and not element:
            t._devtools_open = False
            self._show_devtools(None)
            return
        if view is None:
            view = QWebEngineView()
            t.page().setDevToolsPage(view.page())
            self.dev_stack.addWidget(view)
            self._devtools[t] = view
            view._ready = False
            view.loadFinished.connect(lambda _ok, v=view: setattr(v, "_ready", True))
            view.page().windowCloseRequested.connect(lambda tab=t: self.close_devtools(tab))   # DevTools' own ✕
        t._devtools_open = True
        self._show_devtools(view)
        if element:
            self._element_picker(view)

    def close_devtools(self, tab=None):
        t = tab or self.current_tab()
        if t is None:
            return
        t._devtools_open = False
        if t is self.current_tab():
            self._show_devtools(None)

    # Turns DevTools' "select an element" mode on (never off), so Ctrl+Shift+C always lets you pick again.
    PICKER_JS = """import('devtools://devtools/bundled/ui/legacy/legacy.js').then(function (m) {
      var a = m.ActionRegistry.ActionRegistry.instance().getAction('elements.toggle-element-search');
      if (a && !a.toggled()) a.execute();
    }).catch(function () { window.__pelagicPickerFailed = true; }); true"""

    def _element_picker(self, view, tries: int = 0):
        if not getattr(view, "_ready", False) and tries < 40:
            QTimer.singleShot(150, lambda: self._element_picker(view, tries + 1))
            return
        QTimer.singleShot(400, lambda: view.page().runJavaScript(self.PICKER_JS))   # once the DevTools UI has started

    def _show_devtools(self, view):
        self._dev_switching = True
        if view is None:
            self.dev_dock.hide()
        else:
            self.dev_stack.setCurrentWidget(view)
            self.dev_dock.show()
            if not getattr(self, "_dev_sized", False):
                self._dev_sized = True
                self.resizeDocks([self.dev_dock], [max(260, self.height() // 3)], Qt.Vertical)
        self._dev_switching = False

    def _dev_visibility(self, visible):
        t = self.current_tab()
        if not visible and not self._dev_switching and t is not None and not self.isMinimized() \
                and self._video_hidden is None:
            t._devtools_open = False   # closed with the dock's ✕

    def inspect_element(self):
        """Right-click → Inspect: open DevTools and select the element under the menu."""
        t = self.current_tab()
        if not t:
            return
        if not getattr(t, "_devtools_open", False) or not self.dev_dock.isVisible():
            self.toggle_devtools()
        t.page().triggerAction(QWebEnginePage.WebAction.InspectElement)

    def view_source(self):
        t = self.current_tab()
        if t and t.url().scheme() in ("http", "https", "file", "data"):
            self.open_tab("view-source:" + t.url().toString())

    def save_page(self):
        t = self.current_tab()
        if not t:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save page as", (t.title() or "page") + ".html",
                                              "Web page, complete (*.html);;Web page, single file (*.mhtml)")
        if path:
            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
            fmt = QWebEngineDownloadRequest.SavePageFormat
            t.page().save(path, fmt.MimeHtmlSaveFormat if path.lower().endswith(".mhtml") else fmt.CompleteHtmlSaveFormat)

    def toggle_bookmarks_bar(self):
        self.store.set("bookmarks_bar", not self.store.get("bookmarks_bar"))
        self._rebuild_bookmarks()

    def _move_tab(self, delta):
        i = self.tabs.currentIndex()
        j = i + delta
        if 0 <= j < self.tabs.count():
            self.tabs.tabBar().moveTab(i, j)
            self.strip.after_drag()

    def print_page(self, tab=None):
        """Ctrl+P, or a page's own Print button: the system print dialog (pick a printer, or Microsoft Print to
        PDF)."""
        t = tab or self.current_tab()
        if not t:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(t.title() or "Page")
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        t._printer = printer   # kept until printing is done
        t.printFinished.connect(lambda _ok, t=t: setattr(t, "_printer", None))
        t.print(printer)

    def print_pdf(self):
        t = self.current_tab()
        if not t:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save page as PDF", (t.title() or "page") + ".pdf", "PDF (*.pdf)")
        if path:
            t.page().printToPdf(path)

    # ------------------------------------------------------------ menu & shortcuts
    def _build_menu(self):
        m = QMenu(self)

        def add(text, slot, key=None):
            # Shortcuts are registered once in _shortcuts(); the menu only displays them.
            a = m.addAction(text + (f"\t{key}" if key else ""))
            a.triggered.connect(lambda _=False: slot())
            return a
        add("New tab", lambda: self.open_tab(), "Ctrl+T")
        add("New window", lambda: self.ctx.new_window(), "Ctrl+N")
        add("New private window", self.ctx.new_private_window, "Ctrl+Shift+N")
        add("Reopen closed tab", self.strip.reopen_closed, "Ctrl+Shift+T")
        add("Search tabs…", self.strip.search_tabs)
        add("Split view", lambda: self.strip.split_view(), "Ctrl+Shift+E")
        add("Group tabs by site", self.strip.group_by_site)
        autog = m.addAction("Keep tabs grouped by site")
        autog.setCheckable(True)
        autog.setToolTip("Tabs from the same site are put into a group as they open")
        autog.triggered.connect(self.set_auto_group)
        m.aboutToShow.connect(lambda: autog.setChecked(bool(self.store.get("auto_group_tabs"))))
        vert = m.addAction("Vertical tabs")
        vert.setCheckable(True)
        vert.triggered.connect(self.set_vertical_tabs)
        m.aboutToShow.connect(lambda: vert.setChecked(bool(self.store.get("vertical_tabs"))))
        if not self.private:
            ws = m.addMenu("Workspaces")
            ws.aboutToShow.connect(lambda: tabviews.fill_menu(self, ws))
            m.aboutToShow.connect(lambda: ws.setTitle(f"Workspace: {tabviews.current_workspace(self.store)}"))
        m.addSeparator()
        add("Bookmarks…", self.show_bookmarks, "Ctrl+Shift+O")
        add("History…", self.show_history, "Ctrl+H")
        add("Reading list…", self.show_reading_list)
        add("Add page to reading list", self.add_to_reading_list, "Alt+Shift+R")
        add("Downloads…", self.ctx.show_downloads, "Ctrl+J")
        add("Download video or audio…", self.download_media)
        add("Passwords…", self.show_passwords)
        add("Addresses and cards…", self.show_autofill)
        add("Site permissions…", self.show_site_permissions)
        m.addSeparator()
        add("Find in page", self.show_find, "Ctrl+F")
        add("Reader mode", lambda: tools.toggle_reader(self), "F9")
        add("Translate page…", lambda: tools.translate_page(self))
        shots = m.addMenu("Screenshot")
        for text, kind, key in (("Select an area", "area", "Ctrl+Shift+S"), ("Visible part of the page", "visible", None),
                                ("Whole page", "full", None)):
            shots.addAction(text + (f"\t{key}" if key else "")).triggered.connect(
                lambda _=False, k=kind: tools.screenshot(self, k))
        add("Picture-in-picture", lambda: tools.picture_in_picture(self))
        add("Zoom in", lambda: self._zoom(0.1))
        add("Zoom out", lambda: self._zoom(-0.1))
        add("Reset zoom", lambda: self._zoom(0))
        add("Open file…", self.open_file, "Ctrl+O")
        add("Save page as…", self.save_page, "Ctrl+S")
        add("Print…", self.print_page, "Ctrl+P")
        add("Save page as PDF…", self.print_pdf)
        add("Show bookmarks bar", self.toggle_bookmarks_bar, "Ctrl+Shift+B")
        m.addSeparator()
        add("Developer tools", self.toggle_devtools, "Ctrl+Shift+I")
        add("Inspect element", lambda: self.toggle_devtools(element=True), "Ctrl+Shift+C")
        add("View page source", self.view_source, "Ctrl+U")
        m.addSeparator()
        add("Pelagic AI panel", lambda: self.toggle_panel(), "Ctrl+Shift+A")
        add("Automations…", self.show_automations)
        add("Token usage…", self.show_usage)
        add("Settings…", self.open_settings, "Ctrl+,")
        m.addSeparator()
        add("About Pelagic", lambda: QMessageBox.about(
            self, "Pelagic", "Pelagic — a Chromium-based browser with a built-in AI agent.\n"
            "Works with Gemini, Claude, OpenAI, OpenRouter, Groq, Mistral, DeepSeek, xAI, Ollama and many more."))
        self.menu_btn.setMenu(m)
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)

    def _shortcuts(self):
        def sc(key, fn):
            QShortcut(QKeySequence(key), self).activated.connect(fn)
        sc("Ctrl+T", lambda: self.open_tab())
        sc("Alt+Shift+R", self.add_to_reading_list)
        sc("Ctrl+W", lambda: self._cur(self.close_tab_obj))
        sc("Ctrl+Tab", lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count()))
        sc("Ctrl+Shift+Tab", lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count()))
        sc("Ctrl+L", lambda: (self.addr.setFocus(), self.addr.selectAll()))
        sc("F6", lambda: (self.addr.setFocus(), self.addr.selectAll()))
        sc("F5", self._reload_or_stop)
        sc("Ctrl+R", self._reload_or_stop)
        sc("Alt+Left", lambda: self._cur(lambda t: t.back()))
        sc("Alt+Right", lambda: self._cur(lambda t: t.forward()))
        sc("Ctrl+D", lambda: self.toggle_bookmark(edit=True))
        sc("Ctrl+H", self.show_history)
        sc("Ctrl+Shift+O", self.show_bookmarks)
        sc("Ctrl+J", self.ctx.show_downloads)
        sc("Ctrl+F", self.show_find)
        sc("Ctrl+O", self.open_file)
        sc("F9", lambda: tools.toggle_reader(self))
        sc("Ctrl+Shift+E", lambda: self.strip.split_view())
        sc("Ctrl+Shift+S", lambda: tools.screenshot(self, "area"))
        sc("F11", lambda: self.set_fullscreen(not self.isFullScreen()))
        self._esc_fs = QShortcut(QKeySequence("Escape"), self)
        self._esc_fs.setEnabled(False)   # only while full screen, so Esc still reaches web pages normally
        self._esc_fs.activated.connect(lambda: self.set_fullscreen(False))
        esc = QShortcut(QKeySequence("Escape"), self.find_bar)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.hide_find)
        sc("Ctrl+=", lambda: self._zoom(0.1))
        sc("Ctrl++", lambda: self._zoom(0.1))
        sc("Ctrl+-", lambda: self._zoom(-0.1))
        sc("Ctrl+0", lambda: self._zoom(0))
        sc("F12", self.toggle_devtools)
        sc("Ctrl+Shift+I", self.toggle_devtools)
        sc("Ctrl+Shift+J", self.toggle_devtools)
        sc("Ctrl+Shift+C", lambda: self.toggle_devtools(element=True))
        sc("Ctrl+U", self.view_source)
        sc("Ctrl+S", self.save_page)
        sc("Ctrl+Shift+B", self.toggle_bookmarks_bar)
        sc("Ctrl+N", lambda: self.ctx.new_window())
        sc("Ctrl+Shift+T", self.strip.reopen_closed)
        sc("Ctrl+Shift+W", self.close)
        sc("Alt+Home", lambda: self._cur(lambda t: t.load(self.home_url())))
        sc("Ctrl+PgDown", lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count()))
        sc("Ctrl+PgUp", lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count()))
        sc("Ctrl+Shift+PgDown", lambda: self._move_tab(1))
        sc("Ctrl+Shift+PgUp", lambda: self._move_tab(-1))
        sc("Ctrl+Shift+Del", lambda: self.open_settings("privacy"))
        sc("Ctrl+P", self.print_page)
        sc("Ctrl+Shift+A", lambda: self.toggle_panel())
        sc("Ctrl+Shift+N", self.ctx.new_private_window)
        sc("Ctrl+,", self.open_settings)
        for n in range(1, 10):
            sc(f"Ctrl+{n}", lambda n=n: self.tabs.setCurrentIndex(self.tabs.count() - 1 if n == 9 else n - 1)
               if (n == 9 or n - 1 < self.tabs.count()) else None)

    # ------------------------------------------------------------ lifecycle
    def completer_refresh(self):
        """Autocomplete reads history and bookmarks live as you type (omnibox.py), so there is nothing to cache."""

    def set_fullscreen(self, on: bool, page: bool = False):
        """Full screen (F11, or a page's video with page=True) and back to the window state it had before.
        A page's full screen also hides the tabs, toolbar, bookmarks bar and side panels, so the video gets the
        whole screen, like Chrome."""
        if on and page:
            self._hide_browser_ui()
        if not on:
            self._show_browser_ui()
        if on == self.isFullScreen():
            return
        if on:
            self._normal_geom = self.saveGeometry()
            self.showFullScreen()
        else:
            self.showNormal()
            if self._normal_geom is not None:
                self.restoreGeometry(self._normal_geom)
            t = self.current_tab()
            if t:   # let a full-screen video know too (its own exit request then finds us already windowed)
                t.page().triggerAction(QWebEnginePage.WebAction.ExitFullScreen)
        self._esc_fs.setEnabled(on)
        self.window_buttons.setVisible(on)   # only matters in F11: a video's full screen hides the whole tab row
        self.apply_tab_layout()
        from .tabstrip import relayout
        relayout(self.tabs.tabBar())

    def _window_buttons(self) -> QWidget:
        """Windows-style minimize / restore / close for F11 full screen, where the title bar is gone."""
        box = QWidget()
        box.setObjectName("winbuttons")
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        for name, tip, slot, hover in (("minimize", "Minimize", self.showMinimized, "rgba(255,255,255,0.10)"),
                                       ("restore", "Exit full screen (F11)", lambda: self.set_fullscreen(False),
                                        "rgba(255,255,255,0.10)"),
                                       ("window-close", "Close", self.close, "#c42b1c")):
            b = QToolButton()
            b.setObjectName(name)
            b.setIcon(icons.icon(name))
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(46, 34)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=slot: f())
            b.setStyleSheet(f"QToolButton{{background:transparent;border:none;border-radius:0;margin:0}}"
                            f"QToolButton:hover{{background:{hover}}}"
                            f"QToolButton:pressed{{background:{'#8f1d14' if name == 'window-close' else 'rgba(255,255,255,0.16)'}}}")
            h.addWidget(b)
        box.hide()
        return box

    def apply_tab_layout(self):
        """Tabs along the top, or down the left side ("vertical_tabs"). With vertical tabs the top row is hidden,
        except in F11 full screen, where it holds the minimize / restore / close buttons."""
        if self._video_hidden is not None:
            return
        vertical = bool(self.store.get("vertical_tabs"))
        self.vtabs.setVisible(vertical)
        self.tabs.tabBar().setVisible(not vertical)
        self.tabs.row.setVisible(not vertical or self.isFullScreen())

    def set_auto_group(self, on: bool):
        self.store.set("auto_group_tabs", bool(on))
        if on:
            for w in self.ctx.windows:
                w.strip.group_by_site()

    def _auto_group_soon(self):
        if self.store.get("auto_group_tabs"):
            if not hasattr(self, "_auto_group_timer"):
                self._auto_group_timer = QTimer(self, singleShot=True, interval=400, timeout=self.strip.group_by_site)
            self._auto_group_timer.start()

    def set_vertical_tabs(self, on: bool):
        self.store.set("vertical_tabs", bool(on))
        for w in self.ctx.windows:
            w.apply_tab_layout()

    def _browser_ui(self):
        return [self.tabs.row, self.vtabs, self.toolbar, self.progress, self.bm_bar, self.find_bar, self.save_bar,
                self.dock, self.dev_dock]

    def _hide_browser_ui(self):
        if self._video_hidden is not None:
            return
        self._video_hidden = [w for w in self._browser_ui() if w.isVisible()]
        for w in self._video_hidden:
            w.hide()

    def _show_browser_ui(self):
        hidden, self._video_hidden = self._video_hidden, None
        for w in hidden or []:
            w.show()

    def save_session(self):
        """Open tabs, pins and groups, restored on the next start (only the first window's)."""
        if self.private or self.ctx.main_window is not self:
            return
        kept = [t for t in self.tab_list() if tools.page_url(t).scheme() in ("http", "https")]
        urls, layout = [tools.page_url(t).toString() for t in kept], self.strip.layout_state(kept)
        if urls != self.store.get("session") or layout != self.store.get("session_layout"):
            self.store.set("session", urls)
            self.store.set("session_layout", layout)

    def notify(self, text: str):
        self.notice_text.setText(text)
        self.notice.show()

    def closeEvent(self, ev):
        if not self.private:
            geom = self._normal_geom if self.isFullScreen() and self._normal_geom is not None else self.saveGeometry()
            self.store.set("window", {"geom": bytes(geom.toBase64()).decode()})
            self.save_session()
        self.panel.stop()
        self.previews.close()
        for view in self._devtools.values():
            view.close()
        for t in self.tab_list():
            t.stop()
        self.ctx.window_closed(self)
        super().closeEvent(ev)
