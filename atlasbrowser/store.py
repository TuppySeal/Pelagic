"""Persistent app data: settings, bookmarks, history, API keys (encrypted: DPAPI on Windows, see secretbox)."""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


# the new tab page (Settings → Homepage); see homepage.py
HOMEPAGE_DEFAULTS = {
    "home_shortcuts": [],            # [{"title", "url"}]
    "home_shortcuts_mode": "mine",   # "mine" or "most_visited"
    "home_bg": "ocean",
    "home_bg_color": "#0b1f33",
    "home_bg_image": "",             # a copy kept in the profile's homepage/ folder
    "home_bg_dim": 25,               # percent
    "home_bg_blur": 0,               # px
    "home_show_logo": True,
    "home_show_tagline": True,
    "home_show_search": True,
    "home_show_shortcuts": True,
    "home_show_clock": False,
    "home_show_footer": True,
}


SEARCH_ENGINES = {
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?q=%s"),
    "google": ("Google", "https://www.google.com/search?q=%s"),
    "bing": ("Bing", "https://www.bing.com/search?q=%s"),
    "brave": ("Brave Search", "https://search.brave.com/search?q=%s"),
    "startpage": ("Startpage", "https://www.startpage.com/do/search?q=%s"),
    "ecosia": ("Ecosia", "https://www.ecosia.org/search?q=%s"),
    "perplexity": ("Perplexity", "https://www.perplexity.ai/search?q=%s"),
}


