"""Bookmarks bar, the bookmark editor and the bookmark manager: editable names and addresses, folders, and site
icons (cached per profile in favicons/, so they show before the site is opened again)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QFrame, QInputDialog, QLayout, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icons

NEW_FOLDER = "\x00new"  # combo entry that asks for a new folder name
BAR_STYLE = ("QPushButton{padding:2px 9px;font-size:12px;text-align:left}"
             "QPushButton::menu-indicator{width:0;image:none}")


# ------------------------------------------------------------------ icons
def save_favicon(store, url: str, icon: QIcon):
    if icon is None or icon.isNull() or not url.startswith(("http://", "https://")):
        return
    pix = icon.pixmap(32, 32)
    if pix.isNull():
        return
    path = store.favicon_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path), "PNG")


def favicon(store, url: str) -> QIcon:
    path = store.favicon_path(url)
    if path.exists():
        ic = QIcon(str(path))
        if not ic.isNull():
            return ic
    return icons.icon("globe")


# ------------------------------------------------------------------ editor
class BookmarkEditor(QDialog):
    """Name, address and folder of one bookmark (like Chrome's "Edit bookmark")."""

    def __init__(self, store, url: str, parent=None, added: bool = False):
        super().__init__(parent)
        self.store, self.url = store, url
        b = next((b for b in store.bookmarks if b["url"] == url), {"url": url, "title": url})
        self.setWindowTitle("Bookmark added" if added else "Edit bookmark")
        self.setMinimumWidth(420)
        self.name = QLineEdit(b["title"])
        self.addr = QLineEdit(b["url"])
        self.folder = QComboBox()
        fill_folder_combo(self.folder, store, b.get("folder", ""))
        self.folder.activated.connect(self._maybe_new_folder)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("URL", self.addr)
        form.addRow("Folder", self.folder)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        remove = btns.addButton("Remove", QDialogButtonBox.DestructiveRole)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        remove.clicked.connect(self._remove)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)
        self.name.selectAll()
        self.name.setFocus()

    def _maybe_new_folder(self, _i):
        if self.folder.currentData() == NEW_FOLDER:
            name = ask_folder_name(self)
            fill_folder_combo(self.folder, self.store, self.store.add_folder(name) if name else "")

    def _save(self):
        url = self.addr.text().strip()
        if url and "://" not in url and not url.startswith(("about:", "data:")):
            url = QUrl.fromUserInput(url).toString()
        self.store.edit_bookmark(self.url, title=self.name.text(), new_url=url or None,
                                 folder=self.folder.currentData() or "")
        self.accept()

    def _remove(self):
        self.store.remove_bookmark(self.url)
        self.done(2)


def fill_folder_combo(combo: QComboBox, store, current: str):
    combo.clear()
    combo.addItem(icons.icon("star"), "Bookmarks bar", "")
    for f in store.all_folders():
        combo.addItem(icons.icon("folder"), f, f)
    combo.addItem("New folder…", NEW_FOLDER)
    combo.setCurrentIndex(max(0, combo.findData(current)))


def ask_folder_name(parent, text: str = "", title: str = "New folder") -> str:
    name, ok = QInputDialog.getText(parent, title, "Folder name:", text=text)
    return name.strip()[:40] if ok else ""


