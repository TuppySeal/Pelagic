"""More ways to see tabs: hover previews, vertical tabs, and workspaces (named sets of tabs you switch between).
Split view (two tabs side by side) lives in tabstrip.TabWidget, since it changes what the tab area shows.

Settings: "tab_previews" (on/off), "vertical_tabs" (on/off), "workspaces" ({name: saved tabs}) and "workspace"
(the one in use).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QStyle, QStyledItemDelegate, QToolButton,
                               QVBoxLayout, QWidget)

from . import icons
from .sleeper import is_asleep

THUMB_W = 260


# ------------------------------------------------------------------ hover previews
def snap(tab):
    """Keep a small picture of a tab, taken while it's on screen, for its hover preview."""
    try:
        if tab is not None and tab.isVisible() and tab.width() > 50 and not is_asleep(tab):
            tab._thumb = tab.grab().scaledToWidth(THUMB_W, Qt.SmoothTransformation)
    except RuntimeError:
        pass


class TabPreview(QFrame):
    """The card shown when the pointer rests on a tab: title, site and (for other tabs) a picture of the page."""

    def __init__(self, owner=None):
        # a small window owned by the browser window: it stays above that window only (not above other apps),
        # never takes focus, and Windows hides it with its owner when that's minimised
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setObjectName("tabpreview")
        self.setStyleSheet("#tabpreview{background:#1b1e26;border:1px solid #2c313d;border-radius:8px}"
                           "QLabel{background:transparent}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(3)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight:600;color:#e6e8ee")
        self.site = QLabel()
        self.site.setStyleSheet("color:#8b93a7;font-size:11px")
        self.pic = QLabel()
        self.pic.setStyleSheet("border-radius:4px;margin-top:4px")
        for w in (self.title, self.site, self.pic):
            lay.addWidget(w)
        self.setFixedWidth(THUMB_W + 22)
        self.tab = None

    def show_for(self, tab, pos: QPoint, current: bool):
        self.tab = tab
        title = getattr(tab, "_title_full", "") or tab.title() or "New tab"
        fm = QFontMetrics(self.title.font())
        self.title.setText(fm.elidedText(title, Qt.ElideRight, THUMB_W * 2 - 20))
        from .tools import page_url
        url = page_url(tab)
        site = url.host() or url.toString()[:60]
        self.site.setText(site + ("  ·  sleeping to save memory" if is_asleep(tab) else ""))
        thumb = getattr(tab, "_thumb", None)
        show_pic = not current and thumb is not None and not thumb.isNull()
        self.pic.setVisible(show_pic)
        if show_pic:
            self.pic.setPixmap(thumb)
        self.adjustSize()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            pos = QPoint(min(pos.x(), screen.right() - self.width() - 4), min(pos.y(), screen.bottom() - self.height() - 4))
        self.move(pos)
        self.show()
        self.raise_()