def data_dir() -> Path:
    override = os.environ.get("ATLASBROWSER_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AtlasBrowser"
    else:
        # ~/AtlasBrowser if an earlier version made it there, else $XDG_DATA_HOME (~/.local/share)/AtlasBrowser
        legacy = Path.home() / "AtlasBrowser"
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = legacy if legacy.is_dir() else Path(xdg) / "AtlasBrowser"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    return base


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- encryption (DPAPI on Windows; see secretbox)
from .secretbox import KeyringMissing, _dpapi, protect, unprotect  # noqa: E402,F401


# AI provider and agent settings shared by every profile (they live in the first profile's settings.json).
SHARED_SETTINGS = {"selected", "overrides", "custom", "multi", "model_cache", "price_overrides", "max_steps", "vision",
                   "vision_every_step", "humanize", "batch", "token_saver", "guard", "confirm_all", "context_limit",
                   "core_instructions"}


class Store:
    DEFAULTS = {
        "search_engine": "duckduckgo",
        "home": "atlas:start",
        "autocomplete": True,
        **HOMEPAGE_DEFAULTS,
        "tab_sleep": True,          # put tabs you haven't used for a while to sleep, to save memory
        "tab_sleep_minutes": 30,
        "tab_previews": True,       # a picture of the page when the pointer rests on a tab
        "vertical_tabs": False,     # tabs down the left side instead of along the top
        "download_ask": True,       # ask where to save each download (off: straight to the Downloads folder)
        "spellcheck": False,
        "spellcheck_lang": "en-US",
        "bookmarks_bar": True,
        "selected": "gemini",
        "max_steps": 30,
        "vision": False,
        "humanize": False,
        "batch": True,      # True: model may plan several actions per reply; False: strictly one at a time
        "token_saver": True,
        "vision_every_step": False,
        "memory_file": "",  # Empty uses Atlas Memory.md in the app data folder; access is opt-in.
        "core_instructions": "",
        "context_limit": 128000,  # User-configurable reference, not auto-detected model capacity.
        "price_overrides": {},  # provider:model -> USD per million tokens
        "model_cache": {},  # provider id -> model names fetched from the provider
        "guard": True,
        "adblock": True,         # built-in ad and tracker blocker
        "adblock_allow": [],     # sites the blocker is paused on
        "save_passwords": True,  # offer to save passwords after sign-in (never in private windows)
        "autofill": True,        # offer to save and fill addresses and payment cards
        "safe_browsing": True,   # warn before known phishing / malware sites (local lists, see safebrowsing.py)
        "sync_folder": "",       # folder sync (sync.py); '' = off
        "sync_secrets": False,   # also sync passwords, addresses and cards (encrypted with the sync passphrase)
        "confirm_all": False,
        "overrides": {},   # provider id -> {"model":..., "base_url":...}
        "custom": [],      # user-defined providers
        "multi": [],       # provider ids ticked in Compare mode
        "window": {},
    }

    def __init__(self, root: Path | None = None, shared: "Store | None" = None):
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.shared = shared   # another profile's Store: API keys and SHARED_SETTINGS are read and written there
        self._lock = threading.RLock()
        self.settings = {**self.DEFAULTS, **_load_json(self.root / "settings.json", {})}
        self.bookmarks: list[dict] = _load_json(self.root / "bookmarks.json", [])   # {url, title, folder?}
        self.bookmark_folders: list[str] = _load_json(self.root / "bookmark_folders.json", [])
        self._keys: dict[str, str] | None = None
        self._db = sqlite3.connect(self.root / "history.db", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS history(url TEXT PRIMARY KEY, title TEXT, visits INTEGER, last REAL)")
        self._db.commit()

    # settings
    def get(self, key):
        if self.shared is not None and key in SHARED_SETTINGS:
            return self.shared.get(key)
        return self.settings.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        if self.shared is not None and key in SHARED_SETTINGS:
            return self.shared.set(key, value)
        with self._lock:
            self.settings[key] = value
            _atomic_write(self.root / "settings.json", json.dumps(self.settings, indent=2))

    # bookmarks
    def _save_bookmarks(self):
        _atomic_write(self.root / "bookmarks.json", json.dumps(self.bookmarks, indent=2))

    def is_bookmarked(self, url: str) -> bool:
        return any(b["url"] == url for b in self.bookmarks)

    def toggle_bookmark(self, url: str, title: str) -> bool:
        with self._lock:
            if self.is_bookmarked(url):
                self.bookmarks = [b for b in self.bookmarks if b["url"] != url]
                added = False
            else:
                self.bookmarks.append({"url": url, "title": title or url})
                added = True
            self._save_bookmarks()
            return added

    def remove_bookmark(self, url: str):
        with self._lock:
            self.bookmarks = [b for b in self.bookmarks if b["url"] != url]
            self._save_bookmarks()

    def add_bookmark(self, url: str, title: str, folder: str = ""):
        with self._lock:
            if not self.is_bookmarked(url):
                self.bookmarks.append({"url": url, "title": title or url, **({"folder": folder} if folder else {})})
                self._save_bookmarks()

    def edit_bookmark(self, url: str, title: str | None = None, new_url: str | None = None,
                      folder: str | None = None):
        """Rename, change the address of, or move a bookmark ("" folder = the bookmarks bar itself)."""
        with self._lock:
            for b in self.bookmarks:
                if b["url"] == url:
                    if title is not None:
                        b["title"] = title.strip() or b["url"]
                    if new_url and new_url != url and not self.is_bookmarked(new_url):
                        b["url"] = new_url
                    if folder is not None:
                        if folder:
                            b["folder"] = folder
                        else:
                            b.pop("folder", None)
                    break
            self._save_bookmarks()

    def bookmarks_in(self, folder: str = "") -> list[dict]:
        return [b for b in self.bookmarks if b.get("folder", "") == folder]

    def _save_folders(self):
        _atomic_write(self.root / "bookmark_folders.json", json.dumps(self.bookmark_folders, indent=2))

    def all_folders(self) -> list[str]:
        """Folders in the order they were made, including ones only named on a bookmark."""
        names = list(self.bookmark_folders)
        for b in self.bookmarks:
            if b.get("folder") and b["folder"] not in names:
                names.append(b["folder"])
        return names

    def add_folder(self, name: str) -> str:
        name = name.strip()
        with self._lock:
            if name and name not in self.all_folders():
                self.bookmark_folders.append(name)
                self._save_folders()
        return name

    def rename_folder(self, old: str, new: str):
        new = new.strip()
        with self._lock:
            if not new or new == old or new in self.all_folders():
                return
            self.bookmark_folders = [new if f == old else f for f in self.all_folders()]
            for b in self.bookmarks:
                if b.get("folder") == old:
                    b["folder"] = new
            self._save_folders()
            self._save_bookmarks()

    def delete_folder(self, name: str, keep_bookmarks: bool = True):
        """Removes the folder; its bookmarks move to the bookmarks bar, or are deleted too."""
        with self._lock:
            self.bookmark_folders = [f for f in self.all_folders() if f != name]
            if keep_bookmarks:
                for b in self.bookmarks:
                    if b.get("folder") == name:
                        b.pop("folder")
            else:
                self.bookmarks = [b for b in self.bookmarks if b.get("folder") != name]
            self._save_folders()
            self._save_bookmarks()

    def favicon_path(self, url: str) -> Path:
        """Where a site's icon is cached for the bookmarks bar (one per host)."""
        host = re.sub(r"[^a-z0-9.-]", "_", (urlsplit(url).hostname or "site").lower())
        return self.root / "favicons" / f"{host}.png"

    # history
    def add_history(self, url: str, title: str):
        with self._lock:
            self._db.execute(
                "INSERT INTO history(url,title,visits,last) VALUES(?,?,1,?) "
                "ON CONFLICT(url) DO UPDATE SET title=excluded.title, visits=visits+1, last=excluded.last",
                (url, title or url, time.time()))
            self._db.commit()

    def history(self, query: str = "", limit: int = 500):
        like = f"%{query}%"
        with self._lock:
            return self._db.execute(
                "SELECT url,title,visits,last FROM history WHERE url LIKE ? OR title LIKE ? ORDER BY last DESC LIMIT ?",
                (like, like, limit)).fetchall()

    def delete_history(self, urls):
        with self._lock:
            self._db.executemany("DELETE FROM history WHERE url=?", [(u,) for u in urls])
            self._db.commit()

    # reading list: [{url, title, added, read}]
    def reading_list(self) -> list[dict]:
        return [dict(e) for e in (self.get("reading_list") or []) if isinstance(e, dict) and e.get("url")]

    def add_to_reading_list(self, url: str, title: str) -> bool:
        items = self.reading_list()
        if any(e["url"] == url for e in items):
            return False
        items.insert(0, {"url": url, "title": title or url, "added": time.time(), "read": False})
        self.set("reading_list", items)
        return True

    def update_reading_list(self, url: str, read: bool | None = None, remove: bool = False):
        items = self.reading_list()
        if remove:
            items = [e for e in items if e["url"] != url]
        else:
            for e in items:
                if e["url"] == url and read is not None:
                    e["read"] = bool(read)
        self.set("reading_list", items)

    def clear_history(self):
        with self._lock:
            self._db.execute("DELETE FROM history")
            self._db.commit()

    # API keys
    def _key_file(self) -> Path:
        return self.root / "keys.dat"

    def _load_keys(self) -> dict[str, str]:
        if self._keys is None:
            self._keys = {}
            try:
                raw = base64.b64decode(self._key_file().read_text())
                plain = unprotect(raw)
                self._keys = json.loads(plain.decode("utf-8"))
            except KeyringMissing:
                self._keys = None   # the key is out of reach (locked keyring): never overwrite keys.dat
                return {}
            except Exception:
                self._keys = {}
        return self._keys

    def get_key(self, pid: str) -> str:
        if self.shared is not None:
            return self.shared.get_key(pid)
        return self._load_keys().get(pid, "")

    def set_key(self, pid: str, key: str):
        if self.shared is not None:
            return self.shared.set_key(pid, key)
        with self._lock:
            keys = self._load_keys()
            if self._keys is None:
                unprotect(base64.b64decode(self._key_file().read_text()))   # raises KeyringMissing with the reason
                keys = self._load_keys()
            if key:
                keys[pid] = key
            else:
                keys.pop(pid, None)
            plain = json.dumps(keys).encode("utf-8")
            raw = protect(plain)
            self._key_file().write_text(base64.b64encode(raw).decode("ascii"))
