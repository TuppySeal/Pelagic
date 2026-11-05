"""Sync between computers through a folder that OneDrive, Google Drive, Dropbox (or a USB stick) keeps in step.

Pelagic has no sync server, so each computer writes its own file into "<folder>/Pelagic Sync/<profile>/" and reads
the others' files. Nothing ever goes to Pelagic or to the AI; the cloud drive only sees the files.

What syncs: bookmarks and folders, the reading list and history (last 90 days). Passwords, addresses and cards
sync only when a sync passphrase is set, and then only encrypted with it (scrypt + HMAC-SHA256, encrypt-then-MAC):
the passphrase itself is never written to the folder. Each item carries the time it last changed and deletions are
remembered, so the newest change wins everywhere.

Settings: "sync_folder" ('' = off), "sync_device" (this computer's id), "sync_last" (time), "sync_secrets" (on/off).
Local state (what was last synced) is in <profile>/sync_state.json; the vault key is with the API keys (DPAPI).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path

HISTORY_DAYS = 90
TOMBSTONE_DAYS = 120
INTERVAL_MS = 5 * 60 * 1000
SECRET = ("logins", "addresses", "cards")
_MAGIC = b"PS1"


# ---------------------------------------------------------------- encryption (standard library only)
def derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=64,
                          maxmem=64 * 1024 * 1024)


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    blocks = (n + 31) // 32
    return b"".join(hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest() for i in range(blocks))[:n]


def seal(data: bytes, key: bytes) -> str:
    nonce = os.urandom(16)
    ks = _stream(key[:32], nonce, len(data))
    ct = (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(data), "big") if data else b""
    tag = hmac.new(key[32:], _MAGIC + nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(_MAGIC + nonce + tag + ct).decode("ascii")


def unseal(blob: str, key: bytes) -> bytes:
    raw = base64.b64decode(blob)
    if raw[:3] != _MAGIC or len(raw) < 51:
        raise ValueError("not a Pelagic vault")
    nonce, tag, ct = raw[3:19], raw[19:51], raw[51:]
    if not hmac.compare_digest(tag, hmac.new(key[32:], _MAGIC + nonce + ct, hashlib.sha256).digest()):
        raise ValueError("wrong sync passphrase")
    ks = _stream(key[:32], nonce, len(ct))
    return (int.from_bytes(ct, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(ct), "big") if ct else b""


def _digest(rec) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------- what syncs
class Collections:
    """Reads and applies each synced collection as {key: record}."""

    def __init__(self, store, passwords=None, autofill=None):
        self.store, self.passwords, self.autofill = store, passwords, autofill

    def names(self, secrets: bool) -> list[str]:
        out = ["bookmarks", "folders", "reading", "history"]
        if secrets:
            out += [n for n in SECRET if (self.passwords if n == "logins" else self.autofill) is not None]
        return out

    def items(self, name: str) -> dict:
        s = self.store
        if name == "bookmarks":
            return {b["url"]: {"title": b.get("title", ""), "folder": b.get("folder", "")} for b in s.bookmarks}
        if name == "folders":
            return {f: {} for f in s.all_folders()}
        if name == "reading":
            return {e["url"]: {"title": e.get("title", ""), "added": e.get("added", 0), "read": bool(e.get("read"))}
                    for e in s.reading_list()}
        if name == "history":
            since = time.time() - HISTORY_DAYS * 86400
            with s._lock:
                rows = s._db.execute("SELECT url,title,visits,last FROM history WHERE last >= ?", (since,)).fetchall()
            return {u: {"title": t, "visits": v, "last": round(last, 3)} for u, t, v, last in rows}
        if name == "logins":
            return {f"{x['origin']}\0{x['username']}": {"origin": x["origin"], "username": x["username"],
                                                       "password": x["password"], "note": x.get("note", "")}
                    for x in self.passwords.logins()}
        if name == "addresses":
            from .autofill import ADDRESS_FIELDS
            return {x["id"]: {k: x.get(k, "") for k in ADDRESS_FIELDS} for x in self.autofill.items("addresses")}
        if name == "cards":
            from .autofill import CARD_FIELDS
            return {x["cc_number"]: {k: x.get(k, "") for k in CARD_FIELDS} for x in self.autofill.items("cards")}
        raise KeyError(name)

    def stamp(self, name: str, rec: dict) -> float | None:
        """A record's own change time when it has one (history: its last visit)."""
        return rec.get("last") if name == "history" else None

    def gone(self, name: str, key: str) -> bool:
        """Is a key that dropped out of items() really deleted (not just older than the history window)?"""
        if name != "history":
            return True
        with self.store._lock:
            return self.store._db.execute("SELECT 1 FROM history WHERE url=?", (key,)).fetchone() is None

    def apply(self, name: str, upserts: dict, removes: list):
        s = self.store
        if name == "bookmarks":
            for url in removes:
                s.remove_bookmark(url)
            for url, r in upserts.items():
                if s.is_bookmarked(url):
                    s.edit_bookmark(url, title=r.get("title"), folder=r.get("folder", ""))
                else:
                    s.add_bookmark(url, r.get("title") or url, r.get("folder", ""))
        elif name == "folders":
            for f in upserts:
                s.add_folder(f)
            for f in removes:
                s.delete_folder(f, keep_bookmarks=True)
        elif name == "reading":
            items = {e["url"]: e for e in s.reading_list()}
            for url in removes:
                items.pop(url, None)
            for url, r in upserts.items():
                items[url] = {"url": url, "title": r.get("title") or url, "added": r.get("added", 0),
                              "read": bool(r.get("read"))}
            s.set("reading_list", sorted(items.values(), key=lambda e: -float(e.get("added") or 0)))
        elif name == "history":
            with s._lock:
                s._db.executemany("DELETE FROM history WHERE url=?", [(u,) for u in removes])
                s._db.executemany(
                    "INSERT INTO history(url,title,visits,last) VALUES(?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
                    "title=excluded.title, visits=max(visits, excluded.visits), last=max(last, excluded.last)",
                    [(u, r.get("title") or u, int(r.get("visits") or 1), float(r.get("last") or 0))
                     for u, r in upserts.items()])
                s._db.commit()
        elif name == "logins":
            ps = self.passwords
            with ps._lock:
                data = ps._load()
                by_key = {f"{x['origin']}\0{x['username']}": x for x in data["logins"]}
                for key in removes:
                    if key in by_key:
                        data["logins"].remove(by_key.pop(key))
                for key, r in upserts.items():
                    x = by_key.get(key)
                    if x is None:
                        x = {"id": uuid.uuid4().hex, "created": time.time(), "last_used": 0}
                        data["logins"].append(x)
                    x.update({k: r.get(k, "") for k in ("origin", "username", "password", "note")})
                    x["updated"] = time.time()
                ps._save()
        elif name == "addresses":
            for key in removes:
                self.autofill.delete("addresses", key)
            for key, r in upserts.items():
                self.autofill.save("addresses", r, key)
        elif name == "cards":
            by_number = {x["cc_number"]: x["id"] for x in self.autofill.items("cards")}
            for key in removes:
                if key in by_number:
                    self.autofill.delete("cards", by_number[key])
            for key, r in upserts.items():
                self.autofill.save("cards", r, by_number.get(key))


