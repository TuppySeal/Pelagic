"""Domain blocking in the style of Pi-hole: whole domains (and their subdomains) never load, in pages or as parts
of pages. Separate from the ad blocker: it works when the ad blocker is off or paused on a site.

Per profile settings:
  "domain_block"        on/off (default on; does nothing until a domain or list is added)
  "blocked_domains"     domains typed by the user, e.g. ["example.com", "ads.example.net"]
  "allowed_domains"     never blocked, even when a list has them (Pi-hole's allowlist)
  "blocklist_urls"      hosts-format or plain domain lists to download, e.g. StevenBlack's hosts file

Downloaded lists are cached in a shared folder and refreshed every few days, like the ad blocker's lists.
Lines can be "example.com", "*.example.com", "||example.com^", "0.0.0.0 example.com" or "127.0.0.1 example.com";
"#" and "!" start comments. Blocking a domain also blocks every subdomain of it.
"""
from __future__ import annotations

import hashlib
import html
import re
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal

REFRESH_SECONDS = 3 * 24 * 3600
MAX_LIST_BYTES = 64 * 1024 * 1024
SUGGESTED_LISTS = {   # shown in the dialog; nothing is downloaded until the user adds one
    "StevenBlack unified hosts (ads and malware)":
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "OISD small": "https://small.oisd.nl/domainswild",
    "Hagezi Multi Light": "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/light.txt",
}
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)*[a-z0-9-]{1,63}$")
_SKIP = {"localhost", "localhost.localdomain", "local", "broadcasthost", "ip6-localhost", "ip6-loopback",
         "0.0.0.0", "ip6-localnet", "ip6-mcastprefix", "ip6-allnodes", "ip6-allrouters", "ip6-allhosts"}
_ADDR = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f:]+:[0-9a-f:]*)$")


def parse_domain(line: str) -> str | None:
    """One list line -> a bare lower-case domain, or None for comments, addresses and junk."""
    line = line.split("#", 1)[0].strip().lower()
    if not line or line.startswith(("!", "[")):
        return None
    parts = line.split()
    if len(parts) >= 2 and _ADDR.match(parts[0]):   # hosts file: "0.0.0.0 ads.example.com"
        line = parts[1]
    elif len(parts) != 1:
        return None
    if "://" in line:   # a pasted address: keep its host
        line = QUrl(line).host().lower()
    line = line.removeprefix("||").removesuffix("^").removeprefix("*.").removeprefix(".").rstrip(".")
    if line in _SKIP or _ADDR.match(line) or not _DOMAIN.match(line) or "." not in line:
        return None
    return line


def parse_text(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        d = parse_domain(line)
        if d:
            out.add(d)
    return out


def _parents(host: str):
    host = host.lower().rstrip(".")
    while host:
        yield host
        host = host.partition(".")[2]


def _cache_name(url: str) -> str:
    return "list-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".txt"


class Lists(QObject):
    """Downloaded blocklists (shared by all profiles): url -> set of domains, built off the UI thread."""
    ready = Signal()

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.domains: dict[str, frozenset[str]] = {}
        self.errors: dict[str, str] = {}
        self._loading = False
        self._lock = threading.Lock()

    def load(self, urls: list[str], force_download: bool = False):
        with self._lock:
            if self._loading:
                return
            self._loading = True
        threading.Thread(target=self._work, args=(list(urls), force_download), daemon=True).start()

    def _work(self, urls, force):
        try:
            found, errors = {}, {}
            for url in urls:
                path = self.folder / _cache_name(url)
                stale = not path.exists() or time.time() - path.stat().st_mtime > REFRESH_SECONDS
                if force or stale:
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "Pelagic/1.0"})
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            data = resp.read(MAX_LIST_BYTES + 1)
                        if len(data) > MAX_LIST_BYTES:
                            raise OSError("the list is too big")
                        tmp = path.with_suffix(".tmp")
                        tmp.write_bytes(data)
                        tmp.replace(path)
                    except (OSError, ValueError) as e:
                        errors[url] = str(getattr(e, "reason", e))   # keep the cached copy, if any
                if path.exists():
                    found[url] = frozenset(parse_text(path.read_text(encoding="utf-8", errors="replace")))
            self.domains, self.errors = found, errors
        finally:
            with self._lock:
                self._loading = False
            try:
                self.ready.emit()
            except RuntimeError:   # the app closed while the lists were loading
                pass


_LISTS: dict[str, Lists] = {}


def shared_lists(folder: Path) -> Lists:
    key = str(Path(folder).resolve())
    if key not in _LISTS:
        _LISTS[key] = Lists(folder)
    return _LISTS[key]


