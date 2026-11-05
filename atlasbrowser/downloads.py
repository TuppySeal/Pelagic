"""The downloads page (Ctrl+J): progress, speed and time left, pause / resume / cancel, retry, open, show in folder,
and a remembered list of past downloads (not from private windows).

Settings: "download_ask" (ask where to save each file; otherwise straight to the Downloads folder) and
"downloads_history" (the remembered list, newest first).
"""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QFileInfo, QProcess, QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileIconProvider, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

State = QWebEngineDownloadRequest.DownloadState
HISTORY_LIMIT = 200


def downloads_folder() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or os.path.expanduser("~")


def unique_path(folder: str, name: str) -> str:
    """name, or "name (1).ext", "name (2).ext"… if a file with that name is already there (like Chrome)."""
    stem, ext = os.path.splitext(name or "download")
    path, n = os.path.join(folder, stem + ext), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return path


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def human_time(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def show_in_folder(path: str):
    if sys.platform == "win32" and os.path.exists(path):
        QProcess.startDetached("explorer", ["/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


class DownloadRow(QFrame):
    """One download. `req` is the live request while it runs; `entry` is what's remembered afterwards."""

    def __init__(self, page, entry: dict, req=None):
        super().__init__()
        self.page, self.entry, self.req = page, entry, req
        self.setObjectName("dlrow")
        self.setStyleSheet("#dlrow{background:#1b1e26;border:1px solid #262a35;border-radius:8px}"
                           "QLabel{background:transparent}")
        self._last = (time.monotonic(), 0)
        self.speed = 0.0
        icon = QLabel()
        icon.setPixmap(QFileIconProvider().icon(QFileInfo(entry["path"])).pixmap(QSize(32, 32)))
        icon.setFixedSize(36, 36)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight:600")
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(4)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.name)
        text.addWidget(self.status)
        text.addWidget(self.bar)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.addWidget(icon, 0, Qt.AlignTop)
        row.addLayout(text, 1)
        row.addLayout(self.buttons)
        if req is not None:
            req.receivedBytesChanged.connect(self.refresh)
            req.stateChanged.connect(self.refresh)
            req.isPausedChanged.connect(self.refresh)
        self.refresh()

    # -- state
    def state(self) -> str:
        """'running' | 'paused' | 'done' | 'cancelled' | 'failed' | 'missing'"""
        if self.req is not None:
            st = self.req.state()
            if st == State.DownloadCompleted:
                return "done"
            if st == State.DownloadCancelled:
                return "cancelled"
            if st == State.DownloadInterrupted:
                return "failed"
            return "paused" if self.req.isPaused() else "running"
        st = self.entry.get("state", "done")
        return "missing" if st == "done" and not os.path.exists(self.entry["path"]) else st

    def refresh(self, *_):
        st = self.state()
        e = self.entry
        e["name"] = os.path.basename(e["path"])
        self.name.setText(e["name"])
        if self.req is not None:
            got, total = self.req.receivedBytes(), self.req.totalBytes()
            e["size"] = total if total > 0 else got
            now = time.monotonic()
            t0, b0 = self._last
            if now - t0 >= 0.8:
                self.speed = 0.6 * self.speed + 0.4 * max(0, got - b0) / (now - t0)
                self._last = (now, got)
        else:
            got, total = e.get("size", 0), e.get("size", 0)
        if st == "running":
            parts = [f"{human_size(got)} of {human_size(total)}" if total > 0 else human_size(got)]
            if self.speed > 0:
                parts.append(f"{human_size(self.speed)}/s")
                if total > 0:
                    parts.append(f"{human_time((total - got) / self.speed)} left")
            self.status.setText(" · ".join(parts))
        elif st == "paused":
            self.status.setText(f"Paused · {human_size(got)}" + (f" of {human_size(total)}" if total > 0 else ""))
        elif st == "done":
            self.status.setText(f"Done · {human_size(e.get('size', 0))} · {e.get('host', '')}".rstrip(" ·"))
        elif st == "missing":
            self.status.setText("Removed from your computer")
        elif st == "cancelled":
            self.status.setText("Cancelled")
        else:
            why = self.req.interruptReasonString() if self.req is not None else e.get("error", "")
            self.status.setText("Failed" + (f": {why}" if why else ""))
        active = st in ("running", "paused")
        self.bar.setVisible(active)
        if active:
            self.bar.setRange(0, 100 if total > 0 else 0)
            self.bar.setValue(int(got * 100 / total) if total > 0 else 0)
        self.name.setStyleSheet("font-weight:600" + (";text-decoration:line-through;color:#8b93a7"
                                                     if st in ("missing", "cancelled") else ""))
        if st != getattr(self, "_shown", None):
            self._shown = st
            self._buttons(st)
            if not active and self.req is not None:
                e["state"] = st
                if st == "failed":
                    e["error"] = self.req.interruptReasonString()
                self.page.remember()

    def _buttons(self, st):
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

        def add(text, slot, tip=""):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            self.buttons.addWidget(b)
            return b
        if st == "running":
            add("Pause", lambda: self.req.pause())
            add("Cancel", lambda: self.req.cancel())
        elif st == "paused":
            add("Resume", lambda: self.req.resume()).setObjectName("primary")
            add("Cancel", lambda: self.req.cancel())
        elif st == "done":
            add("Open", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.entry["path"])))
            add("Show in folder", lambda: show_in_folder(self.entry["path"]))
        elif st in ("failed", "cancelled", "missing") and self.entry.get("url"):
            add("Retry", lambda: self.page.retry(self), "Download it again")
        if st not in ("running", "paused"):
            add("✕", lambda: self.page.remove(self), "Remove from this list (the file stays)").setFixedWidth(32)