# ---------------------------------------------------------------- the sync itself
class FolderSync:
    def __init__(self, store, pid: str, collections: Collections):
        self.store, self.pid, self.c = store, pid, collections
        self._lock = threading.Lock()
        self.last_report = ""

    # -- places
    def folder(self) -> Path | None:
        f = self.store.get("sync_folder") or ""
        return Path(f) / "Pelagic Sync" / self.pid if f else None

    def device_id(self) -> str:
        d = self.store.get("sync_device")
        if not d:
            d = uuid.uuid4().hex[:12]
            self.store.set("sync_device", d)
        return d

    def _state_path(self) -> Path:
        return self.store.root / "sync_state.json"

    def _key_name(self) -> str:
        return f"sync-vault-{self.pid}"

    # -- passphrase
    def vault_key(self) -> bytes | None:
        k = self.store.get_key(self._key_name())
        return bytes.fromhex(k) if k else None

    def set_passphrase(self, passphrase: str) -> str:
        """Checks the passphrase against the folder's (or sets it for a new folder). Returns '' or the problem."""
        folder = self.folder()
        if folder is None:
            return "Choose a sync folder first."
        folder.mkdir(parents=True, exist_ok=True)
        salt_file, check_file = folder / "vault-salt", folder / "vault-check"
        if not salt_file.exists():
            salt_file.write_text(base64.b64encode(os.urandom(16)).decode("ascii"))
        key = derive_key(passphrase, base64.b64decode(salt_file.read_text()))
        if check_file.exists():
            try:
                if unseal(check_file.read_text(), key) != b"pelagic-sync":
                    raise ValueError
            except ValueError:
                return "That isn't the sync passphrase used on your other computer."
        else:
            check_file.write_text(seal(b"pelagic-sync", key))
        self.store.set_key(self._key_name(), key.hex())
        return ""

    def forget_passphrase(self):
        self.store.set_key(self._key_name(), "")

    # -- run
    def run(self) -> str:
        """One sync round (any thread). Returns a short report."""
        folder = self.folder()
        if folder is None:
            return "Sync is off."
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            me = self.device_id()
            key = self.vault_key() if self.store.get("sync_secrets") else None
            names = self.c.names(secrets=key is not None)
            try:
                state = json.loads(self._state_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = {}
            others, devices, problems = [], [], []
            for f in sorted(folder.glob("*.json")):
                if f.stem == me:
                    continue
                try:
                    doc = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue      # half-synced by the cloud drive: next round
                devices.append(doc.get("name") or f.stem)
                data = dict(doc.get("open") or {})
                if key is not None and doc.get("vault"):
                    try:
                        data.update(json.loads(unseal(doc["vault"], key)))
                    except ValueError as e:
                        problems.append(f"{doc.get('name') or f.stem}: {e}")
                others.append(data)
            now = time.time()
            merged_all, changed = {}, 0
            for name in names:
                local = self.c.items(name)
                prev = state.get(name, {})
                merged = {}
                for k, rec in local.items():
                    d = _digest(rec)
                    p = prev.get(k)
                    t = self.c.stamp(name, rec) or (p[1] if p and p[0] == d else now)
                    merged[k] = {"t": t, "r": rec}
                for k, p in prev.items():
                    if k not in merged and (p[0] is None or self.c.gone(name, k)):
                        merged[k] = {"t": p[1] if p[0] is None else now, "r": None}   # deleted here
                    elif k not in merged:
                        merged[k] = {"t": p[1], "r": "keep"}                           # just aged out locally
                for data in others:
                    for k, e in (data.get(name) or {}).items():
                        if isinstance(e, dict) and (k not in merged or float(e.get("t", 0)) > merged[k]["t"]):
                            merged[k] = {"t": float(e.get("t", 0)), "r": e.get("r")}
                upserts = {k: e["r"] for k, e in merged.items()
                           if isinstance(e["r"], dict) and local.get(k) != e["r"]}
                # (history outside the 90-day window isn't in `local` but is still deleted)
                removes = [k for k, e in merged.items() if e["r"] is None and (k in local or name == "history")]
                if upserts or removes:
                    self.c.apply(name, upserts, removes)
                    changed += len(upserts) + len([k for k in removes if k in local])
                cutoff = now - TOMBSTONE_DAYS * 86400
                merged = {k: e for k, e in merged.items() if e["r"] != "keep" and (e["r"] is not None or e["t"] > cutoff)}
                merged_all[name] = merged
                state[name] = {k: [None if e["r"] is None else _digest(e["r"]), e["t"]] for k, e in merged.items()}
            doc = {"name": socket.gethostname(), "device": me, "time": now, "version": 1,
                   "open": {n: merged_all[n] for n in names if n not in SECRET}}
            if key is not None:
                doc["vault"] = seal(json.dumps({n: merged_all[n] for n in names if n in SECRET}).encode("utf-8"), key)
            tmp = folder / f"{me}.json.tmp"
            tmp.write_text(json.dumps(doc), encoding="utf-8")
            os.replace(tmp, folder / f"{me}.json")
            tmp = self._state_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, self._state_path())
            self.store.set("sync_last", now)
            report = (f"Synced with {len(devices)} other computer" + ("s" if len(devices) != 1 else "")
                      + (f" ({', '.join(devices)})" if devices else "") + f": {changed} change"
                      + ("s" if changed != 1 else "") + " brought in.")
            if problems:
                report += " Passwords couldn't be read from " + "; ".join(problems) + "."
            self.last_report = report
            return report
