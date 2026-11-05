"""The Pelagic Playground: a hidden page of hands-on challenges for every feature (assets/playground.html).

Two ways in: type pelagic:playground in the address bar, or click the logo on the homepage five times quickly.
It's a local file, so it works offline, and the page keeps its own progress in local storage.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl

PAGE = Path(__file__).resolve().parent / "assets" / "playground.html"
ADDRESSES = ("pelagic:playground", "pelagic://playground", "atlas:playground")


def is_address(text: str) -> bool:
    return (text or "").strip().lower().rstrip("/") in ADDRESSES


def url() -> QUrl:
    return QUrl.fromLocalFile(str(PAGE))


def is_playground(url: QUrl) -> bool:
    return url.isLocalFile() and Path(url.toLocalFile()).name == PAGE.name
