"""Chrome-style tab strip: equal-width tabs, pinned tabs, tab groups (name, colour, collapse), mute, duplicate,
reopen closed tab, close others/to the right, and a tab search popup.

Per-tab state lives on the BrowserTab widget: _pinned (bool), _group (group id or None), _title_full, _icon_full.
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QColorDialog, QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QApplication, QSplitter, QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

from . import icons

# group names for sites whose address doesn't spell their name nicely
SITE_NAMES = {"youtube": "YouTube", "github": "GitHub", "myopenmath": "MyOpenMath", "chatgpt": "ChatGPT",
              "openai": "OpenAI", "linkedin": "LinkedIn", "tiktok": "TikTok", "edmentum": "Edmentum",
              "cloudflare": "Cloudflare", "stackoverflow": "Stack Overflow", "wikipedia": "Wikipedia"}


def site_of(url) -> str:
    """The site a page belongs to: classroom.google.com and docs.google.com are both "google.com"."""
    if url.scheme() not in ("http", "https"):
        return ""
    parts = url.host().lower().split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:   # bbc.co.uk-style names
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def site_name(site: str) -> str:
    label = site.split(".")[0]
    return SITE_NAMES.get(label, label[:1].upper() + label[1:])

# Chrome's tab group colours
GROUP_COLORS = {"Blue": "#5b8def", "Grey": "#8a8fa3", "Red": "#e0605a", "Yellow": "#e6b84a", "Green": "#4fae6e",
                "Pink": "#e36aa8", "Purple": "#a36ee6", "Cyan": "#2FB3B4", "Orange": "#e8894a"}
TAB_MAX, TAB_MIN, PINNED_W = 240, 140, 44   # TAB_MIN keeps titles readable; more tabs scroll
CLOSED_LIMIT = 25


def swatch(color: str, size: int = 16) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


class GroupEditor(QDialog):
    """Name and color of a tab group, like Chrome's group bubble: a name box, a row of color dots and a
    custom color picker. Changes show on the tab strip as you pick."""

    def __init__(self, strip, gid):
        super().__init__(strip.win)
        self.strip, self.gid = strip, gid
        g = strip.groups[gid]
        self.setWindowTitle("Tab group")
        self.name = QLineEdit(g["name"])
        self.name.setPlaceholderText("Name this group")
        self.name.setMaxLength(24)
        self.name.textEdited.connect(lambda t: strip.set_group(gid, name=t.strip()))
        self.name.returnPressed.connect(self.accept)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.dots = {}
        for label, c in GROUP_COLORS.items():
            b = QToolButton()
            b.setToolTip(label)
            b.setCheckable(True)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=c: self.pick(c))
            self.dots[c.lower()] = b
            row.addWidget(b)
        more = QToolButton()
        more.setText("…")
        more.setToolTip("Custom color")
        more.setFixedSize(26, 26)
        more.clicked.connect(self._custom)
        row.addWidget(more)
        self.custom = more
        lay = QVBoxLayout(self)
        lay.addWidget(self.name)
        lay.addLayout(row)
        self._paint()

    def pick(self, color: str):
        self.strip.set_group(self.gid, color=color)
        self._paint()

    def _custom(self):
        self.strip._custom_color(self.gid, self)
        self._paint()

    def _paint(self):
        cur = self.strip.groups[self.gid]["color"].lower()
        for c, b in self.dots.items():
            b.setChecked(c == cur)
            ring = "#ffffff" if c == cur else "transparent"
            b.setStyleSheet(f"QToolButton{{background:{c};border:2px solid {ring};border-radius:13px}}")
        custom = cur not in self.dots
        self.custom.setStyleSheet(f"QToolButton{{background:{cur if custom else '#1e2129'};border:2px solid "
                                  f"{'#ffffff' if custom else '#3a3e4a'};border-radius:13px;color:#c9cfdb}}")


class GroupChip(QToolButton):
    """A group's coloured label. Click to collapse or expand; drag it to move the whole group along the strip."""

    def __init__(self, strip):
        super().__init__()
        self.strip = strip
        self._gid = None
        self._press = None
        self.dragging = False

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._press, self.dragging = ev.globalPosition().toPoint(), False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._press is not None and (ev.buttons() & Qt.LeftButton):
            if not self.dragging and (ev.globalPosition().toPoint() - self._press).manhattanLength() \
                    >= QApplication.startDragDistance():
                self.dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            if self.dragging:
                self.strip.drag_group(self._gid, self.strip.bar.mapFromGlobal(ev.globalPosition().toPoint()).x())
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._press = None
        if self.dragging:
            self.dragging = False
            self.setDown(False)
            self.setCursor(Qt.PointingHandCursor)
            QTimer.singleShot(0, self.strip.normalize)   # no click: a drag doesn't collapse the group
            return
        super().mouseReleaseEvent(ev)