class DownloadsPage(QDialog):
    def __init__(self, store=None, parent=None, current_tab=None):
        super().__init__(parent)
        self.store = store
        self.current_tab = current_tab or (lambda: None)   # a tab to start a retried download from
        self.setWindowTitle("Downloads")
        self.resize(640, 520)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search downloads")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.rows: list[DownloadRow] = []
        holder = QWidget()
        self.box = QVBoxLayout(holder)
        self.box.setContentsMargins(0, 0, 6, 0)
        self.box.setSpacing(6)
        self.empty = QLabel("Files you download appear here.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.box.addWidget(self.empty)
        self.box.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(holder)
        self.ask = QCheckBox("Ask where to save each file")
        self.ask.setChecked(self._get("download_ask", True) is not False)
        self.ask.toggled.connect(lambda on: store is not None and store.set("download_ask", on))
        folder = QPushButton("Open Downloads folder")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(downloads_folder())))
        clear = QPushButton("Clear list")
        clear.setToolTip("Remove finished downloads from this list (the files stay)")
        clear.clicked.connect(self.clear_finished)
        foot = QHBoxLayout()
        foot.addWidget(self.ask)
        foot.addStretch(1)
        foot.addWidget(folder)
        foot.addWidget(clear)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(area, 1)
        lay.addLayout(foot)
        for e in self._get("downloads_history", []) or []:
            if isinstance(e, dict) and e.get("path"):
                self._add(DownloadRow(self, dict(e)), top=False)
        self._timer = QTimer(self, interval=1000, timeout=self._tick)   # speed and time left keep updating
        self._timer.start()

    def _get(self, key, default):
        if self.store is None:
            return default
        v = self.store.get(key)
        return default if v is None else v

    def _add(self, row, top=True):
        self.rows.insert(0, row) if top else self.rows.append(row)
        self.box.insertWidget(0 if top else self.box.count() - 2, row)
        self.empty.setVisible(False)

    def track(self, req, private: bool = False):
        url = req.url().toString()
        entry = {"path": os.path.join(req.downloadDirectory(), req.downloadFileName()), "url": url,
                 "host": QUrl(url).host(), "time": time.time(), "size": 0, "state": "running"}
        row = DownloadRow(self, entry, req)
        row.private = private
        self._add(row)
        return row

    def remember(self):
        if self.store is None:
            return
        keep = [r.entry for r in self.rows
                if not getattr(r, "private", False) and r.state() not in ("running", "paused")]
        self.store.set("downloads_history", keep[:HISTORY_LIMIT])

    def remove(self, row):
        self.rows.remove(row)
        row.deleteLater()
        self.empty.setVisible(not self.rows)
        self.remember()

    def clear_finished(self):
        for r in [r for r in self.rows if r.state() not in ("running", "paused")]:
            self.remove(r)

    def retry(self, row):
        tab = self.current_tab()
        if tab is not None:
            self.remove(row)
            tab.page().download(QUrl(row.entry["url"]), os.path.basename(row.entry["path"]))

    def _tick(self):
        for r in self.rows:
            if r.req is not None and r.state() == "running":
                r.refresh()

    def _filter(self, text):
        q = text.strip().lower()
        for r in self.rows:
            r.setVisible(not q or q in r.entry.get("name", "").lower() or q in r.entry.get("url", "").lower())


def choose_path(store, req, parent) -> str | None:
    """Where a new download goes: asked (the default), or straight into the Downloads folder."""
    if store is not None and store.get("download_ask") is False:
        return unique_path(downloads_folder(), req.downloadFileName())
    from PySide6.QtWidgets import QFileDialog
    path, _ = QFileDialog.getSaveFileName(parent, "Save download", os.path.join(downloads_folder(),
                                                                               req.downloadFileName()))
    return path or None

