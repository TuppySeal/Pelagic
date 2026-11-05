"""Screen sharing (Discord, Meet, Teams…): when a page asks to share your screen, you pick the whole screen or one
window here. Nothing is shared until you click Share; Cancel tells the page you said no."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QTabWidget,
                               QVBoxLayout)

ROLE = Qt.ItemDataRole.UserRole


def _names(model) -> list[str]:
    return [str(model.data(model.index(r, 0), Qt.ItemDataRole.DisplayRole) or f"Item {r + 1}")
            for r in range(model.rowCount())]


def _screen_thumb(n: int) -> QIcon:
    screens = QGuiApplication.screens()
    if n >= len(screens):
        return QIcon()
    try:
        shot = screens[n].grabWindow(0)
    except Exception:   # noqa: BLE001 - some systems don't allow screen grabs; the name is enough
        return QIcon()
    return QIcon(shot.scaled(QSize(240, 135), Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not shot.isNull() \
        else QIcon()


class SharePicker(QDialog):
    def __init__(self, site: str, screens: list[str], windows: list[str], parent=None, thumbs: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Share your screen")
        self.resize(640, 460)
        self.choice: tuple[str, int] | None = None
        v = QVBoxLayout(self)
        head = QLabel(f"<b>{site or 'This page'}</b> wants to see your screen. Choose what to share.")
        head.setWordWrap(True)
        v.addWidget(head)
        self.tabs = QTabWidget()
        self.screen_list = QListWidget()
        self.screen_list.setViewMode(QListWidget.IconMode)
        self.screen_list.setIconSize(QSize(240, 135))
        self.screen_list.setGridSize(QSize(270, 180))
        self.screen_list.setMovement(QListWidget.Static)
        self.screen_list.setResizeMode(QListWidget.Adjust)
        for n, name in enumerate(screens):
            label = "Entire screen" if len(screens) == 1 else f"Screen {n + 1}"
            it = QListWidgetItem(_screen_thumb(n) if thumbs else QIcon(), label)
            it.setToolTip(name)
            it.setData(ROLE, ("screen", n))
            self.screen_list.addItem(it)
        self.window_list = QListWidget()
        for n, name in enumerate(windows):
            it = QListWidgetItem(name)
            it.setData(ROLE, ("window", n))
            self.window_list.addItem(it)
        if not windows:
            self.window_list.addItem(QListWidgetItem("No windows to share"))
            self.window_list.item(0).setFlags(Qt.NoItemFlags)
        self.tabs.addTab(self.screen_list, "Entire screen")
        self.tabs.addTab(self.window_list, "Window")
        v.addWidget(self.tabs, 1)
        note = QLabel("Sound from your computer is shared too when the site asks for it. To stop sharing, use the "
                      "site's own Stop button or close the tab.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        v.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.share_btn = self.buttons.addButton("Share", QDialogButtonBox.AcceptRole)
        self.share_btn.setObjectName("primary")
        self.share_btn.setEnabled(False)
        self.buttons.accepted.connect(self._share)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)
        for lst in (self.screen_list, self.window_list):
            lst.currentItemChanged.connect(self._picked)
            lst.itemDoubleClicked.connect(lambda _it: self._share())
        self.tabs.currentChanged.connect(lambda _i: self._picked())
        if self.screen_list.count():
            self.screen_list.setCurrentRow(0)

    def _current(self):
        lst = self.screen_list if self.tabs.currentIndex() == 0 else self.window_list
        it = lst.currentItem()
        return it.data(ROLE) if it is not None else None

    def _picked(self, *_):
        self.share_btn.setEnabled(self._current() is not None)

    def _share(self):
        self.choice = self._current()
        if self.choice is not None:
            self.accept()


def handle_request(page, request, parent=None, ask=None):
    """QWebEnginePage.desktopMediaRequested: ask which screen or window, then share it (or cancel)."""
    site = page.url().host()
    screens_model, windows_model = request.screensModel(), request.windowsModel()
    screens, windows = _names(screens_model), _names(windows_model)
    if ask is None:
        def ask(site, screens, windows):
            dlg = SharePicker(site, screens, windows, parent)
            return dlg.choice if dlg.exec() == QDialog.Accepted else None
    choice = ask(site, screens, windows)
    if choice is None:
        request.cancel()
    elif choice[0] == "screen":
        request.selectScreen(screens_model.index(choice[1], 0))
    else:
        request.selectWindow(windows_model.index(choice[1], 0))
