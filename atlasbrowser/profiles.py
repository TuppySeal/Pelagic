"""Profiles (like Chrome's): each keeps its own history, bookmarks, passwords, cookies/sign-ins, tabs and
automations; API keys and AI provider settings are shared. The first profile is the original data folder,
so existing data stays where it was."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .store import Store, _atomic_write, _load_json

DEFAULT_ID = "default"
COLORS = ["#2FB3B4", "#2f9e6e", "#e0793a", "#d4497a", "#3a8be0", "#c9a227", "#8a8fa3"]


class Profiles:
    """profiles.json in the main data folder: names, colours, last used, and folders waiting to be deleted."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "profiles.json"
        data = _load_json(self.path, {})
        self.items: list[dict] = data.get("profiles") or [{"id": DEFAULT_ID, "name": "Personal", "color": COLORS[0]}]
        self.last: str = data.get("last") or DEFAULT_ID
        self.pending_delete: list[str] = data.get("delete") or []
        if self.get(self.last) is None:
            self.last = DEFAULT_ID

    def _save(self):
        _atomic_write(self.path, json.dumps({"profiles": self.items, "last": self.last,
                                             "delete": self.pending_delete}, indent=2))

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.items if p["id"] == pid), None)

    def folder(self, pid: str) -> Path:
        return self.root if pid == DEFAULT_ID else self.root / "profiles" / pid

    def add(self, name: str, color: str | None = None) -> dict:
        used = {p["color"] for p in self.items}
        p = {"id": uuid.uuid4().hex[:10], "name": name.strip() or "Profile",
             "color": color or next((c for c in COLORS if c not in used), COLORS[len(self.items) % len(COLORS)])}
        self.items.append(p)
        self._save()
        return p

    def update(self, pid: str, **fields):
        p = self.get(pid)
        if p:
            p.update({k: v for k, v in fields.items() if k in ("name", "color") and v})
            self._save()

    def set_last(self, pid: str):
        if self.get(pid) and self.last != pid:
            self.last = pid
            self._save()

    def remove(self, pid: str):
        """Forget a profile now; its folder is deleted on the next start, when no browser engine holds it open."""
        if pid == DEFAULT_ID:
            raise ValueError("The first profile can't be deleted.")
        self.items = [p for p in self.items if p["id"] != pid]
        if pid not in self.pending_delete:
            self.pending_delete.append(pid)
        if self.last == pid:
            self.last = DEFAULT_ID
        self._save()

    def purge_pending(self):
        left = []
        for pid in self.pending_delete:
            folder = self.folder(pid)
            if pid != DEFAULT_ID and folder.parent == self.root / "profiles":
                shutil.rmtree(folder, ignore_errors=True)
                if folder.exists():
                    left.append(pid)
        if left != self.pending_delete:
            self.pending_delete = left
            self._save()


class ProfileHub:
    """Owns one browser context (Browser) per open profile and routes app-level requests to the right one."""

    def __init__(self, app, root_store: Store, browser_factory):
        self.app, self.root_store = app, root_store
        self.profiles = Profiles(root_store.root)
        self.profiles.purge_pending()
        self._factory = browser_factory
        self.contexts: dict = {}

    def context(self, pid: str):
        ctx = self.contexts.get(pid)
        if ctx is None:
            store = self.root_store if pid == DEFAULT_ID else Store(self.profiles.folder(pid), shared=self.root_store)
            ctx = self._factory(self.app, store, hub=self, pid=pid)
            self.contexts[pid] = ctx
        return ctx

    def info(self, pid: str) -> dict:
        return self.profiles.get(pid) or {"id": pid, "name": "Profile", "color": COLORS[0]}

    def many(self) -> bool:
        return len(self.profiles.items) > 1

    def open_profile(self, pid: str, urls: list[str] | None = None):
        """Bring up a window for the profile: its existing window, or a new one restoring its last tabs."""
        if self.profiles.get(pid) is None:
            return None
        ctx = self.context(pid)
        self.profiles.set_last(pid)
        win = next((w for w in ctx.windows if not w.private), None)
        if win is not None and not urls:
            win.showNormal() if win.isMinimized() else None
            win.raise_()
            win.activateWindow()
            return win
        session = [u for u in (ctx.store.get("session") or []) if isinstance(u, str)]
        start = urls or session or [None]
        win = ctx.new_window(urls=start)
        if not urls and session and hasattr(win, "strip"):
            win.strip.restore_layout(ctx.store.get("session_layout"))   # pinned tabs and tab groups
            if getattr(ctx, "crashed", False):
                win.notify("Pelagic didn't close properly last time, so your tabs have been brought back.")
                ctx.crashed = False
        return win

    def active(self):
        w = QApplication.activeWindow()
        ctx = getattr(w, "ctx", None)
        if ctx is not None and ctx in self.contexts.values():
            return ctx
        return self.context(self.profiles.last)

    def open_urls(self, urls: list[str]):
        self.active().open_urls(urls)

    def window_activated(self, ctx):
        self.profiles.set_last(ctx.pid)

    def delete_profile(self, pid: str):
        ctx = self.contexts.get(pid)
        others = [w for c in self.contexts.values() if c is not ctx for w in c.windows]
        if not others:
            self.open_profile(DEFAULT_ID)   # keep the app running while the profile's windows close
        if ctx is not None:
            for w in list(ctx.windows):
                w.close()
            ctx.watches.stop_all()
        self.profiles.remove(pid)

    def stop_all(self):
        for ctx in self.contexts.values():
            ctx.watches.stop_all()
