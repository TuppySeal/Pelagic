"""Passwords page: search, show, copy, add, edit, delete, a checkup (leaked, reused, weak), never-saved sites, and
import from Google."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .passwords import display_site, origin_of

MASK = "••••••••"


class LoginDialog(QDialog):
    def __init__(self, parent, login: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit password" if login else "Add password")
        self.resize(460, 0)
        login = login or {}
        self.site = QLineEdit(login.get("origin", ""))
        self.site.setPlaceholderText("https://example.com")
        self.user = QLineEdit(login.get("username", ""))
        self.pw = QLineEdit(login.get("password", ""))
        self.pw.setEchoMode(QLineEdit.Password)
        show = QCheckBox("Show")
        show.toggled.connect(lambda on: self.pw.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        row = QHBoxLayout()
        row.addWidget(self.pw, 1)
        row.addWidget(show)
        self.note = QLineEdit(login.get("note", ""))
        f = QFormLayout()
        f.addRow("Site", self.site)
        f.addRow("Username", self.user)
        f.addRow("Password", row)
        f.addRow("Note", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(buttons)

    def _ok(self):
        if not origin_of(self.site.text()):
            QMessageBox.warning(self, "Site", "Enter a web address such as https://example.com.")
            return
        if not self.pw.text():
            QMessageBox.warning(self, "Password", "The password can't be empty.")
            return
        self.accept()

    def values(self) -> dict:
        return {"origin": origin_of(self.site.text()), "username": self.user.text(), "password": self.pw.text(),
                "note": self.note.text()}


class PasswordsDialog(QDialog):
    def __init__(self, manager, win):
        super().__init__(win)
        self.manager, self.store, self.win = manager, manager.store, win
        self.shown: set[str] = set()
        self.setWindowTitle("Passwords")
        self.resize(820, 540)

        self.offer = QCheckBox("Offer to save passwords")
        self.offer.setChecked(manager.enabled())
        self.offer.toggled.connect(lambda on: win.store.set("save_passwords", bool(on)))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search passwords")
        self.search.textChanged.connect(self.reload)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Site", "Username", "Password"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _i: self._edit())

        btns = QHBoxLayout()
        for text, slot in (("Show / hide", self._toggle_show), ("Copy password", self._copy),
                           ("Add…", self._add), ("Edit…", self._edit), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)

        saved = QWidget()
        sv = QVBoxLayout(saved)
        sv.addWidget(self.search)
        sv.addWidget(self.table, 1)
        sv.addLayout(btns)

        never = QWidget()
        nv = QVBoxLayout(never)
        nv.addWidget(QLabel("Pelagic never offers to save passwords on these sites."))
        self.never_list = QListWidget()
        nv.addWidget(self.never_list, 1)
        rm = QPushButton("Remove selected")
        rm.clicked.connect(self._remove_never)
        nr = QHBoxLayout()
        nr.addStretch(1)
        nr.addWidget(rm)
        nv.addLayout(nr)

        imp = QWidget()
        iv = QVBoxLayout(imp)
        info = QLabel(
            "<b>From Google</b>: opens Google Password Manager in a new tab. Sign in if asked, then click "
            "<b>Download file</b> under Export passwords. Pelagic imports the file straight away and deletes it, "
            "so it never stays on your computer. The AI is never involved.<br><br>"
            "<b>From a CSV file</b>: Chrome, Google, Edge and Firefox exports all work. Delete the CSV afterwards, "
            "because it is not encrypted.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        g = QPushButton("Import from Google…")
        g.setObjectName("primary")
        g.clicked.connect(self._import_google)
        c = QPushButton("Import CSV file…")
        c.clicked.connect(self._import_csv)
        ir = QHBoxLayout()
        ir.addWidget(g)
        ir.addWidget(c)
        ir.addStretch(1)
        iv.addWidget(info)
        iv.addLayout(ir)
        iv.addStretch(1)

        tabs = QTabWidget()
        tabs.addTab(saved, "Saved")
        tabs.addTab(self._checkup_tab(), "Checkup")
        tabs.addTab(never, "Never saved")
        tabs.addTab(imp, "Import")
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.offer)
        lay.addWidget(tabs, 1)
        lay.addWidget(close)
        self.reload()

    # -- checkup
    def _checkup_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        info = QLabel("Finds saved passwords that showed up in known data breaches, are used on more than one site, "
                      "or are easy to guess. To look up breaches, only the first 5 characters of each password's "
                      "scrambled fingerprint (SHA-1 hash) are sent to Have I Been Pwned, never the password itself.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        self.check_btn = QPushButton("Check passwords")
        self.check_btn.setObjectName("primary")
        self.check_btn.clicked.connect(self._run_checkup)
        self.check_status = QLabel("")
        top = QHBoxLayout()
        top.addWidget(self.check_btn)
        top.addWidget(self.check_status, 1)
        self.issues = QListWidget()
        self.issues.itemDoubleClicked.connect(lambda _i: self._fix_issue(edit=True))
        change = QPushButton("Change password on the site")
        change.setToolTip("Opens the site so you can change it there, then update it here with Edit…")
        change.clicked.connect(lambda: self._fix_issue(edit=False))
        edit = QPushButton("Edit…")
        edit.clicked.connect(lambda: self._fix_issue(edit=True))
        row = QHBoxLayout()
        row.addWidget(change)
        row.addWidget(edit)
        row.addStretch(1)
        v.addWidget(info)
        v.addLayout(top)
        v.addWidget(self.issues, 1)
        v.addLayout(row)
        return w

    def _run_checkup(self):
        from .agent import run_in_pool
        from .pwcheck import checkup
        logins = self.store.logins()
        if not logins:
            self.check_status.setText("No saved passwords to check.")
            return
        self.check_btn.setEnabled(False)
        self.check_status.setText(f"Checking {len(logins)} passwords…")
        self._checkup_job = run_in_pool(0, lambda: checkup(logins), lambda _t, out: self._show_checkup(out))

    def _show_checkup(self, out):
        try:
            self.check_btn.setEnabled(True)
        except RuntimeError:
            return   # the dialog was closed meanwhile
        if isinstance(out, Exception):
            self.check_status.setText(f"The check failed: {out}")
            return
        self.issues.clear()
        logins = {x["id"]: x for x in self.store.logins()}
        rank = lambda i: (-(i[1]["leaked"] > 0), -i[1]["reused"], -i[1]["weak"])
        for lid, iss in sorted(out["issues"].items(), key=rank):
            x = logins.get(lid)
            if not x:
                continue
            why = []
            if iss["leaked"]:
                why.append(f"found in data breaches ({iss['leaked']:,} times)")
            if iss["reused"]:
                why.append(f"also used on {iss['reused']} other saved login" + ("s" if iss["reused"] > 1 else ""))
            if iss["weak"]:
                why.append("easy to guess")
            item = QListWidgetItem(f"{display_site(x['origin'])}  ·  {x['username'] or '(no username)'}\n"
                                   f"    {'; '.join(why).capitalize()}")
            item.setData(Qt.UserRole, lid)
            self.issues.addItem(item)
        leaked = sum(1 for i in out["issues"].values() if i["leaked"])
        if out.get("error"):
            msg = f"Checked for reuse and weak passwords, but {out['error']}."
        elif not out["issues"]:
            msg = f"All {out['checked']} passwords look fine."
        else:
            msg = (f"{len(out['issues'])} of {out['checked']} need attention"
                   + (f", {leaked} of them leaked." if leaked else "."))
        self.check_status.setText(msg)

    def _fix_issue(self, edit: bool):
        it = self.issues.currentItem()
        login = self.store.get(it.data(Qt.UserRole)) if it is not None else None
        if not login:
            return
        if not edit:
            self.win.open_tab(login["origin"])
            return
        d = LoginDialog(self, login)
        if d.exec():
            self.store.update(login["id"], **d.values())
            self.reload()
            self.check_status.setText("Saved. Run the check again to update the list.")

    def reload(self, *_):
        q = self.search.text().lower()
        rows = [x for x in self.store.logins()
                if q in x["origin"].lower() or q in x["username"].lower() or q in x.get("note", "").lower()]
        self.table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            site = QTableWidgetItem(display_site(x["origin"]))
            site.setData(Qt.UserRole, x["id"])
            site.setToolTip(x["origin"])
            self.table.setItem(r, 0, site)
            self.table.setItem(r, 1, QTableWidgetItem(x["username"]))
            self.table.setItem(r, 2, QTableWidgetItem(x["password"] if x["id"] in self.shown else MASK))
        self.never_list.clear()
        for origin in self.store.never_sites():
            self.never_list.addItem(origin)

    def _selected(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _toggle_show(self):
        lid = self._selected()
        if lid:
            self.shown ^= {lid}
            self.reload()

    def _copy(self):
        login = self.store.get(self._selected() or "")
        if not login:
            return
        cb = QApplication.clipboard()
        cb.setText(login["password"])
        pw = login["password"]
        # Clear the clipboard after 30 s unless something else was copied meanwhile.
        QTimer.singleShot(30000, lambda: cb.clear() if cb.text() == pw else None)

    def _add(self):
        d = LoginDialog(self)
        if d.exec():
            v = d.values()
            self.store.add(v["origin"], v["username"], v["password"], v["note"])
            self.reload()

    def _edit(self):
        login = self.store.get(self._selected() or "")
        if not login:
            return
        d = LoginDialog(self, login)
        if d.exec():
            self.store.update(login["id"], **d.values())
            self.reload()

    def _delete(self):
        login = self.store.get(self._selected() or "")
        if login and QMessageBox.question(
                self, "Delete password",
                f"Delete the saved password for {login['username'] or 'this login'} on "
                f"{display_site(login['origin'])}?") == QMessageBox.Yes:
            self.store.delete(login["id"])
            self.reload()

    def _remove_never(self):
        for it in self.never_list.selectedItems():
            self.store.remove_never(it.text())
        self.reload()

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import passwords", "", "CSV files (*.csv)")
        if not path:
            return
        try:
            added, updated, skipped = self.store.import_csv(path)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", f"Couldn't read that file: {e}")
            return
        self.reload()
        QMessageBox.information(self, "Import finished",
                                f"Added {added}, updated {updated}, skipped {skipped}.\n\n"
                                "Delete the CSV file now: it holds your passwords unencrypted.")

    def _import_google(self):
        self.manager.start_google_import(self.win)
        self.accept()
