"""Address bar autocomplete, like Chrome's: inline completion of sites you've visited, plus a drop-down of matching
history and bookmarks and the search engine's own suggestions. Off when the "autocomplete" setting is off."""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QCompleter

from . import icons

# OpenSearch suggestion endpoints: each returns [query, [suggestion, ...]]
SUGGEST = {
    "google": "https://suggestqueries.google.com/complete/search?client=firefox&q=%s",
    "duckduckgo": "https://duckduckgo.com/ac/?type=list&q=%s",
    "bing": "https://api.bing.com/osjson.aspx?query=%s",
    "brave": "https://search.brave.com/api/suggest?q=%s",
    "ecosia": "https://ac.ecosia.org/autocomplete?type=list&q=%s",
}
VALUE = Qt.UserRole + 1    # what goes in the address bar when the row is picked
MAX_SITES, MAX_SEARCHES = 5, 5
_PREFIX = re.compile(r"^(https?://)?(www\.)?", re.I)


def strip_url(url: str) -> str:
    """'https://www.github.com/x' -> 'github.com/x' (the form people type)."""
    return _PREFIX.sub("", url)


def inline_completion(typed: str, urls: list[str]) -> str:
    """The rest of the first visited site that starts with what was typed: completes to the end of the host, or to
    the next path segment once the host is typed. '' when nothing fits."""
    t = typed.lower()
    if not t or " " in t:
        return ""
    for url in urls:
        s = strip_url(url).rstrip("/")
        if not s.lower().startswith(t) or len(s) == len(t):
            continue
        host_end = s.find("/")
        if host_end < 0 or len(t) < host_end:
            end = len(s) if host_end < 0 else host_end
        else:
            nxt = s.find("/", len(t) + 1)
            end = len(s) if nxt < 0 else nxt
        return s[len(t):end]
    return ""


def parse_suggestions(data: bytes) -> list[str]:
    try:
        obj = json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        return []
    if isinstance(obj, list) and len(obj) > 1 and isinstance(obj[1], list):
        return [s for s in obj[1] if isinstance(s, str)]
    return []


class Omnibox(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.addr, self.store = win, win.addr, win.store
        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self.model, self)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.completer.setCompletionRole(VALUE)
        self.completer.setMaxVisibleItems(MAX_SITES + MAX_SEARCHES + 1)
        self.completer.setWidget(self.addr)
        popup = self.completer.popup()
        popup.setIconSize(QSize(16, 16))
        popup.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        popup.setStyleSheet("QListView{background:#1d2029;border:1px solid #2c303c;border-radius:8px;padding:4px;"
                            "outline:0}QListView::item{padding:6px 8px;border-radius:6px}"
                            "QListView::item:selected,QListView::item:hover{background:rgba(255,255,255,0.10);"
                            "color:#ffffff}")
        self.completer.highlighted[str].connect(self._show_value)
        self.completer.activated[str].connect(self._picked)
        self.net = QNetworkAccessManager(self)
        self._reply = None
        self._typed = ""
        self._suggestions: list[str] = []
        self._debounce = QTimer(self, singleShot=True, interval=120, timeout=self._fetch)
        self.addr.textEdited.connect(self._edited)

    def enabled(self) -> bool:
        return bool(self.store.get("autocomplete"))

    # -- typing
    def _edited(self, text: str):
        grew = len(text) > len(self._typed) and text.startswith(self._typed)
        self._typed = text
        if not self.enabled() or not text.strip():
            self.completer.popup().hide()
            self._suggestions = []
            return
        if grew and self.addr.cursorPosition() == len(text):
            rest = inline_completion(text, self._site_urls(text))
            if rest:
                self.addr.setText(text + rest)
                self.addr.setSelection(len(text), len(rest))
        self._suggestions = [s for s in self._suggestions if s.lower().startswith(text.strip().lower())]
        self._rebuild()
        self._debounce.start()

    def _show_value(self, value: str):
        self.addr.setText(value)

    def _picked(self, value: str):
        self.addr.setText(value)
        self.completer.popup().hide()
        self.win._go()

    # -- rows
    def _site_urls(self, text: str) -> list[str]:
        """Visited and bookmarked URLs matching text, most visited first; prefix matches lead."""
        rows = sorted(self.store.history(text.strip(), limit=60), key=lambda r: (-(r[2] or 0), -(r[3] or 0)))
        urls = [r[0] for r in rows] + [b["url"] for b in self.store.bookmarks
                                      if text.lower() in (b["url"] + " " + b.get("title", "")).lower()]
        urls = list(dict.fromkeys(urls))
        t = text.lower()
        return sorted(urls, key=lambda u: not strip_url(u).lower().startswith(t))

    def _rebuild(self):
        text = self._typed.strip()
        self.model.clear()
        full = self.addr.text().strip()
        go = self.win.to_qurl(full)
        is_search = go.toString() == self.win.search_url(full)
        engine = self.win.search_engine_name()
        self._add("search" if is_search else "globe",
                  f"{full}  — Search {engine}" if is_search else full, full)
        titles = {b["url"]: b.get("title", "") for b in self.store.bookmarks}
        history = {r[0]: r[1] for r in self.store.history(text, limit=60)}
        for url in self._site_urls(text)[:MAX_SITES]:
            title = titles.get(url) or history.get(url) or ""
            label = f"{title}  —  {strip_url(url)}" if title else strip_url(url)
            self._add("star" if url in titles else "history", label, url)
        for s in self._suggestions[:MAX_SEARCHES]:
            if s.strip().lower() != full.lower():
                self._add("search", s, s)
        self.completer.complete()
        popup = self.completer.popup()
        popup.setCurrentIndex(self.model.index(-1, -1))
        # fit every row (Qt's own estimate ignores the stylesheet padding and adds a scroll bar)
        rows = sum(popup.sizeHintForRow(i) for i in range(self.model.rowCount()))
        popup.resize(popup.width(), rows + 2 * popup.frameWidth() + 10)

    def _add(self, icon_name: str, label: str, value: str):
        item = QStandardItem(icons.icon(icon_name), label)
        item.setData(value, VALUE)
        item.setToolTip(value)
        self.model.appendRow(item)

    # -- search suggestions
    def _fetch(self):
        text = self._typed.strip()
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        if not text or not self.enabled() or self.win.to_qurl(text).toString() != self.win.search_url(text):
            return
        engine = self.store.get("search_engine") or "duckduckgo"
        template = SUGGEST.get(engine, SUGGEST["duckduckgo"])
        req = QNetworkRequest(QUrl(template % QUrl.toPercentEncoding(text).data().decode()))
        req.setHeader(QNetworkRequest.UserAgentHeader, "Mozilla/5.0 Pelagic/1.0")
        reply = self._reply = self.net.get(req)
        reply.finished.connect(lambda r=reply, t=text: self._got(r, t))

    def _got(self, reply, text: str):
        reply.deleteLater()
        if reply is self._reply:
            self._reply = None
        if text != self._typed.strip() or reply.error() != reply.NetworkError.NoError:
            return
        self._suggestions = parse_suggestions(bytes(reply.readAll()))
        if self.addr.hasFocus():
            self._rebuild()

    def hide(self):
        self.completer.popup().hide()
        self._debounce.stop()
        self._typed = ""