# ------------------------------------------------------------------ bar
class BookmarkStrip(QWidget):
    """The bar's row of buttons, scrollable like the tabs: the mouse wheel or the ‹ › arrows move it along. It never
    makes the window wider (a long bar used to push a maximised window past the edges of the screen)."""
    STEP = 160

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setSizeConstraint(QLayout.SetNoConstraint)
        self.left, self.right = QToolButton(), QToolButton()
        for b, text, tip, step in ((self.left, "‹", "Scroll bookmarks left", -1),
                                   (self.right, "›", "Scroll bookmarks right", 1)):
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRepeat(True)
            b.setAutoRaise(True)
            b.setFixedWidth(20)
            b.clicked.connect(lambda _=False, d=step: self.scroll_by(d * self.STEP))
            b.hide()
        self.area = QScrollArea()
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setWidgetResizable(True)
        self.area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        inner = QWidget()
        self.lay = QHBoxLayout(inner)
        self.area.setWidget(inner)
        self.area.horizontalScrollBar().rangeChanged.connect(lambda *_: self.fit())
        self.area.horizontalScrollBar().valueChanged.connect(lambda *_: self.fit())
        self.area.viewport().installEventFilter(self)   # the wheel scrolls sideways here, like on the tabs
        outer.addWidget(self.left)
        outer.addWidget(self.area, 1)
        outer.addWidget(self.right)

    def minimumSizeHint(self):
        return QSize(0, self.area.widget().sizeHint().height())

    def sizeHint(self):
        return QSize(0, self.area.widget().sizeHint().height())

    def scroll_by(self, dx: int):
        sb = self.area.horizontalScrollBar()
        sb.setValue(sb.value() + dx)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel:
            d = ev.angleDelta()
            step = d.y() or d.x()
            if step:
                self.scroll_by(-round(step / 120 * 80) or (-40 if step > 0 else 40))
            return True
        return super().eventFilter(obj, ev)

    def fit(self):
        sb = self.area.horizontalScrollBar()
        self.left.setVisible(sb.maximum() > 0 and sb.value() > 0)
        self.right.setVisible(sb.maximum() > 0 and sb.value() < sb.maximum())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.fit()


