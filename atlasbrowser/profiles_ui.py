"""Add / rename / recolour / delete profiles."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .profiles import DEFAULT_ID


def _swatch(color: str) -> QIcon:
    pix = QPixmap(14, 14)
    pix.fill(QColor(color))
    return QIcon(pix)


def _refresh_windows(hub):
    for ctx in hub.contexts.values():
        for w in ctx.windows:
            w.refresh_profile()


def add_profile(hub, parent) -> str | None:
    name, ok = QInputDialog.getText(parent, "Add profile", "Profile name (for example Work):")
    if not ok or not name.strip():
        return None
    p = hub.profiles.add(name)
    _refresh_windows(hub)
    hub.open_profile(p["id"])
    return p["id"]


class ManageProfilesDialog(QDialog):
    def __init__(self, hub, win):
        super().__init__(win)
        self.hub, self.win = hub, win
        self.setWindowTitle("Profiles")
        self.resize(460, 360)
        note = QLabel("Each profile has its own passwords, history, bookmarks, sign-ins, tabs and automations. "
                      "API keys and AI settings are shared by all profiles.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda it: (hub.open_profile(it.data(Qt.UserRole)), self.accept()))
        row = QHBoxLayout()
        for text, slot in (("Open", self._open), ("Add…", self._add), ("Rename…", self._rename),
                           ("Color…", self._color), ("Delete…", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)
        lay.addWidget(close)
        self.reload()

    def reload(self):
        self.list.clear()
        for p in self.hub.profiles.items:
            it = QListWidgetItem(_swatch(p["color"]), p["name"] + ("   (this window)" if p["id"] == self.win.ctx.pid else ""))
            it.setData(Qt.UserRole, p["id"])
            self.list.addItem(it)

    def _pid(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _open(self):
        pid = self._pid()
        if pid:
            self.hub.open_profile(pid)
            self.accept()

    def _add(self):
        if add_profile(self.hub, self):
            self.accept()

    def _rename(self):
        pid = self._pid()
        if not pid:
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "Name:", text=self.hub.info(pid)["name"])
        if ok and name.strip():
            self.hub.profiles.update(pid, name=name.strip())
            _refresh_windows(self.hub)
            self.reload()

    def _color(self):
        pid = self._pid()
        if not pid:
            return
        c = QColorDialog.getColor(QColor(self.hub.info(pid)["color"]), self, "Profile color")
        if c.isValid():
            self.hub.profiles.update(pid, color=c.name())
            _refresh_windows(self.hub)
            self.reload()

    def _delete(self):
        pid = self._pid()
        if not pid:
            return
        name = self.hub.info(pid)["name"]
        if pid == DEFAULT_ID:
            QMessageBox.information(self, "Delete profile", f"{name} is the original profile and can't be deleted.")
            return
        if QMessageBox.warning(
                self, "Delete profile",
                f"Delete the {name} profile? Its saved passwords, history, bookmarks, sign-ins and automations "
                "will be erased. This can't be undone.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        closing_self = pid == self.win.ctx.pid
        self.hub.delete_profile(pid)
        _refresh_windows(self.hub)
        if closing_self:
            self.accept()
        else:
            self.reload()
