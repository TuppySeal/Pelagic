"""The Sync tab in Settings: pick the folder, the optional passphrase for passwords and cards, and Sync now.
Changes here take effect straight away (they don't wait for OK)."""
from __future__ import annotations

import os
import time

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)


def suggested_folder() -> str:
    """OneDrive if it's set up (it usually is on Windows), else nothing."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        p = os.environ.get(var)
        if p and os.path.isdir(p):
            return p
    return ""


class SyncPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.store, self.sync = ctx, ctx.store, ctx.sync
        v = QVBoxLayout(self)
        intro = QLabel("Keep bookmarks, the reading list and history the same on your computers. Pick a folder that "
                       "OneDrive, Google Drive or Dropbox keeps in sync, then pick the same folder in Pelagic on "
                       "your other computer. Nothing is sent anywhere else.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.path = QLineEdit(self.store.get("sync_folder") or "")
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Sync is off")
        choose = QPushButton("Choose folder…")
        choose.clicked.connect(self.choose)
        self.off = QPushButton("Turn off")
        self.off.clicked.connect(self.turn_off)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(choose)
        row.addWidget(self.off)
        v.addLayout(row)

        v.addSpacing(8)
        self.secrets = QCheckBox("Also sync passwords, addresses and cards, encrypted with a sync passphrase")
        self.secrets.setChecked(bool(self.store.get("sync_secrets")) and self.sync.vault_key() is not None)
        self.secrets.toggled.connect(self._secrets_toggled)
        v.addWidget(self.secrets)
        self.phrase = QLineEdit()
        self.phrase.setEchoMode(QLineEdit.Password)
        self.phrase.setPlaceholderText("Sync passphrase (use the same one on each computer)")
        self.phrase_btn = QPushButton("Use passphrase")
        self.phrase_btn.clicked.connect(self.use_phrase)
        self.phrase_row = QWidget()
        pr = QHBoxLayout(self.phrase_row)
        pr.setContentsMargins(22, 0, 0, 0)
        pr.addWidget(self.phrase, 1)
        pr.addWidget(self.phrase_btn)
        v.addWidget(self.phrase_row)
        note = QLabel("The passphrase never leaves this computer, and without it the synced passwords can't be read. "
                      "Pelagic can't recover it if it's forgotten.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setContentsMargins(22, 0, 0, 0)
        v.addWidget(note)

        v.addSpacing(8)
        self.now = QPushButton("Sync now")
        self.now.setObjectName("primary")
        self.now.clicked.connect(self.sync_now)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.now)
        row.addWidget(self.status, 1)
        v.addLayout(row)
        v.addStretch(1)
        self.refresh()

    def refresh(self):
        on = bool(self.store.get("sync_folder"))
        self.off.setEnabled(on)
        self.now.setEnabled(on)
        self.secrets.setEnabled(on)
        self.phrase_row.setVisible(on and self.secrets.isChecked() and self.sync.vault_key() is None)
        if not self.status.text():
            last = self.store.get("sync_last")
            self.status.setText(self.sync.last_report or (f"Last synced {time.strftime('%d %b %H:%M', time.localtime(last))}."
                                                          if on and last else ""))

    def choose(self):
        start = self.store.get("sync_folder") or suggested_folder()
        path = QFileDialog.getExistingDirectory(self, "Sync folder", start)
        if not path:
            return
        if path != self.store.get("sync_folder"):
            self.sync.forget_passphrase()     # a different folder has its own passphrase
            self.store.set("sync_folder", path)
            self.path.setText(path)
        self.refresh()
        self.sync_now()

    def turn_off(self):
        self.store.set("sync_folder", "")
        self.store.set("sync_secrets", False)
        self.sync.forget_passphrase()
        self.path.clear()
        self.secrets.setChecked(False)
        self.status.setText("Sync is off. What was already synced stays on this computer.")
        self.refresh()

    def _secrets_toggled(self, on):
        if not on:
            self.store.set("sync_secrets", False)
        elif self.sync.vault_key() is not None:
            self.store.set("sync_secrets", True)
        self.refresh()
        if on and self.sync.vault_key() is None:
            self.phrase.setFocus()

    def use_phrase(self):
        phrase = self.phrase.text()
        if len(phrase) < 8:
            self.status.setText("Use a passphrase of at least 8 characters.")
            return
        problem = self.sync.set_passphrase(phrase)
        self.phrase.clear()
        if problem:
            self.status.setText(problem)
            return
        self.store.set("sync_secrets", True)
        self.refresh()
        self.sync_now()

    def sync_now(self):
        self.status.setText("Syncing…")
        self.now.setEnabled(False)

        def done(report):
            try:
                self.status.setText(report)
                self.now.setEnabled(bool(self.store.get("sync_folder")))
            except RuntimeError:
                pass   # the settings window was closed meanwhile
        self.ctx.sync_now(done)