class BookmarksBar:
    """Fills the window's bookmarks bar: folders (drop-down menus) then bookmarks, each with its site icon.
    Right-click a bookmark or folder to edit, rename or delete it."""

    def __init__(self, win):
        self.win, self.store = win, win.store
        win.bm_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        win.bm_bar.customContextMenuRequested.connect(lambda pos: self._bar_menu(win.bm_bar.mapToGlobal(pos)))

    def rebuild(self):
        lay = self.win.bm_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for f in self.store.all_folders():
            lay.addWidget(self._folder_button(f))
        for b in self.store.bookmarks_in(""):
            lay.addWidget(self._bookmark_button(b))
        lay.addStretch(1)
        has = bool(self.store.bookmarks or self.store.all_folders())
        self.win.bm_bar.setVisible(has and bool(self.store.get("bookmarks_bar")))

    def _button(self, text, icon, tip):
        btn = QPushButton(text)
        btn.setIcon(icon)
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(tip)
        btn.setStyleSheet(BAR_STYLE)
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        return btn

    def _bookmark_button(self, b):
        text = (b["title"] or b["url"])
        btn = self._button(text[:22] + ("…" if len(text) > 22 else ""), favicon(self.store, b["url"]),
                           f"{b['title']}\n{b['url']}")
        btn.clicked.connect(lambda _=False, u=b["url"]: self.open(u))
        btn.customContextMenuRequested.connect(
            lambda pos, u=b["url"], w=btn: self.bookmark_menu(u).exec(w.mapToGlobal(pos)))
        return btn

    def _folder_button(self, folder):
        btn = self._button(folder[:22], icons.icon("folder"), folder)
        m = QMenu(btn)
        m.aboutToShow.connect(lambda m=m, f=folder: self._fill_folder_menu(m, f))
        btn.setMenu(m)
        btn.customContextMenuRequested.connect(
            lambda pos, f=folder, w=btn: self.folder_menu(f).exec(w.mapToGlobal(pos)))
        return btn

    def _fill_folder_menu(self, m: QMenu, folder):
        m.clear()
        items = self.store.bookmarks_in(folder)
        for b in items:
            self._add_bookmark_action(m, b)
        if not items:
            m.addAction("(empty)").setEnabled(False)
        else:
            m.addSeparator()
            m.addAction(f"Open all ({len(items)})").triggered.connect(lambda: self.open_all(folder))

    def _add_bookmark_action(self, m: QMenu, b):
        a = m.addAction(favicon(self.store, b["url"]), (b["title"] or b["url"])[:60])
        a.setToolTip(b["url"])
        a.triggered.connect(lambda _=False, u=b["url"]: self.open(u))

    # actions
    def open(self, url: str, new_tab: bool = False):
        if new_tab or QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.win.open_tab(url)
        else:
            self.win._cur(lambda t: t.load(QUrl(url)))

    def open_all(self, folder):
        for b in self.store.bookmarks_in(folder):
            self.win.open_tab(b["url"], background=True)

    def edit(self, url: str):
        BookmarkEditor(self.store, url, self.win).exec()
        self.changed()

    def changed(self):
        self.rebuild()
        self.win._cur(self.win._sync_bar)

    def bookmark_menu(self, url: str) -> QMenu:
        m = QMenu(self.win)
        m.addAction("Open").triggered.connect(lambda: self.open(url))
        m.addAction("Open in new tab").triggered.connect(lambda: self.open(url, new_tab=True))
        m.addSeparator()
        m.addAction("Edit…").triggered.connect(lambda: self.edit(url))
        move = m.addMenu("Move to")
        cur = next((b.get("folder", "") for b in self.store.bookmarks if b["url"] == url), "")
        for label, f in [("Bookmarks bar", "")] + [(f, f) for f in self.store.all_folders()]:
            a = move.addAction(label)
            a.setEnabled(f != cur)
            a.triggered.connect(lambda _=False, f=f: (self.store.edit_bookmark(url, folder=f), self.changed()))
        move.addAction("New folder…").triggered.connect(lambda: self._move_to_new(url))
        m.addAction("Delete").triggered.connect(lambda: (self.store.remove_bookmark(url), self.changed()))
        self._common(m)
        return m

    def folder_menu(self, folder: str) -> QMenu:
        m = QMenu(self.win)
        n = len(self.store.bookmarks_in(folder))
        m.addAction(f"Open all ({n})").triggered.connect(lambda: self.open_all(folder))
        m.addSeparator()
        m.addAction("Rename folder…").triggered.connect(lambda: self.rename_folder(folder))
        m.addAction("Delete folder").triggered.connect(lambda: self.delete_folder(folder))
        self._common(m)
        return m

    def _common(self, m: QMenu):
        m.addSeparator()
        m.addAction("New folder…").triggered.connect(self.new_folder)
        m.addAction("Bookmark manager\tCtrl+Shift+O").triggered.connect(self.win.show_bookmarks)
        m.addAction("Hide bookmarks bar\tCtrl+Shift+B").triggered.connect(self.win.toggle_bookmarks_bar)

    def _bar_menu(self, pos):
        m = QMenu(self.win)
        self._common(m)
        m.exec(pos)

    def _move_to_new(self, url):
        name = ask_folder_name(self.win)
        if name:
            self.store.edit_bookmark(url, folder=self.store.add_folder(name))
            self.changed()

    def new_folder(self):
        name = ask_folder_name(self.win)
        if name:
            self.store.add_folder(name)
            self.changed()

    def rename_folder(self, folder):
        name = ask_folder_name(self.win, folder, "Rename folder")
        if name:
            self.store.rename_folder(folder, name)
            self.changed()

    def delete_folder(self, folder):
        n = len(self.store.bookmarks_in(folder))
        keep = True
        if n:
            box = QMessageBox(QMessageBox.Question, "Delete folder",
                              f"Delete the folder “{folder}”? It has {n} bookmark{'s' if n != 1 else ''}.",
                              parent=self.win)
            move = box.addButton("Keep them on the bar", QMessageBox.AcceptRole)
            drop = box.addButton("Delete them too", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() not in (move, drop):
                return
            keep = box.clickedButton() is move
        self.store.delete_folder(folder, keep_bookmarks=keep)
        self.changed()


# ------------------------------------------------------------------ manager
class BookmarksDialog(QDialog):
    """Bookmark manager: folders and bookmarks in a tree. Double-click opens, F2 or Edit renames, drag a
    bookmark onto a folder to move it."""
    open_url = Signal(str)
    changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Bookmarks")
        self.resize(680, 520)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search bookmarks…")
        self.search.textChanged.connect(self.reload)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "URL"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setDragDropMode(QTreeWidget.InternalMove)
        self.tree.itemActivated.connect(self._activated)
        self.tree.setEditTriggers(QTreeWidget.EditKeyPressed | QTreeWidget.SelectedClicked)
        self.tree.itemChanged.connect(self._renamed)
        self.tree.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, self._sync_moves))
        row = QHBoxLayout()
        for text, slot in (("New folder", self._new_folder), ("Edit…", self._edit), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        self._loading = False
        self.reload()

    # build
    def reload(self, *_):
        self._loading = True
        q = self.search.text().lower()
        self.tree.clear()
        match = lambda b: q in b["title"].lower() or q in b["url"].lower()   # noqa: E731
        for f in self.store.all_folders():
            items = [b for b in self.store.bookmarks_in(f) if match(b)]
            if q and not items and q not in f.lower():
                continue
            fi = QTreeWidgetItem([f, ""])
            fi.setIcon(0, icons.icon("folder"))
            fi.setData(0, Qt.UserRole, ("folder", f))
            fi.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDropEnabled)
            self.tree.addTopLevelItem(fi)
            for b in items:
                fi.addChild(self._item(b))
            fi.setExpanded(True)
        for b in self.store.bookmarks_in(""):
            if match(b):
                self.tree.addTopLevelItem(self._item(b))
        self._loading = False

    def _item(self, b):
        it = QTreeWidgetItem([b["title"], b["url"]])
        it.setIcon(0, favicon(self.store, b["url"]))
        it.setToolTip(1, b["url"])
        it.setData(0, Qt.UserRole, ("bookmark", b["url"]))
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
        return it

    def _kind(self, it):
        return it.data(0, Qt.UserRole) if it is not None else (None, None)

    # actions
    def _activated(self, it, _col):
        kind, val = self._kind(it)
        if kind == "bookmark":
            self.open_url.emit(val)

    def _renamed(self, it, col):
        if self._loading or col != 0:
            return
        kind, val = self._kind(it)
        if kind == "bookmark":
            self.store.edit_bookmark(val, title=it.text(0))
        elif kind == "folder":
            self.store.rename_folder(val, it.text(0))
        self._done()

    def _sync_moves(self):
        """After a drag, every bookmark takes the folder it now sits under."""
        if self._loading:
            return
        moved = False
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            kind, val = self._kind(top)
            if kind == "bookmark":
                moved |= self._set_folder(val, "")
            elif kind == "folder":
                for j in range(top.childCount()):
                    k2, v2 = self._kind(top.child(j))
                    if k2 == "bookmark":
                        moved |= self._set_folder(v2, val)
        if moved:
            self.changed.emit()

    def _set_folder(self, url, folder) -> bool:
        cur = next((b.get("folder", "") for b in self.store.bookmarks if b["url"] == url), None)
        if cur is None or cur == folder:
            return False
        self.store.edit_bookmark(url, folder=folder)
        return True

    def _new_folder(self):
        name = ask_folder_name(self)
        if name:
            self.store.add_folder(name)
            self._done()

    def _edit(self):
        it = self.tree.currentItem()
        kind, val = self._kind(it)
        if kind == "bookmark":
            BookmarkEditor(self.store, val, self).exec()
            self._done()
        elif kind == "folder":
            name = ask_folder_name(self, val, "Rename folder")
            if name:
                self.store.rename_folder(val, name)
                self._done()

    def _delete(self):
        for it in self.tree.selectedItems():
            kind, val = self._kind(it)
            if kind == "bookmark":
                self.store.remove_bookmark(val)
            elif kind == "folder":
                self.store.delete_folder(val, keep_bookmarks=True)
        self._done()

    def _done(self):
        self.reload()
        self.changed.emit()