class TabBar(QTabBar):
    def __init__(self, strip):
        super().__init__()
        self.strip = strip
        self.setElideMode(Qt.ElideRight)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setDrawBase(False)
        self.setMovable(True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    # hover previews, and keeping the vertical tab list in step
    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        i = self.tabAt(ev.position().toPoint())
        previews = getattr(self.strip.win, "previews", None)
        if previews is not None:
            if ev.buttons() or i < 0:
                previews.hide()
            else:
                previews.hover(self.strip.tabs.widget(i), self.mapToGlobal(self.tabRect(i).bottomLeft() + QPoint(0, 4)))

    def wheelEvent(self, ev):
        """The wheel scrolls the tabs into view (like Chrome); it never switches tabs. Click to switch."""
        d = ev.angleDelta()
        step = d.y() or d.x()
        if not step:
            return
        name = "ScrollLeftButton" if step > 0 else "ScrollRightButton"
        btn = next((b for b in self.findChildren(QToolButton) if b.objectName() == name), None)
        if btn is not None and btn.isVisible() and btn.isEnabled():
            for _ in range(max(1, abs(step) // 120)):
                btn.click()
        ev.accept()

    def leaveEvent(self, ev):
        previews = getattr(self.strip.win, "previews", None)
        if previews is not None:
            previews.hide()
        super().leaveEvent(ev)

    def tabInserted(self, index):
        super().tabInserted(index)
        self.strip.changed()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self.strip.changed()

    def tabSizeHint(self, index):
        base = super().tabSizeHint(index)
        tab = self.strip.tabs.widget(index)
        if tab is None:
            return base
        h = base.height()
        if getattr(tab, "_pinned", False):
            return QSize(PINNED_W, h)
        chip = self.strip.chip_width(tab)
        if self.strip.is_collapsed_head(tab):
            return QSize(chip + 14, h)
        return QSize(self.strip.tab_width() + chip, h)

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)

    def mousePressEvent(self, ev):
        previews = getattr(self.strip.win, "previews", None)
        if previews is not None:
            previews.hide()
        self._pressed = None
        if ev.button() == Qt.LeftButton:
            i = self.tabAt(ev.position().toPoint())
            if i >= 0:
                self._pressed = (self.strip.tabs.widget(i), ev.position().x(), self.tabRect(i).center().x())
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MiddleButton:
            i = self.tabAt(ev.position().toPoint())
            if i >= 0:
                self.strip.win.close_tab_obj(self.strip.tabs.widget(i))
                return
        super().mouseReleaseEvent(ev)
        if ev.button() == Qt.LeftButton:
            pressed, self._pressed = getattr(self, "_pressed", None), None
            dropped = None
            if pressed is not None:   # the dragged tab, and where its middle was when it was let go
                tab, x0, center = pressed
                dropped = (tab, center + ev.position().x() - x0)
            QTimer.singleShot(0, lambda: self.strip.after_drag(dropped))

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        for i in range(self.count()):
            tab = self.strip.tabs.widget(i)
            gid = getattr(tab, "_group", None)
            if gid is None or not self.isTabVisible(i):
                continue
            g = self.strip.groups.get(gid)
            if not g:
                continue
            r = self.tabRect(i)
            p.fillRect(QRect(r.left(), r.bottom() - 2, r.width(), 3), QColor(g["color"]))
        for tab in self.strip.tabs.split or []:   # the two tabs shown side by side
            i = self.strip.tabs.indexOf(tab)
            if i >= 0 and self.isTabVisible(i):
                r = self.tabRect(i)
                p.fillRect(QRect(r.left() + 6, r.top() + 1, r.width() - 12, 2), QColor("#5FE0CF"))
        p.end()


def relayout(bar: QTabBar):
    """Make Qt ask for every tab's size again (setElideMode always re-lays out the tabs)."""
    bar.setElideMode(Qt.ElideRight)


class TabRow(QWidget):
    """The strip of tabs above the address bar (like Firefox and Chrome), with the new-tab and search buttons."""

    def __init__(self, bar: QTabBar):
        super().__init__()
        self.setObjectName("tabrow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.bar = bar
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(6, 0, 6, 0)
        self.lay.setSpacing(4)
        self.lay.addWidget(bar)
        self.lay.addStretch(1)

    def add_buttons(self, *buttons):
        for i, b in enumerate(buttons):
            self.lay.insertWidget(1 + i, b, 0, Qt.AlignVCenter)

    def add_window_buttons(self, box: QWidget):
        """Minimize / exit full screen / close at the far right, shown only in F11 full screen."""
        self.window_buttons = box
        self.lay.addWidget(box, 0, Qt.AlignTop)

    def reserved(self) -> int:
        box = getattr(self, "window_buttons", None)
        return box.sizeHint().width() if box is not None and not box.isHidden() else 0

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        relayout(self.bar)   # tab widths follow the window width


class TabWidget(QWidget):
    """QTabWidget's API, but the tab bar lives in its own row (self.row) so the window can put it above the toolbar.
    Each tab's page widget is kept as the tab's data, so moving tabs needs no bookkeeping."""
    currentChanged = Signal(int)

    def __init__(self, strip):
        super().__init__()
        self._bar = TabBar(strip)
        self.stack = QStackedWidget()
        self.split: list | None = None   # split view: [left tab, right tab]
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.setStyleSheet("QSplitter::handle{background:#232733}QSplitter::handle:hover{background:#1B8C9A}")
        self.stack.addWidget(self.splitter)
        QApplication.instance().focusChanged.connect(self._focus_changed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.row = TabRow(self._bar)
        self._bar.currentChanged.connect(self._changed)

    def _changed(self, i):
        w = self.widget(i)
        from .tabviews import snap
        shown = self.stack.currentWidget()
        for t in ([self.splitter.widget(k) for k in range(self.splitter.count())] if shown is self.splitter else [shown]):
            if t is not w:
                snap(t)   # a picture for its hover preview, taken while it's still on screen
        if w is not None:
            self._show(w)
        self.currentChanged.emit(i)

    # -- split view
    def _show(self, w):
        pair = self.split
        if pair and w in pair:
            for k, t in enumerate(pair):
                if self.splitter.indexOf(t) != k:
                    self.splitter.insertWidget(k, t)
                t.show()
            if self.splitter.count() == 2 and len(set(self.splitter.sizes())) == 1 or 0 in self.splitter.sizes():
                half = max(1, self.splitter.width() // 2)
                self.splitter.setSizes([half, half])
            self.stack.setCurrentWidget(self.splitter)
        else:
            self._release()
            self.stack.setCurrentWidget(w)

    def _release(self):
        while self.splitter.count():
            self.stack.addWidget(self.splitter.widget(0))

    def set_split(self, left, right):
        self.split = [left, right]
        cur = self.currentWidget()
        self._show(cur if cur in self.split else left)
        if cur not in self.split:
            self.setCurrentWidget(left)
        self._bar.update()

    def end_split(self):
        if self.split is None:
            return
        self.split = None
        self._release()
        cur = self.currentWidget()
        if cur is not None:
            self.stack.setCurrentWidget(cur)
        self._bar.update()

    def _focus_changed(self, _old, new):
        """Clicking into the other half of a split view makes it the current tab (address bar, etc.)."""
        try:
            if not self.split or new is None:
                return
            for t in self.split:
                if (t is new or t.isAncestorOf(new)) and t is not self.currentWidget():
                    self.setCurrentWidget(t)
        except RuntimeError:
            pass

    def tabBar(self) -> QTabBar:
        return self._bar

    def addTab(self, w, text: str) -> int:
        self.stack.addWidget(w)
        i = self._bar.addTab(text)
        self._bar.setTabData(i, w)
        if self._bar.currentIndex() == i:
            self._changed(i)
        return i

    def removeTab(self, i: int):
        w = self.widget(i)
        if self.split and w in self.split:
            self.end_split()
        self._bar.removeTab(i)
        if w is not None:
            self.stack.removeWidget(w)

    def widget(self, i: int):
        return self._bar.tabData(i) if 0 <= i < self._bar.count() else None

    def indexOf(self, w) -> int:
        return next((i for i in range(self._bar.count()) if self._bar.tabData(i) is w), -1)

    def count(self) -> int:
        return self._bar.count()

    def currentIndex(self) -> int:
        return self._bar.currentIndex()

    def setCurrentIndex(self, i: int):
        self._bar.setCurrentIndex(i)

    def currentWidget(self):
        return self.widget(self._bar.currentIndex())

    def setCurrentWidget(self, w):
        i = self.indexOf(w)
        if i >= 0:
            self._bar.setCurrentIndex(i)


class TabStrip:
    def __init__(self, win):
        self.win = win
        self.groups: dict[str, dict] = {}       # id -> {name, color, collapsed}
        self.closed: list[str] = []
        self.tabs = TabWidget(self)
        self.bar: TabBar = self.tabs.tabBar()
        self.bar.customContextMenuRequested.connect(self._context_menu)
        self.tabs.currentChanged.connect(self._current_changed)
        corner = QToolButton()
        corner.setIcon(icons.icon("down"))
        corner.setToolTip("Search tabs")
        corner.clicked.connect(self.search_tabs)
        self.search_btn = corner

    # -- sizes
    def tab_width(self) -> int:
        tabs = [self.tabs.widget(i) for i in range(self.tabs.count()) if self.bar.isTabVisible(i)]
        pinned = sum(1 for t in tabs if getattr(t, "_pinned", False))
        normal = [t for t in tabs if not getattr(t, "_pinned", False) and not self.is_collapsed_head(t)]
        chips = sum(self.chip_width(t) + (14 if self.is_collapsed_head(t) else 0) for t in tabs)
        avail = self.tabs.row.width() - 110 - self.tabs.row.reserved() - pinned * PINNED_W - chips
        return max(TAB_MIN, min(TAB_MAX, avail // max(1, len(normal))))

    def chip_width(self, tab) -> int:
        chip = self._chip(tab)
        return chip.width() + 6 if chip is not None else 0

    def _chip(self, tab):
        i = self.tabs.indexOf(tab)
        if i < 0 or not self.is_group_head(tab):
            return None
        return self.bar.tabButton(i, QTabBar.LeftSide)

    # -- groups
    def members(self, gid) -> list:
        return [t for t in self.win.tab_list() if getattr(t, "_group", None) == gid]

    def is_group_head(self, tab) -> bool:
        gid = getattr(tab, "_group", None)
        m = self.members(gid) if gid else []
        return bool(m) and m[0] is tab

    def is_collapsed_head(self, tab) -> bool:
        gid = getattr(tab, "_group", None)
        return bool(gid and self.groups.get(gid, {}).get("collapsed") and self.is_group_head(tab))

    def new_group(self, tabs, name: str = "", color: str | None = None) -> str:
        gid = uuid.uuid4().hex[:8]
        used = {g["color"] for g in self.groups.values()}
        color = color or next((c for c in GROUP_COLORS.values() if c not in used), "#8a8fa3")
        self.groups[gid] = {"name": name, "color": color, "collapsed": False}
        for t in tabs:
            t._pinned = False
            t._group = gid
        self.normalize()
        return gid

    def group_by_site(self) -> int:
        """Sort tabs into groups by site: two or more tabs from the same site (e.g. Google Classroom and Google
        Docs are both Google) get a group named after it. Pinned tabs, groups you made yourself and tabs you took
        out of an automatic group are left alone. Returns how many tabs were moved into groups."""
        tabs = [t for t in self.win.tab_list() if not getattr(t, "_pinned", False)]
        auto = {g["auto"]: gid for gid, g in self.groups.items() if g.get("auto")}
        by_site: dict[str, list] = {}
        moved = 0
        for t in tabs:
            gid = getattr(t, "_group", None)
            if gid and not self.groups.get(gid, {}).get("auto"):
                continue   # in a group you made: yours to arrange
            site = site_of(t.url())
            if gid and self.groups[gid]["auto"] != site:   # it went to another site: out of the old site's group
                t._group = None
                gid = None
            if site and not getattr(t, "_no_auto", False):
                by_site.setdefault(site, []).append(t)
        for site, members in by_site.items():
            gid = auto.get(site)
            if gid is None and len(members) < 2:
                continue
            if gid is None:
                gid = uuid.uuid4().hex[:8]
                used = {g["color"] for g in self.groups.values()}
                color = next((c for c in GROUP_COLORS.values() if c not in used), "#8a8fa3")
                self.groups[gid] = {"name": site_name(site), "color": color, "collapsed": False, "auto": site}
            for t in members:
                if getattr(t, "_group", None) != gid:
                    t._group = gid
                    moved += 1
        # a site group left with one tab isn't a group any more
        for gid, g in list(self.groups.items()):
            if g.get("auto") and len(self.members(gid)) < 2:
                for t in self.members(gid):
                    t._group = None
        self.normalize()
        return moved

    def leave_auto_group(self, tab):
        """Taken out of a group by hand: automatic grouping won't put it back."""
        if self.groups.get(getattr(tab, "_group", None), {}).get("auto"):
            tab._no_auto = True
        self.remove_from_group(tab)

    def add_to_group(self, tab, gid):
        tab._pinned = False
        tab._group = gid
        self.normalize()

    def remove_from_group(self, tab):
        tab._group = None
        self.normalize()

    def set_group(self, gid, **changes):
        self.groups[gid].update(changes)
        self.normalize()

    def toggle_collapse(self, gid):
        g = self.groups.get(gid)
        if not g:
            return
        g["collapsed"] = not g["collapsed"]
        cur = self.win.current_tab()
        if g["collapsed"] and getattr(cur, "_group", None) == gid:
            others = [t for t in self.win.tab_list() if getattr(t, "_group", None) != gid]
            if others:
                self.win.select_tab(others[0])
            else:
                self.win.open_tab()
        self.normalize()

    def ungroup(self, gid):
        for t in self.members(gid):
            t._group = None
        self.groups.pop(gid, None)
        self.normalize()

    def close_group(self, gid):
        for t in self.members(gid):
            self.win.close_tab_obj(t)
        self.groups.pop(gid, None)
        self.normalize()

    # -- pinning, muting, closing
    def set_pinned(self, tab, on: bool):
        tab._pinned = on
        if on:
            tab._group = None
        self.normalize()

    def toggle_mute(self, tab):
        tab.page().setAudioMuted(not tab.page().isAudioMuted())
        self.refresh(tab)

    def duplicate(self, tab):
        new = self.win.open_tab(tab.url().toString(), background=False)
        new._group = getattr(tab, "_group", None)
        self.tabs.tabBar().moveTab(self.tabs.indexOf(new), self.tabs.indexOf(tab) + 1)
        self.normalize()
        return new

    def remember_closed(self, tab):
        url = tab.url().toString()
        if url and not self.win.is_start(tab.url()) and url != "about:blank":
            self.closed.append(url)
            del self.closed[:-CLOSED_LIMIT]

    def reopen_closed(self):
        if self.closed:
            self.win.open_tab(self.closed.pop())

    def close_others(self, keep):
        for t in self.win.tab_list():
            if t is not keep and not getattr(t, "_pinned", False):
                self.win.close_tab_obj(t)

    def close_right(self, tab):
        i = self.tabs.indexOf(tab)
        for t in self.win.tab_list()[i + 1:]:
            self.win.close_tab_obj(t)

    # -- order and labels
    def normalize(self):
        """Pinned tabs first, then everything else with each group's tabs kept together; refresh labels."""
        tabs = self.win.tab_list()
        live = {getattr(t, "_group", None) for t in tabs}
        for gid in list(self.groups):
            if gid not in live:
                self.groups.pop(gid)
        order, placed = [t for t in tabs if getattr(t, "_pinned", False)], set()
        for t in tabs:
            if getattr(t, "_pinned", False) or id(t) in placed:
                continue
            gid = getattr(t, "_group", None)
            batch = [m for m in tabs if gid and getattr(m, "_group", None) == gid and not getattr(m, "_pinned", False)] \
                if gid else [t]
            for m in batch:
                if id(m) not in placed:
                    order.append(m)
                    placed.add(id(m))
        cur = self.win.current_tab()
        for want, t in enumerate(order):
            have = self.tabs.indexOf(t)
            if have != want:
                self.bar.moveTab(have, want)
        if cur is not None:
            self.win.select_tab(cur)
        for t in order:
            self.refresh(t)
        relayout(self.bar)
        self.bar.update()

    def refresh(self, tab):
        i = self.tabs.indexOf(tab)
        if i < 0:
            return
        title = getattr(tab, "_title_full", "") or "New tab"
        icon = getattr(tab, "_icon_full", None) or QIcon()
        pinned = getattr(tab, "_pinned", False)
        gid = getattr(tab, "_group", None)
        g = self.groups.get(gid) if gid else None
        collapsed = bool(g and g["collapsed"])
        head = self.is_group_head(tab)
        if tab.page().isAudioMuted():
            icon = icons.icon("muted")
        elif tab.page().recentlyAudible():
            icon = icons.icon("audible")
        self.bar.setTabVisible(i, not (collapsed and not head))
        self.bar.setTabText(i, "" if pinned or (collapsed and head) else title)
        self.bar.setTabIcon(i, QIcon() if collapsed and head else icon)
        self.bar.setTabToolTip(i, title)
        close = self.bar.tabButton(i, QTabBar.RightSide)
        if close is not None:
            close.setVisible(not pinned and not (collapsed and head))
        chip = self.bar.tabButton(i, QTabBar.LeftSide)
        if head and g:
            if chip is None:
                chip = GroupChip(self)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setContextMenuPolicy(Qt.CustomContextMenu)
                chip.clicked.connect(lambda _=False, c=chip: self.toggle_collapse(c._gid))
                chip.customContextMenuRequested.connect(
                    lambda pos, c=chip: self._group_menu(c._gid).exec(c.mapToGlobal(pos)))
                self.bar.setTabButton(i, QTabBar.LeftSide, chip)
            chip._gid = gid
            chip.setText(g["name"] or "")
            font = chip.font()
            font.setPixelSize(11)
            font.setBold(True)
            chip.setFont(font)
            chip.setFixedSize(max(16, QFontMetrics(font).horizontalAdvance(g["name"] or "") + 16), 18)
            chip.setToolTip(f"{g['name'] or 'Unnamed group'}: click to {'expand' if collapsed else 'collapse'},"
                            " drag to move the group (right-click to rename or change its color)")
            ink = "#101217" if QColor(g["color"]).lightnessF() > 0.45 else "#ffffff"
            chip.setStyleSheet(f"QToolButton{{background:{g['color']};color:{ink};border:none;border-radius:6px;"
                               f"padding:0 6px;margin:0;font-size:11px;font-weight:700}}")
        elif chip is not None:
            self.bar.setTabButton(i, QTabBar.LeftSide, None)
            chip.deleteLater()
        if hasattr(self.win, "sleeper"):
            self.win.sleeper.mark(tab)
        self.changed()

    def changed(self):
        """Something about the tabs changed: the vertical tab list (if shown) catches up."""
        vt = getattr(self.win, "vtabs", None)
        if vt is not None:
            vt.schedule()

    # -- split view
    def split_view(self, other=None):
        """Show the current tab and another side by side (or stop, if already split). The other tab is the one
        given, else the next tab, else a new tab."""
        tabs = self.tabs
        if tabs.split:
            tabs.end_split()
            return
        cur = self.win.current_tab()
        if cur is None:
            return
        if other is None or other is cur:
            visible = [t for t in self.win.tab_list() if self.bar.isTabVisible(tabs.indexOf(t)) and t is not cur]
            i = self.win.tab_list().index(cur)
            after = [t for t in visible if self.win.tab_list().index(t) > i]
            other = (after or visible or [None])[0]
            if other is None:
                other = self.win.open_tab(background=True)
        tabs.set_split(cur, other)

    def blocks(self) -> list[list]:
        """The unpinned tabs in order, as moveable units: each group's tabs together, other tabs one by one."""
        out, seen = [], set()
        for t in self.win.tab_list():
            if getattr(t, "_pinned", False):
                continue
            gid = getattr(t, "_group", None)
            if gid is None:
                out.append([t])
            elif gid not in seen:
                seen.add(gid)
                out.append(self.members(gid))
        return out

    def _apply_order(self, order):
        cur = self.win.current_tab()
        for want, t in enumerate(order):
            have = self.tabs.indexOf(t)
            if have != want:
                self.bar.moveTab(have, want)
        if cur is not None and self.win.current_tab() is not cur:
            self.win.select_tab(cur)

    def move_group(self, gid, slot: int):
        """Put the whole group at position `slot` among the other tabs and groups (0 = first after pinned tabs)."""
        others = [b for b in self.blocks() if getattr(b[0], "_group", None) != gid]
        group = self.members(gid)
        if not group:
            return
        slot = max(0, min(slot, len(others)))
        pinned = [t for t in self.win.tab_list() if getattr(t, "_pinned", False)]
        order = pinned + [t for b in others[:slot] for t in b] + group + [t for b in others[slot:] for t in b]
        if order != self.win.tab_list():
            self._apply_order(order)
            self.bar.update()

    def drag_group(self, gid, x: int):
        """While a group's label is dragged: the group goes before the first other tab or group whose middle is
        right of the pointer."""
        others = [b for b in self.blocks() if getattr(b[0], "_group", None) != gid]
        slot = len(others)
        for n, b in enumerate(others):
            rects = [self.bar.tabRect(self.tabs.indexOf(t)) for t in b if self.bar.isTabVisible(self.tabs.indexOf(t))]
            if rects and x < (rects[0].left() + rects[-1].right()) / 2:
                slot = n
                break
        self.move_group(gid, slot)

    def after_drag(self, dropped=None):
        """A tab dropped between two tabs of a group joins that group; a grouped tab left apart from the rest of
        its group leaves it. `dropped` is (tab, x of its middle when let go): a tab dragged past the end of its
        group by more than half its width leaves the group, even with nothing beyond it to drop between."""
        tabs = [t for t in self.win.tab_list() if not getattr(t, "_pinned", False)]

        def around(i):
            groups = [getattr(t, "_group", None) for t in tabs]
            return (groups[i - 1] if i > 0 else None), groups[i], (groups[i + 1] if i + 1 < len(tabs) else None), groups

        joins = {}
        for i in range(len(tabs)):
            left, gid, right, _ = around(i)
            if left and left == right and gid != left:
                joins[i] = left
        for i, gid in joins.items():
            tabs[i]._group = gid
        leaves = []
        for i in range(len(tabs)):
            left, gid, right, groups = around(i)
            if gid and left != gid and right != gid and groups.count(gid) > 1:
                leaves.append(i)
        for i in leaves:
            tabs[i]._group = None
        if dropped is not None and dropped[0] in tabs:
            tab, x = dropped
            gid = getattr(tab, "_group", None)
            others = [t for t in self.members(gid) if t is not tab] if gid else []
            if others:
                rects = [self.bar.tabRect(self.tabs.indexOf(t)) for t in others]
                half = self.bar.tabRect(self.tabs.indexOf(tab)).width() / 2
                lo, hi = min(r.left() for r in rects), max(r.right() for r in rects)
                i = tabs.index(tab)
                at_end = i + 1 == len(tabs) or getattr(tabs[i + 1], "_group", None) != gid
                at_start = i == 0 or getattr(tabs[i - 1], "_group", None) != gid
                if (at_end and x > hi + 2 * half) or (at_start and x < lo - 2 * half):
                    tab._group = None
        self.normalize()

    def _current_changed(self, _i):
        tab = self.win.current_tab()
        gid = getattr(tab, "_group", None)
        if gid and self.groups.get(gid, {}).get("collapsed"):
            self.groups[gid]["collapsed"] = False
            QTimer.singleShot(0, self.normalize)

    # -- menus
    def _context_menu(self, pos: QPoint):
        i = self.bar.tabAt(pos)
        if i < 0:
            m = QMenu(self.win)
            m.addAction("New tab").triggered.connect(lambda: self.win.open_tab())
            m.addAction("Reopen closed tab\tCtrl+Shift+T").triggered.connect(self.reopen_closed)
            m.exec(self.bar.mapToGlobal(pos))
            return
        tab = self.tabs.widget(i)
        self.tab_menu(tab).exec(self.bar.mapToGlobal(pos))

    def tab_menu(self, tab) -> QMenu:
        m = QMenu(self.win)
        m.addAction("New tab to the right").triggered.connect(lambda: self._new_right(tab))
        gid = getattr(tab, "_group", None)
        if not getattr(tab, "_pinned", False):
            if gid:
                m.addAction("Remove from group").triggered.connect(lambda: self.leave_auto_group(tab))
            sub = m.addMenu("Add tab to group")
            sub.addAction("New group").triggered.connect(lambda: self._new_group_named([tab]))
            for g_id, g in self.groups.items():
                if g_id != gid:
                    sub.addAction(g["name"] or "Unnamed group").triggered.connect(
                        lambda _=False, g_id=g_id: self.add_to_group(tab, g_id))
        if gid:
            m.addMenu(self._group_menu(gid, parent=m)).setText("Group")
        m.addAction("Group tabs by site").triggered.connect(self.group_by_site)
        m.addSeparator()
        m.addAction("Reload").triggered.connect(tab.reload)
        m.addAction("Duplicate").triggered.connect(lambda: self.duplicate(tab))
        if self.tabs.split and tab in self.tabs.split:
            m.addAction("Exit split view").triggered.connect(self.tabs.end_split)
        elif tab is self.win.current_tab():
            m.addAction("Split view with the next tab").triggered.connect(lambda: self.split_view())
        else:
            m.addAction("Show side by side with this tab").triggered.connect(lambda: self.split_view(tab))
        m.addAction("Unpin" if getattr(tab, "_pinned", False) else "Pin").triggered.connect(
            lambda: self.set_pinned(tab, not getattr(tab, "_pinned", False)))
        m.addAction("Unmute site" if tab.page().isAudioMuted() else "Mute site").triggered.connect(
            lambda: self.toggle_mute(tab))
        sleeper = getattr(self.win, "sleeper", None)
        if sleeper is not None:
            from .sleeper import is_asleep
            if is_asleep(tab):
                m.addAction("Wake tab").triggered.connect(lambda: sleeper.wake(tab))
            else:
                a = m.addAction("Put tab to sleep (frees memory)")
                a.setEnabled(sleeper.can_sleep(tab, manual=True))
                a.triggered.connect(lambda: sleeper.sleep(tab, manual=True))
        m.addSeparator()
        m.addAction("Close\tCtrl+W").triggered.connect(lambda: self.win.close_tab_obj(tab))
        m.addAction("Close other tabs").triggered.connect(lambda: self.close_others(tab))
        m.addAction("Close tabs to the right").triggered.connect(lambda: self.close_right(tab))
        m.addSeparator()
        m.addAction("Reopen closed tab\tCtrl+Shift+T").triggered.connect(self.reopen_closed)
        return m

    def _group_menu(self, gid, parent=None) -> QMenu:
        g = self.groups[gid]
        m = QMenu(parent or self.win)
        m.addAction("Edit name and color…").triggered.connect(lambda: self._rename(gid))
        colors = m.addMenu(swatch(g["color"]), "Color")
        for name, c in GROUP_COLORS.items():
            a = colors.addAction(swatch(c), name)
            a.setCheckable(True)
            a.setChecked(c.lower() == g["color"].lower())
            a.triggered.connect(lambda _=False, c=c: self.set_group(gid, color=c))
        colors.addSeparator()
        custom = colors.addAction("Custom color…")
        custom.setCheckable(True)
        custom.setChecked(g["color"].lower() not in {c.lower() for c in GROUP_COLORS.values()})
        custom.triggered.connect(lambda: self._custom_color(gid))
        m.addAction("Expand" if g["collapsed"] else "Collapse").triggered.connect(lambda: self.toggle_collapse(gid))
        m.addAction("New tab in group").triggered.connect(lambda: self._new_in_group(gid))
        sleeper = getattr(self.win, "sleeper", None)
        if sleeper is not None:
            from .sleeper import is_asleep
            members = self.members(gid)
            if any(not is_asleep(t) for t in members):
                m.addAction("Put group to sleep (frees memory)").triggered.connect(lambda: self.sleep_group(gid))
            if any(is_asleep(t) for t in members):
                m.addAction("Wake group").triggered.connect(lambda: self.wake_group(gid))
        m.addSeparator()
        m.addAction("Ungroup").triggered.connect(lambda: self.ungroup(gid))
        m.addAction("Close group").triggered.connect(lambda: self.close_group(gid))
        return m

    def sleep_group(self, gid):
        """Every tab in the group goes to sleep. If you're on one of them, you're moved to the nearest other tab
        first (the tab you're looking at can't sleep)."""
        members = self.members(gid)
        cur = self.win.current_tab()
        if cur in members:
            tabs = self.win.tab_list()
            i = tabs.index(cur)
            others = [t for t in tabs if t not in members and self.bar.isTabVisible(self.tabs.indexOf(t))]
            if others:
                self.win.select_tab(min(others, key=lambda t: abs(tabs.index(t) - i)))
        for t in members:
            self.win.sleeper.sleep(t, manual=True)

    def wake_group(self, gid):
        for t in self.members(gid):
            self.win.sleeper.wake(t)

    def _rename(self, gid):
        GroupEditor(self, gid).exec()

    def _custom_color(self, gid, parent=None):
        c = QColorDialog.getColor(QColor(self.groups[gid]["color"]), parent or self.win, "Group color")
        if c.isValid():
            self.set_group(gid, color=c.name())

    def _new_group_named(self, tabs):
        gid = self.new_group(tabs)
        self._rename(gid)

    def _new_right(self, tab):
        new = self.win.open_tab()
        new._group = getattr(tab, "_group", None)
        self.bar.moveTab(self.tabs.indexOf(new), self.tabs.indexOf(tab) + 1)
        self.normalize()

    def _new_in_group(self, gid):
        new = self.win.open_tab()
        self.add_to_group(new, gid)

    # -- tab search
    def search_tabs(self):
        dlg = TabSearch(self)
        btn = self.search_btn
        pos = btn.mapToGlobal(QPoint(btn.width() - dlg.width(), btn.height())) if btn.isVisible() else \
            self.win.mapToGlobal(QPoint(self.win.width() - dlg.width() - 20, 80))
        dlg.move(pos)
        dlg.exec()

    # -- session
    def layout_state(self, tabs) -> dict:
        split = [tabs.index(t) for t in self.tabs.split or [] if t in tabs]
        return {"tabs": [{"pinned": getattr(t, "_pinned", False), "group": getattr(t, "_group", None)} for t in tabs],
                "groups": {k: dict(v) for k, v in self.groups.items()}, "split": split if len(split) == 2 else None}

    def restore_layout(self, state):
        if not isinstance(state, dict):
            return
        rows, tabs = state.get("tabs") or [], self.win.tab_list()
        if len(rows) != len(tabs):
            return
        self.groups = {k: dict(v) for k, v in (state.get("groups") or {}).items() if isinstance(v, dict)}
        for t, r in zip(tabs, rows):
            t._pinned = bool(r.get("pinned"))
            t._group = r.get("group") if r.get("group") in self.groups else None
        self.normalize()
        split = state.get("split")
        if isinstance(split, list) and len(split) == 2 and all(isinstance(i, int) and 0 <= i < len(tabs) for i in split):
            self.tabs.set_split(tabs[split[0]], tabs[split[1]])


class TabSearch(QDialog):
    """Chrome's tab search: type to filter open tabs by title or address, Enter to switch."""

    def __init__(self, strip: TabStrip):
        super().__init__(strip.win, Qt.Popup)
        self.strip = strip
        self.resize(380, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search tabs")
        self.list = QListWidget()
        lay.addWidget(self.edit)
        lay.addWidget(self.list)
        self.edit.textChanged.connect(self._fill)
        self.edit.returnPressed.connect(self._pick)
        self.list.itemActivated.connect(lambda _: self._pick())
        self.edit.installEventFilter(self)
        self._fill("")

    def _fill(self, text):
        self.list.clear()
        t = text.lower()
        for tab in self.strip.win.tab_list():
            title = getattr(tab, "_title_full", "") or tab.title() or "New tab"
            url = tab.url().toString()
            if t and t not in title.lower() and t not in url.lower():
                continue
            item = QListWidgetItem(getattr(tab, "_icon_full", None) or QIcon(), f"{title}\n{url}")
            item.setData(Qt.UserRole, tab)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return super().eventFilter(obj, ev)

    def _pick(self):
        item = self.list.currentItem()
        if item is not None:
            self.strip.win.select_tab(item.data(Qt.UserRole))
        self.accept()
