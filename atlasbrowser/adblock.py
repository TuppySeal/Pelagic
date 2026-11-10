"""Built-in ad and tracker blocker using the standard EasyList / EasyPrivacy filter lists.

Network rules are indexed by a token (like uBlock Origin) so each request checks only a handful of rules; the
interceptor runs on the UI thread and must stay fast. Site-specific element-hiding rules (example.com##.ad) are
applied as a small style sheet after the page loads. The lists are shared by all profiles; whether the blocker is
on, and the sites it is paused on, are per profile.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInfo, QWebEngineUrlRequestInterceptor

LISTS = {   # official address first, then the EasyList project's GitHub mirror
    "easylist.txt": ("https://easylist.to/easylist/easylist.txt",
                     "https://raw.githubusercontent.com/easylist/easylist/gh-pages/easylist.txt"),
    "easyprivacy.txt": ("https://easylist.to/easylist/easyprivacy.txt",
                        "https://raw.githubusercontent.com/easylist/easylist/gh-pages/easyprivacy.txt"),
}
REFRESH_SECONDS = 4 * 24 * 3600

_RT = QWebEngineUrlRequestInfo.ResourceType
TYPES = {
    "script": {_RT.ResourceTypeScript},
    "image": {_RT.ResourceTypeImage, _RT.ResourceTypeFavicon},
    "stylesheet": {_RT.ResourceTypeStylesheet},
    "xmlhttprequest": {_RT.ResourceTypeXhr},
    "subdocument": {_RT.ResourceTypeSubFrame},
    "media": {_RT.ResourceTypeMedia},
    "font": {_RT.ResourceTypeFontResource},
    "ping": {_RT.ResourceTypePing, _RT.ResourceTypeCspReport},
    "websocket": {_RT.ResourceTypeWebSocket} if hasattr(_RT, "ResourceTypeWebSocket") else set(),
    "object": {_RT.ResourceTypeObject, _RT.ResourceTypePluginResource},
    "other": {_RT.ResourceTypeSubResource, _RT.ResourceTypeWorker, _RT.ResourceTypeSharedWorker,
              _RT.ResourceTypePrefetch, _RT.ResourceTypeServiceWorker, _RT.ResourceTypeUnknown},
}
# Options this engine understands; a rule with any other option is skipped rather than half-applied.
_KNOWN = set(TYPES) | {"third-party", "3p", "first-party", "1p", "domain", "match-case", "xhr", "css", "frame",
                       "important", "all"}
_TOKEN = re.compile(r"[a-z0-9%]{3,}")


def _host_parents(host: str):
    parts = host.split(".")
    for i in range(len(parts) - 1):
        yield ".".join(parts[i:])


def _base(host: str) -> str:
    parts = host.split(".")
    # good-enough registrable domain: last two labels, or three for co.uk-style names
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class Rule:
    __slots__ = ("regex", "types", "party", "include", "exclude", "exception")

    def __init__(self, regex, types, party, include, exclude, exception):
        self.regex, self.types, self.party = regex, types, party
        self.include, self.exclude, self.exception = include, exclude, exception

    def applies(self, url: str, rtype, third: bool, page_host: str) -> bool:
        if self.types is not None and rtype not in self.types:
            return False
        if self.party is not None and self.party != third:
            return False
        if self.include and not any(h in self.include for h in _host_parents(page_host)):
            return False
        if self.exclude and any(h in self.exclude for h in _host_parents(page_host)):
            return False
        return self.regex is None or bool(self.regex.search(url))


def _pattern_to_regex(p: str) -> str:
    out, i = [], 0
    if p.startswith("||"):
        out.append(r"^[a-z][a-z0-9+.-]*://([^/?#]*\.)?")
        i = 2
    elif p.startswith("|"):
        out.append("^")
        i = 1
    end = p.endswith("|") and not p.endswith("^|")
    body = p[i:-1] if end else p[i:]
    for ch in body:
        if ch == "*":
            out.append(".*")
        elif ch == "^":
            out.append(r"(?:[^a-z0-9_.%-]|$)")
        else:
            out.append(re.escape(ch))
    if end:
        out.append("$")
    return "".join(out)


class FilterEngine:
    def __init__(self):
        self.block_domains: dict[str, list[Rule] | None] = {}   # ||host^ rules; None means "no options"
        self.allow_domains: dict[str, list[Rule] | None] = {}
        self.block_index: dict[str, list[Rule]] = {}
        self.allow_index: dict[str, list[Rule]] = {}
        self.block_any: list[Rule] = []
        self.allow_any: list[Rule] = []
        self.cosmetic: dict[str, list[str]] = {}
        self.cosmetic_except: dict[str, set[str]] = {}
        self.rules = 0

    # -- parsing
    def add_text(self, text: str):
        for line in text.splitlines():
            self.add_line(line.strip())

    def add_line(self, line: str):
        if not line or line.startswith(("!", "[")):
            return
        if "#@#" in line:
            hosts, _, sel = line.partition("#@#")
            for h in filter(None, hosts.split(",")):
                self.cosmetic_except.setdefault(h.strip(), set()).add(sel)
            return
        if "##" in line:
            hosts, _, sel = line.partition("##")
            if not hosts or sel.startswith(("+js", "^")) or ":-abp-" in sel or ":has-text" in sel \
                    or ":style(" in sel or ":remove" in sel or ":matches-" in sel or ":upward" in sel \
                    or ":xpath" in sel or ":min-text" in sel or ":watch-attr" in sel:
                return   # generic hiding is too heavy to inject everywhere; scriptlets aren't supported
            for h in filter(None, (x.strip() for x in hosts.split(","))):
                if not h.startswith("~"):
                    self.cosmetic.setdefault(h, []).append(sel)
            return
        if "#?#" in line or "#$#" in line or "#%#" in line:
            return
        exception = line.startswith("@@")
        if exception:
            line = line[2:]
        pattern, opts = line, ""
        if "$" in line:
            pattern, _, opts = line.rpartition("$")
        types, party, include, exclude = None, None, set(), set()
        for opt in filter(None, (o.strip() for o in opts.split(","))):
            neg = opt.startswith("~")
            name = opt[1:] if neg else opt
            name, _, value = name.partition("=")
            if name not in _KNOWN:
                return
            if name == "domain":
                for d in value.split("|"):
                    (exclude if d.startswith("~") else include).add(d.lstrip("~"))
            elif name in ("third-party", "3p"):
                party = not neg
            elif name in ("first-party", "1p"):
                party = neg
            elif name in ("match-case", "important"):
                continue
            elif name == "all":
                continue
            else:
                key = {"xhr": "xmlhttprequest", "css": "stylesheet", "frame": "subdocument"}.get(name, name)
                if neg:
                    types = (types if types is not None else set().union(*TYPES.values())) - TYPES[key]
                else:
                    types = (types or set()) | TYPES[key]
        if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 2:
            return   # raw regex rules are rare and expensive; skip
        pattern = pattern.lower()
        if not pattern or pattern in ("*", "|", "||"):
            if not (include or exclude):
                return
        simple = re.fullmatch(r"\|\|([a-z0-9.-]+)\^?", pattern)
        has_opts = types is not None or party is not None or include or exclude
        if simple:
            target = self.allow_domains if exception else self.block_domains
            host = simple.group(1)
            if not has_opts:
                target[host] = None
            elif target.get(host, []) is not None:
                target.setdefault(host, []).append(Rule(None, types, party, include, exclude, exception))
            self.rules += 1
            return
        try:
            rx = re.compile(_pattern_to_regex(pattern)) if pattern else None
        except re.error:
            return
        rule = Rule(rx, types, party, include, exclude, exception)
        tokens = [t for t in _TOKEN.findall(re.sub(r"[*^|]", " ", pattern)) if "%" not in t]
        index, anylist = (self.allow_index, self.allow_any) if exception else (self.block_index, self.block_any)
        if tokens:
            index.setdefault(max(tokens, key=len), []).append(rule)
        else:
            anylist.append(rule)
        self.rules += 1

    # -- matching
    def _match(self, domains, index, anylist, url, host, rtype, third, page_host) -> bool:
        for h in _host_parents(host):
            if h in domains:
                rules = domains[h]
                if rules is None or any(r.applies(url, rtype, third, page_host) for r in rules):
                    return True
        for tok in set(_TOKEN.findall(url)):
            for r in index.get(tok, ()):
                if r.applies(url, rtype, third, page_host):
                    return True
        return any(r.applies(url, rtype, third, page_host) for r in anylist)

    def should_block(self, url: str, host: str, rtype, page_host: str) -> bool:
        url, host, page_host = url.lower(), host.lower(), (page_host or "").lower()
        third = bool(page_host) and _base(host) != _base(page_host)
        if not self._match(self.block_domains, self.block_index, self.block_any, url, host, rtype, third, page_host):
            return False
        return not self._match(self.allow_domains, self.allow_index, self.allow_any, url, host, rtype, third,
                               page_host)

    def hide_css(self, page_host: str) -> str:
        sels, skip = [], set()
        for h in _host_parents(page_host.lower()):
            skip |= self.cosmetic_except.get(h, set())
        for h in _host_parents(page_host.lower()):
            sels.extend(s for s in self.cosmetic.get(h, ()) if s not in skip)
        if not sels:
            return ""
        return ",\n".join(dict.fromkeys(sels)) + " { display: none !important; }"


class FilterLists(QObject):
    """Downloads/caches the lists (shared folder) and builds one engine in the background."""
    ready = Signal()

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.engine: FilterEngine | None = None
        self.updated = 0.0
        self._loading = False

    def load(self, force_download: bool = False):
        if self._loading:
            return
        self._loading = True
        threading.Thread(target=self._work, args=(force_download,), daemon=True).start()

    def _work(self, force: bool):
        try:
            for name, urls in LISTS.items():
                path = self.folder / name
                stale = not path.exists() or time.time() - path.stat().st_mtime > REFRESH_SECONDS
                for url in urls if (force or stale) else ():
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "Pelagic/1.0"})
                        data = urllib.request.urlopen(req, timeout=30).read()
                    except OSError:
                        continue   # try the mirror; otherwise keep the cached copy until next start
                    if b"[Adblock" in data[:200] or data.startswith(b"!"):
                        tmp = path.with_suffix(".tmp")
                        tmp.write_bytes(data)
                        tmp.replace(path)
                        break
            engine = FilterEngine()
            for name in LISTS:
                path = self.folder / name
                if path.exists():
                    engine.add_text(path.read_text(encoding="utf-8", errors="replace"))
            custom = self.folder / "my-filters.txt"
            if custom.exists():
                engine.add_text(custom.read_text(encoding="utf-8", errors="replace"))
            self.engine = engine
            self.updated = max((p.stat().st_mtime for p in self.folder.glob("*.txt")), default=0)
        finally:
            self._loading = False
            try:
                self.ready.emit()   # queued to the UI thread for receivers living there
            except RuntimeError:    # the app closed while the lists were loading
                pass


_LISTS: dict[str, FilterLists] = {}


def shared_lists(folder: Path) -> FilterLists:
    key = str(Path(folder).resolve())
    if key not in _LISTS:
        _LISTS[key] = FilterLists(folder)
        _LISTS[key].load()
    return _LISTS[key]


class Blocker(QWebEngineUrlRequestInterceptor):
    """Per-profile request interceptor. Main-frame navigations are never blocked, so sites always open."""

    def __init__(self, lists: FilterLists, store, parent=None, domains=None):
        super().__init__(parent)
        self.lists, self.store = lists, store
        self.domains = domains               # blocklist.DomainBlocker: the user's blocked domains (Pi-hole style)
        self.counts: dict[str, int] = {}     # page host -> requests blocked since it was last loaded

    def enabled(self) -> bool:
        return self.store.get("adblock") is not False

    def paused_on(self, host: str) -> bool:
        allow = self.store.get("adblock_allow") or []
        return any(h in allow for h in _host_parents(host.lower())) if host else False

    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.scheme() not in ("http", "https", "ws", "wss"):
            return
        page = info.firstPartyUrl().host()
        # blocked domains apply to everything, pages included, whether or not the ad blocker is on
        if self.domains is not None and self.domains.match(url.host()):
            info.block(True)
            self.counts[page] = self.counts.get(page, 0) + 1
            return
        engine = self.lists.engine
        if engine is None or not self.enabled():
            return
        rtype = info.resourceType()
        if rtype == _RT.ResourceTypeMainFrame:
            return
        if self.paused_on(page):
            return
        if engine.should_block(url.toString(), url.host(), rtype, page):
            info.block(True)
            self.counts[page] = self.counts.get(page, 0) + 1

    def reset(self, host: str):
        self.counts.pop(host, None)

    def set_paused(self, host: str, paused: bool):
        allow = [h for h in (self.store.get("adblock_allow") or []) if h != host]
        if paused:
            allow.append(host)
        self.store.set("adblock_allow", allow)
