"""A persistent memory file that requires explicit authorization for every access.

Creating a MemoryFile does not inspect, read, or create its path. Callers must pass
``authorized=True`` only in response to a user request or a dedicated memory button.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path


HEADER = ("# Pelagic Memory\n\n"
          "Pelagic reads or updates this file only when you explicitly request it.\n\n")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_LOCK = threading.Lock()


class MemoryFile:
    """UTF-8 Markdown storage with an explicit, per-call access capability."""

    def __init__(self, path: str | os.PathLike, max_chars: int = 100_000):
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < len(HEADER):
            raise ValueError(f"Memory limit must be at least {len(HEADER)} characters.")
        self.path = Path(path)
        self.max_chars = max_chars
        # abspath normalizes the name without following links or touching the file.
        lock_key = os.path.normcase(os.path.abspath(os.fspath(self.path)))
        with _LOCKS_LOCK:
            self._lock = _LOCKS.setdefault(lock_key, threading.RLock())

    @staticmethod
    def _authorize(authorized: bool) -> None:
        if authorized is not True:
            raise PermissionError("Persistent memory requires your explicit permission for this access.")

    def _existing_text(self) -> str:
        """Only call after authorization; bounded read preserves original newlines."""
        try:
            with self.path.open("rb") as source:
                raw = source.read(self.max_chars * 4 + 1)
        except FileNotFoundError:
            return ""
        if len(raw) > self.max_chars * 4:
            raise ValueError(f"Memory exceeds the {self.max_chars:,}-character limit; shorten it before using it.")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Memory is not valid UTF-8 text. Save it as UTF-8 before using it.") from None
        if len(text) > self.max_chars:
            raise ValueError(f"Memory exceeds the {self.max_chars:,}-character limit; shorten it before using it.")
        return text

    def read(self, authorized: bool = False) -> str:
        """Read after explicit permission; a missing file returns an empty string."""
        self._authorize(authorized)
        with self._lock:
            return self._existing_text()

    def initialize(self, authorized: bool = False) -> bool:
        """Create an empty memory document if absent, without reading existing content."""
        self._authorize(authorized)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.path.open("x", encoding="utf-8", newline="") as target:
                    target.write(HEADER)
            except FileExistsError:
                return False
            return True

    def append(self, text: str, authorized: bool = False) -> None:
        """Save an explicitly approved entry atomically, retaining all prior content."""
        self._authorize(authorized)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("There is no text to save to memory.")
        if len(text) > self.max_chars:
            raise ValueError(f"The memory entry exceeds the {self.max_chars:,}-character limit.")
        with self._lock:
            prior = self._existing_text() or HEADER
            separator = "" if prior.endswith("\n\n") else "\n" if prior.endswith("\n") else "\n\n"
            updated = prior + separator + text.strip() + "\n\n"
            if len(updated) > self.max_chars:
                raise ValueError(f"Saving this entry would exceed the {self.max_chars:,}-character memory limit. "
                                 "Shorten the entry or edit the memory file first.")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode="wb", prefix=".atlas_memory_", suffix=".tmp",
                                                 dir=self.path.parent, delete=False) as target:
                    temp_path = Path(target.name)
                    target.write(updated.encode("utf-8"))
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temp_path, self.path)
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink()
                    except FileNotFoundError:
                        pass