class PreviewHover:
    """Shows the preview after the pointer rests on a tab for a moment, and hides it when the pointer leaves."""

    def __init__(self, win):
        self.win = win
        self.card = None
        self.pending = None
        self.timer = QTimer(singleShot=True, interval=450, timeout=self._show)
        # a leave event can be missed (a fast move off the window, switching apps, a menu opening): while the card is
        # up, check a few times a second that the pointer is still over the tabs and Pelagic is still in front
        self.watch = QTimer(interval=200, timeout=self._check)
        try:
            win.tabs.currentChanged.connect(lambda _i: self.hide())
        except (AttributeError, RuntimeError):
            pass

    def _in_front(self) -> bool:
        """Pelagic's window is the one in front (the card itself may count as active on some systems)."""
        return self.win.isActiveWindow() or (self.card is not None and QApplication.activeWindow() is self.card)

    def _over_tabs(self) -> bool:
        pos = QCursor.pos()
        areas = [self.win.tabs.tabBar()]
        vt = getattr(self.win, "vtabs", None)
        if vt is not None:
            areas.append(vt.list.viewport())
        for w in areas:
            try:
                if w.isVisible() and w.rect().contains(w.mapFromGlobal(pos)):
                    return True
            except RuntimeError:
                pass
        return False

    def _check(self):
        try:
            gone = (QApplication.applicationState() != Qt.ApplicationActive or self.win.isMinimized()
                    or not self.win.isVisible() or not self._in_front() or not self._over_tabs())
        except RuntimeError:
            gone = True
        if gone:
            self.hide()

    def enabled(self) -> bool:
        return self.win.store.get("tab_previews") is not False

    def hover(self, tab, pos: QPoint):
        """tab under the pointer (or None) and where the card should go (global)."""
        if tab is None or not self.enabled():
            self.hide()
            return
        if self.card is not None and self.card.isVisible() and self.card.tab is not tab:
            self.pending = (tab, pos)
            self._show()   # moving along the tabs: switch straight away, like Chrome
            return
        if self.pending is None or self.pending[0] is not tab:
            self.pending = (tab, pos)
            self.timer.start()

    def _show(self):
        if self.pending is None:
            return
        tab, pos = self.pending
        try:
            if self.win.tabs.indexOf(tab) < 0:
                return
        except RuntimeError:
            return
        if not self._in_front() or not self._over_tabs():
            return
        if self.card is None:
            self.card = TabPreview(self.win)
        self.card.show_for(tab, pos, tab is self.win.current_tab())
        self.watch.start()

    def hide(self):
        self.timer.stop()
        self.watch.stop()
        self.pending = None
        if self.card is not None:
            self.card.hide()

    def close(self):
        self.hide()
        if self.card is not None:
            self.card.deleteLater()
            self.card = None


# ------------------------------------------------------------------ vertical tabs
KIND, TAB, GID, COLOR = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3


class _Delegate(QStyledItemDelegate):
    def __init__(self, tabs_list):
        super().__init__(tabs_list)
        self.list = tabs_list

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 30 if index.data(KIND) == "tab" else 26)

    def paint(self, p: QPainter, option, index):
        kind, color = index.data(KIND), index.data(COLOR)
        r = option.rect
        if kind == "group":
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            text = index.data(Qt.DisplayRole)
            fm = QFontMetrics(option.font)
            chip = QRect(r.left() + 6, r.top() + 4, min(r.width() - 12, fm.horizontalAdvance(text) + 20), r.height() - 8)
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(chip, 6, 6)
            p.setPen(QColor("#101217" if QColor(color).lightnessF() > 0.45 else "#ffffff"))
            f = option.font
            f.setBold(True)
            p.setFont(f)
            p.drawText(chip.adjusted(8, 0, -4, 0), Qt.AlignVCenter, text)
            p.restore()
            return
        super().paint(p, option, index)
        p.save()
        if color:
            p.fillRect(QRect(r.left() + 2, r.top() + 4, 3, r.height() - 8), QColor(color))
        if option.state & QStyle.State_MouseOver:
            p.setPen(QColor("#c9cedb"))
            p.drawText(self.list.close_rect(r), Qt.AlignCenter, "✕")
        p.restore()