class DomainBlocker:
    """Per-profile view of the blocklist. Rebuilt when the settings change (refresh()); checks are set lookups."""

    def __init__(self, store, lists: Lists):
        self.store, self.lists = store, lists
        self.blocked: set[str] = set()
        self.allowed: set[str] = set()
        self._urls: list[str] = []
        lists.ready.connect(self.refresh)
        self.refresh()
        if self._urls:
            lists.load(self._urls)

    def enabled(self) -> bool:
        return self.store.get("domain_block") is not False

    def refresh(self):
        self._urls = [u for u in (self.store.get("blocklist_urls") or []) if u]
        mine = {d for d in (parse_domain(x) for x in self.store.get("blocked_domains") or []) if d}
        for url in self._urls:
            mine |= self.lists.domains.get(url, frozenset())
        self.blocked = mine
        self.allowed = {d for d in (parse_domain(x) for x in self.store.get("allowed_domains") or []) if d}

    def update_lists(self, force: bool = False):
        self.refresh()
        self.lists.load(self._urls, force_download=force)

    def match(self, host: str) -> str | None:
        """The blocked domain that covers host, or None."""
        if not host or not self.blocked or not self.enabled():
            return None
        hit = None
        for h in _parents(host):
            if h in self.allowed:
                return None
            if hit is None and h in self.blocked:
                hit = h
        return hit

    def add(self, domain: str) -> str | None:
        d = parse_domain(domain)
        if not d:
            return None
        mine = [x for x in self.store.get("blocked_domains") or [] if parse_domain(x) != d]
        self.store.set("blocked_domains", mine + [d])
        self.store.set("allowed_domains", [x for x in self.store.get("allowed_domains") or [] if parse_domain(x) != d])
        self.refresh()
        return d

    def remove(self, domain: str):
        """Unblocks domain: drops it from the user's list, and allows it if a downloaded list still has it."""
        d = parse_domain(domain) or domain
        self.store.set("blocked_domains", [x for x in self.store.get("blocked_domains") or [] if parse_domain(x) != d])
        self.refresh()
        if self.match(d):
            self.store.set("allowed_domains", list(self.store.get("allowed_domains") or []) + [d])
            self.refresh()

    def counts(self) -> tuple[int, int]:
        """(domains the user typed, domains from downloaded lists)"""
        mine = len({d for d in (parse_domain(x) for x in self.store.get("blocked_domains") or []) if d})
        listed = sum(len(self.lists.domains.get(u, ())) for u in self._urls)
        return mine, listed


# ------------------------------------------------------------ the page shown instead of a blocked site
def is_blocked_page(url: QUrl) -> bool:
    return url.isLocalFile() and url.fileName().startswith("blocked-")


def parse_action(url: QUrl) -> str | None:
    q = dict(p.split("=", 1) for p in url.query().split("&") if "=" in p)
    act = q.get("pelagic", "")
    return act if act in ("blocked-back", "blocked-unblock") else None


def build_page(url: QUrl, domain: str) -> str:
    host = html.escape(url.host())
    dom = html.escape(domain)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Blocked: {host}</title><style>
body{{margin:0;background:#16222e;color:#e8eef4;font:15px/1.55 "Segoe UI",system-ui,sans-serif}}
main{{max-width:620px;margin:12vh auto 0;padding:0 24px}}
.icon{{font-size:46px;line-height:1}} h1{{font-size:26px;font-weight:600;margin:14px 0 10px}}
p{{margin:0 0 14px;color:#b9c7d4}} .host{{font-weight:600;color:#fff;word-break:break-all}}
.row{{display:flex;gap:12px;align-items:center;margin-top:26px;flex-wrap:wrap}}
a.b{{background:#3d8bd9;color:#fff;padding:9px 18px;border-radius:6px;text-decoration:none;font-weight:600}}
a.l{{color:#9ccaf5}}
</style></head><body><main>
<div class="icon">⛔</div><h1>This site is blocked</h1>
<p><span class="host">{host}</span> is on your blocked domains list (as <b>{dom}</b>), so Pelagic didn't open it.</p>
<p>Change the list in Settings → Privacy → Blocked domains.</p>
<div class="row"><a class="b" href="?pelagic=blocked-back">Go back</a>
<a class="l" href="?pelagic=blocked-unblock">Unblock {dom}</a></div>
</main></body></html>"""


def show_blocked(tab, url: QUrl, domain: str, store):
    folder = store.root / "warnings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"blocked-{id(tab):x}.html"
    path.write_text(build_page(url, domain), encoding="utf-8")
    tab._blocked_target = url.toString()
    tab._blocked_domain = domain
    tab.load(QUrl.fromLocalFile(str(path)))


def handle_action(tab, action: str, blocker: DomainBlocker):
    target = getattr(tab, "_blocked_target", "")
    if action == "blocked-unblock" and target:
        blocker.remove(getattr(tab, "_blocked_domain", "") or QUrl(target).host())
        tab.load(QUrl(target))
    elif action == "blocked-back":
        hist = tab.history()
        if hist.canGoBack():
            tab.back()
        else:
            win = tab.window()
            tab.load(win.home_url() if hasattr(win, "home_url") else QUrl("about:blank"))
