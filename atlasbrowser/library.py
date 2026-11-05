"""History page (Pelagic's own history and, separately, Google Chrome's) and the reading list.

Chrome's history is only read, never changed: its History database is copied to a temporary file first (Chrome
keeps it locked while it runs), or opened read-only when the copy isn't allowed.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icons
from .bookmarks_ui import favicon

CHROME_EPOCH = 11644473600   # seconds from 1601-01-01 (Chrome's clock) to 1970-01-01
LIMIT = 3000


# ------------------------------------------------------------------ Chrome
def chrome_root() -> Path | None:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        roots = [Path(base) / "Google" / "Chrome" / "User Data"] if base else []
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        roots = [config / "google-chrome", config / "chromium"]
    return next((r for r in roots if r.exists()), None)


def chrome_profiles(root: Path | None = None) -> list[tuple[str, Path]]:
    """[(name shown in Chrome, folder)] for each Chrome profile that has a history file."""
    root = root or chrome_root()
    if root is None:
        return []
    names = {}
    try:
        cache = json.loads((root / "Local State").read_text(encoding="utf-8"))["profile"]["info_cache"]
        names = {k: v.get("name") or k for k, v in cache.items()}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "History").exists() and (d.name == "Default" or d.name.startswith("Profile ")):
            out.append((names.get(d.name, d.name), d))
    return sorted(out, key=lambda p: (p[1].name != "Default", p[0].lower()))


def chrome_history(profile_dir: Path, query: str = "", limit: int = LIMIT) -> list[tuple[str, str, float]]:
    """[(url, title, unix time)] newest first, one row per visit."""
    src = profile_dir / "History"
    tmp = Path(tempfile.mkdtemp(prefix="pelagic_chrome_"))
    db = None
    try:
        try:
            shutil.copyfile(src, tmp / "History")
            db = sqlite3.connect(str(tmp / "History"))
        except OSError:   # locked: read it in place without touching it
            db = sqlite3.connect(f"{src.as_uri()}?mode=ro&immutable=1", uri=True)
        like = f"%{query}%"
        rows = db.execute(
            "SELECT u.url, u.title, v.visit_time FROM visits v JOIN urls u ON u.id = v.url "
            "WHERE (u.url LIKE ? OR u.title LIKE ?) ORDER BY v.visit_time DESC LIMIT ?",
            (like, like, limit * 3)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        if db is not None:
            db.close()
        shutil.rmtree(tmp, ignore_errors=True)
    out, last = [], None
    for url, title, t in rows:
        if (url, int(t // 60_000_000)) == last:   # Chrome logs redirects and reloads as extra visits
            continue
        last = (url, int(t // 60_000_000))
        out.append((url, title or url, t / 1_000_000 - CHROME_EPOCH))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ shared tree
def day_label(d: date) -> str:
    today = date.today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %B %d, %Y").replace(" 0", " ")


class DayTree(QTreeWidget):
    """Rows grouped under a heading per day, newest first. Double-click opens."""
    open_url = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setHeaderLabels(["Time", "Page", "Address"])
        self.setColumnWidth(0, 80)
        self.setColumnWidth(1, 330)
        self.setIconSize(QSize(16, 16))
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.itemActivated.connect(lambda it, _c: it.data(0, Qt.UserRole) and self.open_url.emit(it.data(0, Qt.UserRole)))

    def fill(self, rows):
        """rows: [(url, title, unix time)] newest first."""
        self.clear()
        head, current = None, None
        for url, title, t in rows:
            d = datetime.fromtimestamp(t).date()
            if d != current:
                current = d
                head = QTreeWidgetItem([day_label(d)])
                head.setFirstColumnSpanned(True)
                f = head.font(0)
                f.setBold(True)
                head.setFont(0, f)
                head.setFlags(Qt.ItemIsEnabled)
                self.addTopLevelItem(head)
                head.setExpanded(True)
            it = QTreeWidgetItem([time.strftime("%I:%M %p", time.localtime(t)).lstrip("0"), title, url])
            it.setIcon(1, favicon(self.store, url))
            it.setToolTip(1, title)
            it.setToolTip(2, url)
            it.setData(0, Qt.UserRole, url)
            head.addChild(it)
        if not rows:
            empty = QTreeWidgetItem(["Nothing here yet."])
            empty.setFirstColumnSpanned(True)
            empty.setFlags(Qt.NoItemFlags)
            self.addTopLevelItem(empty)

    def selected_urls(self) -> list[str]:
        return [it.data(0, Qt.UserRole) for it in self.selectedItems() if it.data(0, Qt.UserRole)]


# ------------------------------------------------------------------ history page
class HistoryDialog(QDialog):
    open_url = Signal(str)

    def __init__(self, store, parent=None, chrome_dir: Path | None = None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("History")
        self.resize(820, 600)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search history")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        self.tabs = QTabWidget()

        # Pelagic
        pw = QWidget()
        pv = QVBoxLayout(pw)
        self.pelagic = DayTree(store)
        self.pelagic.open_url.connect(self.open_url)
        pv.addWidget(self.pelagic, 1)
        row = QHBoxLayout()
        delete = QPushButton("Delete selected")
        delete.clicked.connect(self._delete)
        clear = QPushButton("Clear all history")
        clear.clicked.connect(self._clear)
        row.addWidget(delete)
        row.addStretch(1)
        row.addWidget(clear)
        pv.addLayout(row)
        self.tabs.addTab(pw, icons.icon("ai"), "Pelagic")

        # Chrome
        cw = QWidget()
        cv = QVBoxLayout(cw)
        self.chrome_profiles = chrome_profiles(chrome_dir)
        top = QHBoxLayout()
        self.chrome_profile = QComboBox()
        for name, d in self.chrome_profiles:
            self.chrome_profile.addItem(name, str(d))
        self.chrome_profile.currentIndexChanged.connect(self.reload)
        top.addWidget(QLabel("Chrome profile"))
        top.addWidget(self.chrome_profile, 1)
        cv.addLayout(top)
        self.chrome = DayTree(store)
        self.chrome.open_url.connect(self.open_url)
        cv.addWidget(self.chrome, 1)
        note = QLabel("Read only: this shows Google Chrome's history from this computer. Nothing in Chrome is "
                      "changed. If Chrome is open, very recent visits may be missing until it closes.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        cv.addWidget(note)
        if not self.chrome_profiles:
            self.chrome_profile.setEnabled(False)
            self.chrome_profile.addItem("Google Chrome isn't installed for this user")
        self.tabs.addTab(cw, icons.icon("globe"), "Chrome")
        self.tabs.currentChanged.connect(self.reload)

        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.tabs, 1)
        self.reload()

    def reload(self, *_):
        q = self.search.text().strip()
        if self.tabs.currentIndex() == 0:
            self.pelagic.fill([(u, t, last) for u, t, _v, last in self.store.history(q, limit=LIMIT)])
        else:
            d = self.chrome_profile.currentData()
            self.chrome.fill(chrome_history(Path(d), q) if d else [])

    def _delete(self):
        urls = self.pelagic.selected_urls()
        if urls:
            self.store.delete_history(urls)
            self.reload()

    def _clear(self):
        if QMessageBox.question(self, "Clear history", "Delete all of Pelagic's browsing history?") == QMessageBox.Yes:
            self.store.clear_history()
            self.reload()


# ------------------------------------------------------------------ reading list
class ReadingListDialog(QDialog):
    """Pages saved to read later. Opening one marks it read; unread ones are listed first."""
    open_url = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Reading list")
        self.resize(640, 480)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.itemActivated.connect(self._open)
        row = QHBoxLayout()
        for text, slot in (("Open", lambda: self._open(self.tree.currentItem())),
                           ("Mark read / unread", self._toggle), ("Remove", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        tip = QLabel("Add the page you're on with the menu → Add to reading list (Alt+Shift+R).")
        tip.setObjectName("muted")
        lay.addWidget(tip)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        self.reload()

    def reload(self):
        self.tree.clear()
        items = self.store.reading_list()
        for label, read in (("Unread", False), ("Read", True)):
            group = [e for e in items if bool(e.get("read")) == read]
            if not group:
                continue
            head = QTreeWidgetItem([f"{label} ({len(group)})"])
            head.setFlags(Qt.ItemIsEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            self.tree.addTopLevelItem(head)
            for e in group:
                it = QTreeWidgetItem([f"{e['title']}\n{e['url']}"])
                it.setIcon(0, favicon(self.store, e["url"]))
                it.setData(0, Qt.UserRole, e["url"])
                head.addChild(it)
            head.setExpanded(True)
        if not items:
            self.tree.addTopLevelItem(QTreeWidgetItem(["Your reading list is empty."]))

    def _url(self, it):
        return it.data(0, Qt.UserRole) if it is not None else None

    def _open(self, it, *_):
        url = self._url(it)
        if url:
            self.store.update_reading_list(url, read=True)
            self.open_url.emit(url)

    def _toggle(self):
        url = self._url(self.tree.currentItem())
        if url:
            read = next((e["read"] for e in self.store.reading_list() if e["url"] == url), False)
            self.store.update_reading_list(url, read=not read)
            self.reload()

    def _remove(self):
        url = self._url(self.tree.currentItem())
        if url:
            self.store.update_reading_list(url, remove=True)
            self.reload()