class TabList(QListWidget):
    def __init__(self, vt):
        super().__init__()
        self.vt = vt
        self.setMouseTracking(True)
        self.setIconSize(QSize(16, 16))
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideRight)
        self.setItemDelegate(_Delegate(self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.setStyleSheet("QListWidget{background:transparent;border:none;outline:0}"
                           "QListWidget::item{padding:0 26px 0 10px;border-radius:6px;margin:1px 4px;color:#d7dbe5}"
                           "QListWidget::item:hover{background:rgba(255,255,255,0.06)}"
                           "QListWidget::item:selected{background:#262b38;color:#ffffff}")

    @staticmethod
    def close_rect(r: QRect) -> QRect:
        return QRect(r.right() - 26, r.top(), 22, r.height())

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        it = self.itemAt(ev.position().toPoint())
        tab = it.data(TAB) if it is not None and it.data(KIND) == "tab" else None
        r = self.visualItemRect(it) if it is not None else QRect()
        self.vt.win.previews.hover(tab, self.viewport().mapToGlobal(QPoint(r.right() + 8, r.top())))

    def leaveEvent(self, ev):
        self.vt.win.previews.hide()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        self.vt.win.previews.hide()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        if it is not None and it.data(KIND) == "tab":
            tab = it.data(TAB)
            closing = ev.button() == Qt.MiddleButton or (
                ev.button() == Qt.LeftButton and self.close_rect(self.visualItemRect(it)).contains(ev.position().toPoint()))
            if closing:
                self.vt.win.close_tab_obj(tab)
                return
        super().mouseReleaseEvent(ev)
        if it is not None and ev.button() == Qt.LeftButton:
            if it.data(KIND) == "tab":
                self.vt.win.select_tab(it.data(TAB))
            else:
                self.vt.win.strip.toggle_collapse(it.data(GID))

    def dropEvent(self, ev):
        super().dropEvent(ev)
        QTimer.singleShot(0, self.vt.dropped)

    def _menu(self, pos):
        it = self.itemAt(pos)
        strip = self.vt.win.strip
        if it is None:
            return
        m = strip.tab_menu(it.data(TAB)) if it.data(KIND) == "tab" else strip._group_menu(it.data(GID))
        m.exec(self.viewport().mapToGlobal(pos))


class VerticalTabs(QWidget):
    """Tabs listed down the left side. Same tabs, groups and menus as the tab strip; drag to reorder, drag a
    group's label to move the group."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("vtabs")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#vtabs{background:#14161c;border-right:1px solid #232733}")
        self.setFixedWidth(240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(6, 0, 6, 0)
        new = QToolButton()
        new.setIcon(icons.icon("plus"))
        new.setText("New tab")
        new.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        new.setToolTip("New tab (Ctrl+T)")
        new.clicked.connect(lambda: win.open_tab())
        find = QToolButton()
        find.setIcon(icons.icon("down"))
        find.setToolTip("Search tabs")
        find.clicked.connect(lambda: win.strip.search_tabs())
        top.addWidget(new, 1)
        top.addWidget(find)
        lay.addLayout(top)
        self.list = TabList(self)
        lay.addWidget(self.list, 1)
        self._timer = QTimer(self, singleShot=True, interval=0, timeout=self.rebuild)

    def schedule(self):
        if self.isVisible():
            self._timer.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.rebuild()

    def rebuild(self):
        strip, tabs = self.win.strip, self.win.tabs
        bar = tabs.tabBar()
        lst = self.list
        bottom = lst.verticalScrollBar().value()
        lst.clear()
        current = self.win.current_tab()
        for i in range(tabs.count()):
            tab = tabs.widget(i)
            gid = getattr(tab, "_group", None)
            g = strip.groups.get(gid) if gid else None
            if g and strip.is_group_head(tab):
                head = QListWidgetItem(("▸ " if g["collapsed"] else "▾ ") + (g["name"] or "Unnamed group"))
                head.setData(KIND, "group")
                head.setData(GID, gid)
                head.setData(COLOR, g["color"])
                head.setToolTip("Click to collapse or expand. Drag to move the group. Right-click for options.")
                lst.addItem(head)
                if g["collapsed"]:
                    continue
            if not bar.isTabVisible(i):
                continue
            title = getattr(tab, "_title_full", "") or "New tab"
            it = QListWidgetItem(bar.tabIcon(i) if not bar.tabIcon(i).isNull() else QIcon(), title)
            it.setData(KIND, "tab")
            it.setData(TAB, tab)
            it.setData(COLOR, g["color"] if g else None)
            it.setToolTip(title)
            if getattr(tab, "_pinned", False):
                it.setText("📌 " + title)
            lst.addItem(it)
            if tab is current:
                lst.setCurrentItem(it)
        lst.verticalScrollBar().setValue(bottom)

    def dropped(self):
        """New order from the list: a group label brings all its tabs with it."""
        strip = self.win.strip
        order, seen = [], set()
        for n in range(self.list.count()):
            it = self.list.item(n)
            members = strip.members(it.data(GID)) if it.data(KIND) == "group" else [it.data(TAB)]
            for t in members:
                if id(t) not in seen:
                    seen.add(id(t))
                    order.append(t)
        order += [t for t in self.win.tab_list() if id(t) not in seen]
        strip._apply_order(order)
        strip.after_drag()
        self.rebuild()


# ------------------------------------------------------------------ workspaces
def workspaces(store) -> dict:
    ws = store.get("workspaces")
    return ws if isinstance(ws, dict) else {}


def current_workspace(store) -> str:
    return store.get("workspace") or "Main"


def _snapshot(win) -> dict:
    from .tools import page_url
    kept = [t for t in win.tab_list() if page_url(t).scheme() in ("http", "https")]
    cur = win.current_tab()
    return {"tabs": [page_url(t).toString() for t in kept], "layout": win.strip.layout_state(kept),
            "current": kept.index(cur) if cur in kept else 0}


def save_current(win):
    ws = workspaces(win.store)
    ws[current_workspace(win.store)] = _snapshot(win)
    win.store.set("workspaces", ws)


def switch_workspace(win, name: str):
    """Keep this window's tabs in the workspace you're leaving, and bring up the other one's tabs."""
    store = win.store
    if name == current_workspace(store):
        return
    save_current(win)
    target = workspaces(store).get(name) or {}
    old = win.tab_list()
    urls = [u for u in target.get("tabs") or [] if isinstance(u, str)] or [None]
    new = [win.open_tab(u, background=True) for u in urls]
    for t in old:
        win.close_tab_obj(t, remember=False)
    if target.get("layout"):
        win.strip.restore_layout(target["layout"])
    pick = target.get("current") or 0
    win.select_tab(new[pick] if 0 <= pick < len(new) else new[0])
    store.set("workspace", name)
    win.save_session()
    win.notify(f"Workspace: {name}")
    QTimer.singleShot(2500, win.notice.hide)


def new_workspace(win):
    name, ok = QInputDialog.getText(win, "New workspace", "Name the new workspace (for example School or Games).\n"
                                    "Your current tabs stay saved in the workspace you're in.")
    name = name.strip()
    if not ok or not name:
        return
    if name in workspaces(win.store) or name == current_workspace(win.store):
        switch_workspace(win, name)
        return
    save_current(win)
    ws = workspaces(win.store)
    ws[name] = {"tabs": [], "layout": None, "current": 0}
    win.store.set("workspaces", ws)
    switch_workspace(win, name)


def rename_workspace(win):
    old = current_workspace(win.store)
    name, ok = QInputDialog.getText(win, "Rename workspace", "New name:", text=old)
    name = name.strip()
    if not ok or not name or name == old:
        return
    ws = workspaces(win.store)
    if name in ws:
        QMessageBox.information(win, "Rename workspace", f"There's already a workspace called “{name}”.")
        return
    ws[name] = ws.pop(old, None) or _snapshot(win)
    win.store.set("workspaces", ws)
    win.store.set("workspace", name)


def delete_workspace(win, name: str):
    if name == current_workspace(win.store):
        return
    n = len((workspaces(win.store).get(name) or {}).get("tabs") or [])
    if QMessageBox.question(win, "Delete workspace", f"Delete the workspace “{name}” and its {n} saved tab(s)?") \
            != QMessageBox.Yes:
        return
    ws = workspaces(win.store)
    ws.pop(name, None)
    win.store.set("workspaces", ws)


def fill_menu(win, menu: QMenu):
    menu.clear()
    cur = current_workspace(win.store)
    names = sorted(set(workspaces(win.store)) | {cur}, key=str.lower)
    for name in names:
        a = menu.addAction(name)
        a.setCheckable(True)
        a.setChecked(name == cur)
        a.triggered.connect(lambda _=False, n=name: switch_workspace(win, n))
    menu.addSeparator()
    menu.addAction("New workspace…").triggered.connect(lambda: new_workspace(win))
    menu.addAction(f"Rename “{cur}”…").triggered.connect(lambda: rename_workspace(win))
    others = [n for n in names if n != cur]
    if others:
        dm = menu.addMenu("Delete a workspace")
        for name in others:
            dm.addAction(name).triggered.connect(lambda _=False, n=name: delete_workspace(win, n))
