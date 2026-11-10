"""Extensions toolbar button, install prompt for .user.js pages, and the Extensions page."""
from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QToolButton, QVBoxLayout)

from . import darkmode, icons
from .agent import run_in_pool
from .extensions import GREASY_FORK, header_for, is_userscript_url, menu_commands_js, parse_meta, \
    run_menu_command_js, site_patterns


def puzzle_icon() -> QIcon:
    return QIcon(str(Path(__file__).parent / "assets" / "extensions.svg"))


def _base_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class ExtensionsButton(QToolButton):
    """Toolbar button: ad-blocker status for this site, extension on/off, script menu commands, manage."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._icon = puzzle_icon()
        self.setIcon(self._icon)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(34, 32)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)   # the blocked count shows as a badge on the icon
        self.setToolTip("Extensions and ad blocker")
        self.setPopupMode(QToolButton.InstantPopup)
        self.setStyleSheet("QToolButton::menu-indicator{image:none}")
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._fill)
        self.setMenu(self.menu_)
        self._commands: list = []

    def refresh(self):
        t = self.win.current_tab()
        host = t.url().host() if t else ""
        n = self.win.ctx.blocker.counts.get(host, 0) if host else 0
        if self.text() != (str(n) if n else ""):
            self.setText(str(n) if n else "")
            self.setIcon(icons.with_badge(self._icon, n))
        self.setToolTip(f"Extensions and ad blocker — {n} blocked on this page" if n else "Extensions and ad blocker")

    def _fill(self):
        m, ctx, win = self.menu_, self.win.ctx, self.win
        m.clear()
        tab = win.current_tab()
        host = tab.url().host() if tab and tab.url().scheme() in ("http", "https") else ""
        blocker = ctx.blocker
        if not blocker.enabled():
            a = m.addAction("Ad blocker is off (turn on in Extensions)")
            a.setEnabled(False)
        elif host:
            n = blocker.counts.get(host, 0)
            on = not blocker.paused_on(host)
            a = m.addAction(f"Block ads on {host}" + (f"  ({n} blocked)" if on and n else ""))
            a.setCheckable(True)
            a.setChecked(on)
            a.toggled.connect(lambda checked, h=host: self._toggle_site(h, checked))
        if win.private:
            m.addSeparator()
            a = m.addAction("Extensions don't run in private windows")
            a.setEnabled(False)
        exts = ctx.extensions.items
        if exts and not win.private:
            m.addSeparator()
            for e in exts:
                a = m.addAction(e["name"])
                a.setCheckable(True)
                a.setChecked(e.get("enabled", True))
                a.toggled.connect(lambda checked, eid=e["id"]: self._toggle_ext(eid, checked))
            if darkmode.NATIVE and host and darkmode.enabled(ctx.extensions):
                a = m.addAction(f"Dark mode on {host}")
                a.setCheckable(True)
                a.setChecked(not darkmode.site_off(win.store, host))
                a.toggled.connect(lambda checked, h=host: self._toggle_dark(h, checked))
            self._commands_section(m, tab)
        m.addSeparator()
        domains = getattr(ctx, "domains", None)
        if host and domains is not None:
            m.addAction(f"Block {_base_domain(host)} everywhere…").triggered.connect(
                lambda _=False, h=_base_domain(host): self._block_domain(h))
        if domains is not None:
            m.addAction("Blocked domains…").triggered.connect(self._edit_blocklist)
        if host:
            m.addAction(f"Find scripts for {_base_domain(host)}…").triggered.connect(
                lambda: win.open_tab(f"https://greasyfork.org/en/scripts/by-site/{_base_domain(host)}"))
        m.addAction("Extension gallery…").triggered.connect(lambda: _gallery(win))
        m.addAction("Manage extensions…").triggered.connect(lambda: ExtensionsDialog(win).exec())

    def _commands_section(self, m, tab):
        if tab is None:
            return
        anchor = m.addSeparator()
        names = {e["id"]: e["name"] for e in self.win.ctx.extensions.items}

        def got(result):
            try:
                cmds = json.loads(result or "[]")
            except ValueError:
                return
            if not m.isVisible():
                return
            for ext_id, idx, caption in cmds:
                a = QAction(f"{names.get(ext_id, 'Script')}: {caption}", m)
                m.insertAction(anchor, a)
                a.triggered.connect(lambda _=False, e=ext_id, i=idx: tab.page().runJavaScript(run_menu_command_js(e, i)))
        tab.page().runJavaScript(menu_commands_js(), got)

    def _toggle_site(self, host, on):
        self.win.ctx.blocker.set_paused(host, not on)
        self.win.ctx.blocker.reset(host)
        self.win._cur(lambda t: t.reload())

    def _block_domain(self, domain):
        if QMessageBox.question(self.win, "Block domain", f"Block {domain} and all its subdomains? Pages from it won't "
                                "open, and other sites can't load anything from it.") != QMessageBox.Yes:
            return
        if self.win.ctx.domains.add(domain):
            self.win._cur(lambda t: t.reload())

    def _edit_blocklist(self):
        from .network_ui import BlocklistDialog
        BlocklistDialog(self.win.store, self.win.ctx.domains, self.win).exec()

    def _toggle_dark(self, host, on):
        darkmode.set_site_off(self.win.store, host, not on)
        for w in getattr(self.win.ctx, "windows", None) or [self.win]:
            darkmode.refresh_tabs(w.tab_list(), w.store)

    def _toggle_ext(self, ext_id, on):
        exts = self.win.ctx.extensions
        dark = darkmode.NATIVE and (exts.get(ext_id) or {}).get("source") == darkmode.SOURCE
        exts.set_enabled(ext_id, on)
        if not dark:   # dark mode reloads the pages it changes by itself (darkmode.apply_profile)
            self.win._cur(lambda t: t.reload())


def _gallery(win):
    from .extensions_gallery import GalleryDialog   # imported here: it loads the bundled scripts' metadata
    GalleryDialog(win).exec()


# ------------------------------------------------------------------ install prompt
def offer_install(win, url: QUrl):
    """Called when a tab finishes loading a .user.js address (Greasy Fork's Install button)."""
    if win.private or not is_userscript_url(url):
        return
    tab = win.current_tab()
    if tab is not None and getattr(tab, "_wf_offered", None) == url.toString():
        return   # loadFinished can repeat for the same address
    if tab is not None:
        tab._wf_offered = url.toString()
    exts = win.ctx.extensions
    src = url.toString()

    def done(_t, out):
        if isinstance(out, Exception):
            QMessageBox.warning(win, "Install script", f"Couldn't download the script: {out}")
            return
        code, reqs = out
        confirm_install(win, code, reqs, src)
    run_in_pool(0, lambda: exts.fetch_with_requires(src), done)


def confirm_install(win, code: str, reqs: dict, source: str) -> dict | None:
    meta = parse_meta(code)
    exts = win.ctx.extensions
    existing = next((e for e in exts.items if e.get("source") == source), None)
    sites = meta["match"] + meta["include"] or ["every site"]
    shown = ", ".join(html.escape(s) for s in sites[:6]) + (" …" if len(sites) > 6 else "")
    box = QMessageBox(win)
    box.setWindowTitle("Update script" if existing else "Install script")
    box.setTextFormat(Qt.RichText)
    box.setText(f"<b>{html.escape(meta.get('name', 'Untitled'))}</b> {html.escape(meta.get('version', ''))}<br>"
                f"{html.escape(meta.get('description', ''))}")
    box.setInformativeText(
        f"Runs on: {shown}<br><br>Scripts can read and change the pages they run on. Only install scripts you "
        f"trust. It will be added to the <b>{html.escape(win.ctx.hub.info(win.ctx.pid)['name']) if win.ctx.hub else 'current'}</b> profile.")
    install = box.addButton("Update" if existing else "Install", QMessageBox.AcceptRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    if box.clickedButton() is not install:
        return None
    ext = exts.install(code, source_url=source, requires=reqs)
    QMessageBox.information(win, "Installed", f"{ext['name']} is installed. It runs the next time you open or "
                                              "reload a page it works on.")
    return ext


# ------------------------------------------------------------------ editor and manager
class ScriptEditor(QDialog):
    """Create or edit your own site script or style."""

    def __init__(self, parent, ext: dict | None = None, code: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Edit extension" if ext else "New site script or style")
        self.resize(720, 560)
        meta = parse_meta(code) if code else {"match": [], "include": []}
        self.kind = QComboBox()
        self.kind.addItem("Style (CSS)", "style")
        self.kind.addItem("Script (JavaScript)", "script")
        self.name = QLineEdit(ext["name"] if ext else "")
        self.name.setPlaceholderText("e.g. Hide YouTube Shorts")
        shown = []
        for pat in meta["match"] + meta["include"]:
            plain = pat.replace("*://*.", "").replace("*://", "").rstrip("/*")
            if plain not in shown:
                shown.append(plain)
        self.sites = QLineEdit(", ".join(shown))
        self.sites.setPlaceholderText("youtube.com, reddit.com   (leave empty for every site)")
        body = code
        is_style = False
        if ext and ext.get("kind") == "style":
            is_style = True
            m = code.find("GM_addStyle(")
            if m >= 0:
                body = json.loads(code[m + len("GM_addStyle("):code.rfind(");")])
        elif code:
            body = code[code.find("==/UserScript==") + len("==/UserScript=="):].lstrip("\n") if "==/UserScript==" in code else code
        self.kind.setCurrentIndex(0 if (is_style or not ext) else 1)
        self.editor = QPlainTextEdit(body)
        self.editor.setPlaceholderText("/* CSS for a style, e.g. */\n#related, .ad-banner { display: none !important; }")
        self.editor.setStyleSheet("font-family: Consolas, monospace;")
        f = QFormLayout()
        f.addRow("Type", self.kind)
        f.addRow("Name", self.name)
        f.addRow("Sites", self.sites)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(self.editor, 1)
        lay.addWidget(buttons)

    def _ok(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name", "Give it a name.")
            return
        self.accept()

    def result_code(self) -> tuple[str, str]:
        sites = [p for s in self.sites.text().split(",") if s.strip() for p in site_patterns(s)]
        kind = self.kind.currentData()
        text = self.editor.toPlainText()
        if kind == "style":
            return header_for(self.name.text().strip(), sites, "document-start") + \
                f"GM_addStyle({json.dumps(text)});\n", "style"
        return header_for(self.name.text().strip(), sites, "document-end") + text + "\n", "custom"


class ExtensionsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.exts, self.store = win, win.ctx.extensions, win.store
        self.setWindowTitle("Extensions")
        self.resize(760, 560)
        blocker = win.ctx.blocker

        self.adblock = QCheckBox("Block ads and trackers (EasyList and EasyPrivacy)")
        self.adblock.setChecked(blocker.enabled())
        self.adblock.toggled.connect(lambda on: self.store.set("adblock", bool(on)))
        lists = blocker.lists
        engine = lists.engine
        status = QLabel(f"{engine.rules:,} filter rules loaded." if engine else "Filter lists are loading…")
        status.setObjectName("muted")
        paused = QLabel("Paused on: " + (", ".join(self.store.get("adblock_allow") or []) or "no sites"))
        paused.setObjectName("muted")
        paused.setWordWrap(True)
        upd = QPushButton("Update filter lists")
        upd.clicked.connect(lambda: (lists.load(force_download=True), status.setText("Updating filter lists…")))
        clear = QPushButton("Resume on all sites")
        clear.clicked.connect(lambda: (self.store.set("adblock_allow", []), paused.setText("Paused on: no sites")))
        ar = QHBoxLayout()
        ar.addWidget(status, 1)
        ar.addWidget(clear)
        ar.addWidget(upd)

        head = QLabel("<b>Scripts and styles</b> for this profile. Install userscripts from Greasy Fork or "
                      "OpenUserJS (click their Install button in Pelagic), or make your own for any site.")
        head.setWordWrap(True)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._toggled)
        self.list.itemDoubleClicked.connect(lambda _it: self._edit())
        row = QHBoxLayout()
        for text, slot in (("Gallery…", lambda: (_gallery(win), self.reload())),
                           ("Get scripts…", lambda: (win.open_tab(GREASY_FORK), self.accept())),
                           ("New style or script…", self._new), ("Edit…", self._edit),
                           ("Check for updates", self._updates), ("Remove", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.adblock)
        lay.addLayout(ar)
        lay.addWidget(paused)
        lay.addSpacing(10)
        lay.addWidget(head)
        lay.addWidget(self.list, 1)
        lay.addLayout(row)
        if win.private:
            note = QLabel("Scripts don't run in private windows; the ad blocker does.")
            note.setObjectName("muted")
            lay.addWidget(note)
        lay.addWidget(close)
        self.reload()

    def reload(self):
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.exts.items:
            sites = ", ".join(e.get("sites") or []) or "every site"
            kind = {"style": "Style", "custom": "Script"}.get(e.get("kind"), "Userscript")
            it = QListWidgetItem(f"{e['name']}  {e.get('version', '')}\n{kind} · {sites[:90]}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if e.get("enabled", True) else Qt.Unchecked)
            it.setData(Qt.UserRole, e["id"])
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _sel(self) -> dict | None:
        it = self.list.currentItem()
        return self.exts.get(it.data(Qt.UserRole)) if it else None

    def _toggled(self, it):
        self.exts.set_enabled(it.data(Qt.UserRole), it.checkState() == Qt.Checked)

    def _new(self):
        d = ScriptEditor(self)
        if d.exec():
            code, kind = d.result_code()
            self.exts.install(code, kind=kind)
            self.reload()

    def _edit(self):
        e = self._sel()
        if not e:
            return
        d = ScriptEditor(self, e, self.exts.code(e))
        if d.exec():
            code, kind = d.result_code()
            if e.get("kind") not in ("style", "custom"):
                kind = e.get("kind", "userscript")
                code = self.exts.code(e).split("==/UserScript==")[0] + "==/UserScript==\n" + d.editor.toPlainText()
            self.exts.install(code, source_url=e.get("source", ""), kind=kind, ext_id=e["id"])
            self.reload()

    def _remove(self):
        e = self._sel()
        if e and QMessageBox.question(self, "Remove", f"Remove {e['name']}?") == QMessageBox.Yes:
            self.exts.remove(e["id"])
            self.reload()

    def _updates(self):
        targets = [e for e in self.exts.items if e.get("source")]
        if not targets:
            QMessageBox.information(self, "Updates", "None of your scripts were installed from a website. "
                                    "Pelagic's own extensions update from the Gallery.")
            return

        def work():
            found = []
            for e in targets:
                try:
                    new = self.exts.check_update(e)
                except Exception:   # noqa: BLE001 - one broken script shouldn't stop the rest
                    new = None
                if new:
                    found.append((e, new))
            return found

        def done(_t, found):
            if isinstance(found, Exception) or not found:
                QMessageBox.information(self, "Updates", "Everything is up to date.")
                return
            for e, (code, reqs) in found:
                self.exts.install(code, source_url=e["source"], requires=reqs, ext_id=e["id"])
            self.reload()
            QMessageBox.information(self, "Updates", "Updated: " + ", ".join(e["name"] for e, _ in found))
        run_in_pool(0, work, done)
