"""Sleeping tabs (like Chrome's Memory Saver): a tab you haven't looked at for a while is discarded, which frees
its memory. It keeps its title, icon and place in the tab strip, and reloads when you click it.

Never put to sleep: the tab you're on, pinned tabs, tabs playing sound, tabs with DevTools open, tabs that are
loading, and the tab the AI is working in. Settings: "tab_sleep" (on/off) and "tab_sleep_minutes".
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEnginePage

ASLEEP = QWebEnginePage.LifecycleState.Discarded
AWAKE = QWebEnginePage.LifecycleState.Active
CHECK_MS = 30_000


def is_asleep(tab) -> bool:
    return tab.page().lifecycleState() == ASLEEP


def touch(tab):
    tab._last_active = time.monotonic()


class TabSleeper(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.store = win, win.store
        self.timer = QTimer(self, interval=CHECK_MS, timeout=self.check)
        self.timer.start()

    def enabled(self) -> bool:
        return bool(self.store.get("tab_sleep"))

    def minutes(self) -> float:
        return max(1, int(self.store.get("tab_sleep_minutes") or 30))

    def can_sleep(self, tab, manual: bool = False) -> bool:
        """manual: you asked for it (a menu), so a tab that's still loading may sleep too."""
        page = tab.page()
        agent = getattr(getattr(self.win, "panel", None), "agent", None)
        return not (tab is self.win.current_tab() or tab in (self.win.tabs.split or []) or getattr(tab, "_pinned", False)
                    or (getattr(tab, "loading", False) and not manual)
                    or page.recentlyAudible() or page.devToolsPage() is not None or is_asleep(tab)
                    or tab in getattr(self.win, "_devtools", {})
                    or (agent is not None and agent.running and agent.tab is tab)
                    or tab.url().scheme() in ("", "about", "data", "view-source"))

    def check(self):
        if not self.enabled():
            return
        limit = self.minutes() * 60
        now = time.monotonic()
        for tab in self.win.tab_list():
            if now - getattr(tab, "_last_active", now) >= limit and self.can_sleep(tab):
                self.sleep(tab)

    def sleep(self, tab, manual: bool = False) -> bool:
        if not self.can_sleep(tab, manual):
            return False
        tab.page().setLifecycleState(ASLEEP)
        self.mark(tab)
        return True

    def wake(self, tab):
        touch(tab)
        if is_asleep(tab):
            tab.page().setLifecycleState(AWAKE)
            self.win.strip.refresh(tab)   # puts the full-colour icon back

    def mark(self, tab):
        """Greyed-out icon and a tooltip on sleeping tabs."""
        i = self.win.tabs.indexOf(tab)
        if i < 0:
            return
        bar = self.win.tabs.tabBar()
        asleep = is_asleep(tab)
        icon = getattr(tab, "_icon_full", None)
        collapsed = self.win.strip.is_collapsed_head(tab)   # a collapsed group shows only its label
        if asleep and not collapsed and icon is not None and not icon.isNull():
            bar.setTabIcon(i, QIcon(icon.pixmap(QSize(16, 16), QIcon.Disabled)))   # greyed out while asleep
        title = getattr(tab, "_title_full", "") or "New tab"
        bar.setTabToolTip(i, f"{title}\n(sleeping to save memory, click to wake)" if asleep else title)
