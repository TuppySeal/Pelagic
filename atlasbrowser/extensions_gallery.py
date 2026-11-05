"""Extension gallery: Pelagic's own extensions, bundled in assets/gallery, installed or removed with one click.

Each one is an ordinary userscript, installed into the profile's Extensions with the source 'pelagic-gallery:<file>',
so it shows up, switches off and can be edited like any other script. A newer bundled version offers an Update.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .extensions import _version_tuple, parse_meta

GALLERY_DIR = Path(__file__).parent / "assets" / "gallery"
SOURCE = "pelagic-gallery:"

# Shown order, with an icon and the one line that tells you how to use it. Files not listed here still appear, last.
CATALOG = [
    ("youtube-enhancer.user.js", "▶", "Options are in the puzzle menu while you're on YouTube."),
    ("focus-blocker.user.js", "◎", "Edit the blocked sites and study hours with Manage extensions… → Edit."),
    ("cookie-banner-skipper.user.js", "✕", "Works by itself. Pause it for a site from the puzzle menu."),
    ("highlighter-notes.user.js", "✎", "Select text to highlight it. Alt+N opens your notes."),
    ("word-count.user.js", "¶", "Select text or type in a box to count it. Alt+W hides it."),
    ("cite-this-page.user.js", "❝", "Press Alt+C on any page."),
    ("video-speed.user.js", "»", "D faster, S slower, R back to 1×, Z and X skip 10 seconds."),
    ("auto-scroll.user.js", "↓", "Alt+S starts and stops. Arrow keys change the speed."),
    ("password-strength.user.js", "✱", "Appears when you make a new password."),
]


def _sites(meta: dict) -> str:
    shown = []
    for pat in meta["match"] + meta["include"]:
        plain = pat.replace("*://*.", "").replace("*://", "").rstrip("/*")
        if plain in ("", "*") or plain.startswith("*"):
            return "Every site"
        if plain not in shown:
            shown.append(plain)
    return ", ".join(shown) or "Every site"


def entries() -> list[dict]:
    """The bundled extensions: file, icon, tip, code and its metadata."""
    known = {f: (icon, tip) for f, icon, tip in CATALOG}
    files = [f for f, _i, _t in CATALOG if (GALLERY_DIR / f).exists()]
    files += sorted(p.name for p in GALLERY_DIR.glob("*.user.js") if p.name not in known)
    out = []
    for f in files:
        code = (GALLERY_DIR / f).read_text(encoding="utf-8")
        meta = parse_meta(code)
        icon, tip = known.get(f, ("✦", ""))
        out.append({"file": f, "icon": icon, "tip": tip, "code": code, "name": meta.get("name") or f,
                    "description": meta.get("description", ""), "version": meta.get("version", ""),
                    "sites": _sites(meta)})
    return out


def installed(exts, entry: dict) -> dict | None:
    return next((e for e in exts.items if e.get("source") == SOURCE + entry["file"]), None)


def has_update(exts, entry: dict) -> bool:
    e = installed(exts, entry)
    return bool(e) and _version_tuple(entry["version"]) > _version_tuple(e.get("version", ""))


def install(exts, entry: dict) -> dict:
    e = installed(exts, entry)
    return exts.install(entry["code"], source_url=SOURCE + entry["file"], kind="userscript",
                        ext_id=e["id"] if e else None)


def uninstall(exts, entry: dict):
    e = installed(exts, entry)
    if e:
        exts.remove(e["id"])


class _Card(QFrame):
    def __init__(self, dialog, entry: dict):
        super().__init__()
        self.dialog, self.entry = dialog, entry
        self.setObjectName("galleryCard")
        icon = QLabel(entry["icon"])
        icon.setObjectName("galleryIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(44, 44)
        name = QLabel(f"<b>{entry['name']}</b>")
        desc = QLabel(entry["description"])
        desc.setWordWrap(True)
        more = QLabel(" · ".join(x for x in (entry["sites"], entry["tip"]) if x))
        more.setObjectName("muted")
        more.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(name)
        text.addWidget(desc)
        text.addWidget(more)
        self.button = QPushButton()
        self.button.setMinimumWidth(96)
        self.button.clicked.connect(self._clicked)
        self.remove = QPushButton("Remove")
        self.remove.setFlat(True)
        self.remove.clicked.connect(self._remove)
        side = QVBoxLayout()
        side.addWidget(self.button)
        side.addWidget(self.remove)
        side.addStretch(1)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        row.addWidget(icon, 0, Qt.AlignTop)
        row.addLayout(text, 1)
        row.addLayout(side)
        self.refresh()

    def refresh(self):
        exts = self.dialog.exts
        e = installed(exts, self.entry)
        if e is None:
            self.button.setText("Install")
            self.button.setEnabled(True)
            self.button.setDefault(False)
            self.button.setToolTip("")
            self.remove.hide()
        elif has_update(exts, self.entry):
            self.button.setText("Update")
            self.button.setEnabled(True)
            self.button.setToolTip(f"Version {self.entry['version']} is available. Replaces your copy, including any edits.")
            self.remove.show()
        else:
            self.button.setText("Installed ✓")
            self.button.setEnabled(False)
            self.button.setToolTip("")
            self.remove.show()

    def _clicked(self):
        install(self.dialog.exts, self.entry)
        self.dialog.changed()

    def _remove(self):
        uninstall(self.dialog.exts, self.entry)
        self.dialog.changed()


class GalleryDialog(QDialog):
    """Puzzle menu → Extension gallery…"""

    def __init__(self, win):
        super().__init__(win)
        self.win, self.exts = win, win.ctx.extensions
        self.setWindowTitle("Extension gallery")
        self.resize(680, 640)
        self.setStyleSheet("#galleryCard { border: 1px solid palette(mid); border-radius: 10px; }"
                           "#galleryIcon { font-size: 22px; border-radius: 10px; color: white;"
                           " background: #1f8f84; }")
        head = QLabel("<b>Pelagic extensions</b><br>Made for Pelagic. Install with one click, switch them off any "
                      "time from the puzzle menu.")
        head.setWordWrap(True)
        self.all = QPushButton("Install all")
        self.all.clicked.connect(self._install_all)
        top = QHBoxLayout()
        top.addWidget(head, 1)
        top.addWidget(self.all, 0, Qt.AlignTop)

        self.cards = [_Card(self, e) for e in entries()]
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(8)
        for c in self.cards:
            col.addWidget(c)
        if not self.cards:
            col.addWidget(QLabel("The gallery is empty: assets/gallery is missing from this copy of Pelagic."))
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)

        self.note = QLabel("")
        self.note.setObjectName("muted")
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.note, 1)
        bottom.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addSpacing(6)
        lay.addWidget(scroll, 1)
        lay.addLayout(bottom)
        if win.private:
            self.note.setText("Extensions don't run in private windows. What you install here works in normal windows.")
        self._dirty = False
        self._update_all()

    def _update_all(self):
        missing = [c for c in self.cards if installed(self.exts, c.entry) is None or has_update(self.exts, c.entry)]
        self.all.setEnabled(bool(missing))
        self.all.setText("Install all" if missing else "All installed")

    def _install_all(self):
        for c in self.cards:
            if installed(self.exts, c.entry) is None or has_update(self.exts, c.entry):
                install(self.exts, c.entry)
        self.changed()

    def changed(self):
        for c in self.cards:
            c.refresh()
        self._update_all()
        self._dirty = True
        if not self.win.private:
            self.note.setText("Changes apply to pages you open or reload. The current tab reloads when you close this.")

    def done(self, r):
        if self._dirty and not self.win.private:
            try:
                self.win._cur(lambda t: t.reload())
            except Exception:   # noqa: BLE001 - no tab to reload
                pass
        super().done(r)

