"""Unsafe-site warnings: a full-page "Dangerous site" / "Deceptive site" warning before opening known phishing and
malware addresses, and dangerous downloads are stopped.

Google's own Safe Browsing service needs a Google API key, so Pelagic uses free public threat lists instead
(Phishing Army, OpenPhish and abuse.ch URLhaus). They are downloaded every few hours and all checking happens on this
computer: the sites you visit are never sent anywhere. Coverage is good but not the same as Chrome's.

Settings: "safe_browsing" (on by default). "Visit anyway" lasts until Pelagic closes.
"""
from __future__ import annotations

import html
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QUrl

# file -> (address, what it lists, kind)
SOURCES = {
    "phishing-army.txt": ("https://phishing.army/download/phishing_army_blocklist.txt", "hosts", "phishing"),
    "openphish.txt": ("https://openphish.com/feed.txt", "urls", "phishing"),
    "urlhaus-hosts.txt": ("https://urlhaus.abuse.ch/downloads/hostfile/", "hosts", "malware"),
}
REFRESH_SECONDS = 6 * 3600
# Big sites that host other people's pages: only a full listed address can flag a page on these, never the host.
SHARED_HOSTS = ("google.com", "googleusercontent.com", "github.io", "github.com", "microsoft.com", "live.com",
                "office.com", "sharepoint.com", "dropbox.com", "amazonaws.com", "cloudfront.net", "azurewebsites.net",
                "blogspot.com", "wordpress.com", "weebly.com", "wixsite.com", "firebaseapp.com", "web.app",
                "pages.dev", "workers.dev", "vercel.app", "netlify.app", "notion.site", "forms.office.com",
                "docs.google.com", "apple.com", "icloud.com", "facebook.com", "instagram.com", "youtube.com")


def _bare(host: str) -> str:
    host = host.lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def _shared(host: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in SHARED_HOSTS)


