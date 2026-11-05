"""Addresses and cards page: add, edit and delete what autofill offers on forms."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import secretbox
from .autofill import address_label, card_label, digits, luhn_ok

ADDRESS_FORM = (("name", "Name"), ("organization", "Company"), ("street", "Street address"),
                ("street2", "Apartment, suite, etc."), ("city", "City"), ("state", "State / province"),
                ("postal", "ZIP / postal code"), ("country", "Country"), ("tel", "Phone"), ("email", "Email"))


class AddressDialog(QDialog):
    def __init__(self, parent, item: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit address" if item else "Add address")
        self.resize(440, 0)
        item = item or {}
        self.edits = {}
        f = QFormLayout()
        for key, label in ADDRESS_FORM:
            self.edits[key] = QLineEdit(item.get(key, ""))
            f.addRow(label, self.edits[key])
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(buttons)

    def _ok(self):
        if not any(e.text().strip() for e in self.edits.values()):
            QMessageBox.warning(self, "Address", "Fill in at least one field.")
            return
        self.accept()

    def values(self) -> dict:
        return {k: e.text() for k, e in self.edits.items()}


class CardDialog(QDialog):
    def __init__(self, parent, item: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit card" if item else "Add card")
        self.resize(420, 0)
        item = item or {}
        self.number = QLineEdit(item.get("cc_number", ""))
        self.number.setPlaceholderText("1234 5678 9012 3456")
        self.name = QLineEdit(item.get("cc_name", ""))
        self.month = QComboBox()
        self.year = QComboBox()
        self.month.addItems([f"{m:02d}" for m in range(1, 13)])
        import datetime
        now = datetime.date.today().year
        years = [str(y) for y in range(now - 1, now + 16)]
        if item.get("cc_year") and item["cc_year"] not in years:
            years.insert(0, item["cc_year"])
        self.year.addItems(years)
        if item.get("cc_month"):
            self.month.setCurrentIndex(max(0, int(item["cc_month"]) - 1))
        self.year.setCurrentText(item.get("cc_year") or str(now + 3))
        exp = QHBoxLayout()
        exp.addWidget(self.month)
        exp.addWidget(QLabel("/"))
        exp.addWidget(self.year)
        exp.addStretch(1)
        self.nickname = QLineEdit(item.get("nickname", ""))
        self.nickname.setPlaceholderText("Optional, e.g. Work card")
        f = QFormLayout()
        f.addRow("Card number", self.number)
        f.addRow("Name on card", self.name)
        f.addRow("Expires", exp)
        f.addRow("Nickname", self.nickname)
        note = QLabel("The security code (CVC) is never saved. You type it each time.")
        note.setObjectName("muted")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(note)
        lay.addWidget(buttons)

    def _ok(self):
        if not luhn_ok(self.number.text()):
            QMessageBox.warning(self, "Card number", "That doesn't look like a valid card number.")
            return
        self.accept()

    def values(self) -> dict:
        return {"cc_number": digits(self.number.text()), "cc_name": self.name.text(),
                "cc_month": str(self.month.currentIndex() + 1), "cc_year": self.year.currentText(),
                "nickname": self.nickname.text()}


class AutofillDialog(QDialog):
    def __init__(self, autofill, win):
        super().__init__(win)
        self.autofill, self.store = autofill, autofill.store
        self.setWindowTitle("Addresses and cards")
        self.resize(560, 440)
        self.offer = QCheckBox("Offer to save and fill addresses and cards")
        self.offer.setChecked(autofill.enabled())
        self.offer.toggled.connect(lambda on: win.store.set("autofill", bool(on)))
        self.lists = {}
        tabs = QTabWidget()
        for kind, title, dialog in (("addresses", "Addresses", AddressDialog), ("cards", "Payment cards", CardDialog)):
            page = QWidget()
            v = QVBoxLayout(page)
            lst = QListWidget()
            lst.itemDoubleClicked.connect(lambda _i, k=kind, d=dialog: self._edit(k, d))
            self.lists[kind] = lst
            v.addWidget(lst, 1)
            row = QHBoxLayout()
            for text, slot in (("Add…", lambda _=False, k=kind, d=dialog: self._add(k, d)),
                               ("Edit…", lambda _=False, k=kind, d=dialog: self._edit(k, d)),
                               ("Delete", lambda _=False, k=kind: self._delete(k))):
                b = QPushButton(text)
                b.clicked.connect(slot)
                row.addWidget(b)
            row.addStretch(1)
            v.addLayout(row)
            tabs.addTab(page, title)
        note = QLabel(f"Saved on this computer, encrypted with {secretbox.where()}. "
                      "The AI never sees card details and never fills these in.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.offer)
        lay.addWidget(tabs, 1)
        lay.addWidget(note)
        lay.addWidget(close)
        self.reload()

    def reload(self):
        for kind, lst in self.lists.items():
            lst.clear()
            for it in self.store.items(kind):
                if kind == "cards":
                    text = card_label(it) + (f"   ·  {it.get('cc_name')}" if it.get("cc_name") else "")
                    if it.get("cc_month"):
                        text += f"   ·  expires {int(it['cc_month']):02d}/{it.get('cc_year', '')[-2:]}"
                else:
                    text = address_label(it)
                row = QListWidgetItem(text)
                row.setData(256, it["id"])
                lst.addItem(row)

    def _current(self, kind):
        it = self.lists[kind].currentItem()
        return it.data(256) if it is not None else None

    def _add(self, kind, dialog):
        d = dialog(self)
        if d.exec():
            self.store.save(kind, d.values())
            self.reload()

    def _edit(self, kind, dialog):
        item_id = self._current(kind)
        item = self.store.get(kind, item_id) if item_id else None
        if not item:
            return
        d = dialog(self, item)
        if d.exec():
            self.store.save(kind, d.values(), item_id)
            self.reload()

    def _delete(self, kind):
        item_id = self._current(kind)
        if item_id and QMessageBox.question(self, "Delete", "Delete this saved item?") == QMessageBox.Yes:
            self.store.delete(kind, item_id)
            self.reload()