class ThreatLists:
    """Downloads/caches the lists in a shared folder and keeps an index in memory."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.hosts: dict[str, str] = {}               # bare host -> kind
        self.urls: dict[str, list[tuple[str, str]]] = {}   # bare host -> [(address prefix, kind)]
        self.updated = 0.0
        self._loading = False

    def load(self, force: bool = False, wait: bool = False):
        if self._loading:
            return
        self._loading = True
        t = threading.Thread(target=self._work, args=(force,), daemon=True)
        t.start()
        if wait:
            t.join()

    def _work(self, force: bool):
        try:
            for name, (url, _what, _kind) in SOURCES.items():
                path = self.folder / name
                if force or not path.exists() or time.time() - path.stat().st_mtime > REFRESH_SECONDS:
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "Pelagic/1.0"})
                        data = urllib.request.urlopen(req, timeout=30).read()
                    except OSError:
                        continue      # keep the cached copy until next time
                    if data.strip():
                        tmp = path.with_suffix(".tmp")
                        tmp.write_bytes(data)
                        tmp.replace(path)
            self.index()
        finally:
            self._loading = False

    def index(self):
        hosts, urls = {}, {}
        for name, (_url, what, kind) in SOURCES.items():
            path = self.folder / name
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "!")):
                    continue
                if what == "hosts":
                    host = _bare(line.split()[-1])
                    if host and host != "localhost" and "." in host and not _shared(host):
                        hosts.setdefault(host, kind)
                else:
                    u = QUrl(line)
                    if u.host():
                        prefix = _bare(u.host()) + (u.path() or "/")
                        urls.setdefault(_bare(u.host()), []).append((prefix.rstrip("/"), kind))
        self.hosts, self.urls = hosts, urls
        self.updated = max((p.stat().st_mtime for p in self.folder.glob("*.txt")), default=0)

    def verdict(self, url: QUrl) -> str | None:
        """'phishing', 'malware' or None."""
        if url.scheme() not in ("http", "https"):
            return None
        host = _bare(url.host())
        kind = self.hosts.get(host)
        if kind:
            return kind
        here = host + (url.path() or "/")
        for prefix, kind in self.urls.get(host, ()):
            if here == prefix or here.startswith(prefix + "/") or here.rstrip("/") == prefix:
                return kind
        return None


_LISTS: dict[str, ThreatLists] = {}


def shared_lists(folder: Path) -> ThreatLists:
    key = str(Path(folder).resolve())
    if key not in _LISTS:
        _LISTS[key] = ThreatLists(folder)
        _LISTS[key].load()
    return _LISTS[key]


class Guard:
    """Per-profile switch over the shared lists, plus the sites the user chose to visit anyway this session."""

    def __init__(self, lists: ThreatLists, store):
        self.lists, self.store = lists, store
        self.allowed: set[str] = set()

    def enabled(self) -> bool:
        return self.store.get("safe_browsing") is not False

    def check(self, url: QUrl) -> str | None:
        if not self.enabled() or _bare(url.host()) in self.allowed:
            return None
        if time.time() - self.lists.updated > REFRESH_SECONDS and not self.lists._loading:
            self.lists.load()      # long-running sessions keep the lists fresh
        return self.lists.verdict(url)


# ---------------------------------------------------------------- the warning page
TEXT = {
    "phishing": ("Deceptive site ahead",
                 "This site is on public lists of phishing sites. It may try to trick you into giving away "
                 "passwords, card numbers or other personal details, often by pretending to be a site you trust."),
    "malware": ("Dangerous site ahead",
                "This site is on public lists of sites that spread malware. Visiting it or downloading from it "
                "could harm your computer or steal your information."),
}


def is_warning(url: QUrl) -> bool:
    return url.isLocalFile() and url.fileName().startswith("unsafe-")


def parse_action(url: QUrl) -> str | None:
    q = dict(p.split("=", 1) for p in url.query().split("&") if "=" in p)
    act = q.get("pelagic", "")
    return act if act in ("unsafe-back", "unsafe-continue") else None


def build_page(url: QUrl, kind: str) -> str:
    title, body = TEXT.get(kind, TEXT["phishing"])
    host = html.escape(url.host())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
body{{margin:0;background:#a3281f;color:#fff;font:15px/1.55 "Segoe UI",system-ui,sans-serif}}
main{{max-width:620px;margin:12vh auto 0;padding:0 24px}}
.icon{{font-size:46px;line-height:1}} h1{{font-size:26px;font-weight:600;margin:14px 0 10px}}
p{{margin:0 0 14px;color:#ffe9e6}} .host{{font-weight:600;color:#fff;word-break:break-all}}
.row{{display:flex;gap:12px;align-items:center;margin-top:26px;flex-wrap:wrap}}
a.b{{background:#fff;color:#a3281f;padding:9px 18px;border-radius:6px;text-decoration:none;font-weight:600}}
details{{margin-top:28px;color:#ffe9e6}} summary{{cursor:pointer}} details a{{color:#fff}}
small{{display:block;margin-top:18px;opacity:.75}}
</style></head><body><main>
<div class="icon">⚠</div><h1>{title}</h1>
<p>Pelagic stopped <span class="host">{host}</span> from opening.</p><p>{body}</p>
<div class="row"><a class="b" href="?pelagic=unsafe-back">Back to safety</a></div>
<details><summary>Details</summary><p>If you understand the risks, you can
<a href="?pelagic=unsafe-continue">visit this unsafe site anyway</a> (until Pelagic closes).</p>
<small>Checked on this computer against public threat lists (Phishing Army, OpenPhish, URLhaus). The address was
not sent anywhere.</small></details>
</main></body></html>"""


def warning_folder(store) -> Path:
    d = store.root / "warnings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def show_warning(tab, url: QUrl, kind: str, store):
    """Replace the page with the warning; the address bar keeps showing the blocked address."""
    path = warning_folder(store) / f"unsafe-{id(tab):x}.html"
    path.write_text(build_page(url, kind), encoding="utf-8")
    tab._unsafe_target = url.toString()
    tab._unsafe_kind = kind
    tab.load(QUrl.fromLocalFile(str(path)))


def handle_action(tab, action: str, guard: Guard):
    target = getattr(tab, "_unsafe_target", "")
    if action == "unsafe-continue" and target:
        guard.allowed.add(_bare(QUrl(target).host()))
        tab.load(QUrl(target))
    elif action == "unsafe-back":
        hist = tab.history()
        if hist.canGoBack():
            tab.back()
        else:
            win = tab.window()
            tab.load(win.home_url() if hasattr(win, "home_url") else QUrl("about:blank"))
