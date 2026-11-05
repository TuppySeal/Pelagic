"""Automations window: list, create, pause, run-now and delete watchers."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from .automation import describe_condition, new_spec

KINDS = [("Page shows this text", "text"), ("This text disappears", "gone"), ("Page changes", "changed"),
         ("Number goes below…", "number<"), ("Number goes above…", "number>"), ("A button/link appears", "element"),
         ("No condition — just repeat the steps", "none")]
UNITS = [("seconds", 1), ("minutes", 60), ("hours", 3600)]


class NewWatchDialog(QDialog):
    def __init__(self, current_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New automation")
        self.resize(520, 480)
        f = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. PS5 back in stock")
        self.url = QLineEdit(current_url if current_url.startswith("http") else "")
        row = QHBoxLayout()
        self.every = QDoubleSpinBox()
        self.every.setRange(1, 9999)
        self.every.setValue(30)
        self.unit = QComboBox()
        for label, _ in UNITS:
            self.unit.addItem(label)
        row.addWidget(self.every)
        row.addWidget(self.unit, 1)
        self.kind = QComboBox()
        for label, _ in KINDS:
            self.kind.addItem(label)
        self.value = QLineEdit()
        self.value.setPlaceholderText("text / number / control label")
        self.near = QLineEdit()
        self.near.setPlaceholderText("optional: only look next to this word (e.g. Price)")
        self.steps = QPlainTextEdit()
        self.steps.setPlaceholderText("Optional steps to run each time, one per line, in plain words:\nclick Refresh\nscroll down")
        self.steps.setFixedHeight(64)
        self.notify = QCheckBox("Show a desktop notification")
        self.notify.setChecked(True)
        self.beep = QCheckBox("Play a sound")
        self.open = QCheckBox("Open the page in a tab")
        self.ask = QCheckBox("Ask the AI about the page (spends tokens, once)")
        self.ask_text = QLineEdit()
        self.ask_text.setPlaceholderText("What should the AI tell you? (optional)")
        self.once = QCheckBox("Stop after the first match")
        self.once.setChecked(True)
        f.addRow("Name", self.name)
        f.addRow("Page address", self.url)
        f.addRow("Check every", row)
        f.addRow("Wake me when", self.kind)
        f.addRow("Value", self.value)
        f.addRow("Near", self.near)
        f.addRow("Steps", self.steps)
        for w in (self.notify, self.beep, self.open, self.ask):
            f.addRow(w)
        f.addRow(self.ask_text)
        f.addRow(self.once)
        note = QLabel("Checks run in an invisible tab with your logged-in sessions. No AI is used until a match.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        f.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)
        self.spec = None

    def _ok(self):
        from .localai import parse_steps
        kind = KINDS[self.kind.currentIndex()][1]
        value, near = self.value.text().strip(), self.near.text().strip()
        cond = None
        if kind in ("text", "gone", "element"):
            cond = {"type": kind, "value": value}
        elif kind == "changed":
            cond = {"type": "changed"}
        elif kind in ("number<", "number>"):
            cond = {"type": "number", "op": kind[-1], "num": value}
        if cond and near:
            cond["near"] = near
        lines = [ln for ln in self.steps.toPlainText().splitlines() if ln.strip()]
        steps, bad = parse_steps(" then ".join(lines)) if lines else ([], "")
        if steps is None:
            return QMessageBox.warning(self, "Automation", f"I don't understand the step “{bad}”.")
        then = [n for n, cb in (("notify", self.notify), ("beep", self.beep), ("open", self.open),
                                ("ask_ai", self.ask)) if cb.isChecked()]
        try:
            self.spec = new_spec(self.name.text() or "Automation", self.url.text(),
                                 self.every.value() * UNITS[self.unit.currentIndex()][1], cond, steps,
                                 then or ["notify"], ask=self.ask_text.text(), repeat=not self.once.isChecked(),
                                 reload=not steps)
        except ValueError as e:
            return QMessageBox.warning(self, "Automation", str(e))
        self.accept()


class AutomationsDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win, self.watches = win, win.ctx.watches
        self.setWindowTitle("Automations")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Automations check pages in the background and wake you (or the AI) only when "
                             "their condition is met. They cost no tokens while waiting."))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda *_: self._buttons())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btns = {}
        for key, label, slot in (("new", "New…", self._new), ("toggle", "Pause / Resume", self._toggle),
                                 ("run", "Check now", self._run), ("del", "Delete", self._delete)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.btns[key] = b
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.watches.changed.connect(self.refresh)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self):
        sel = self._current_id()
        self.list.blockSignals(True)
        self.list.clear()
        for w in self.watches.items.values():
            s = w.spec
            mark = "●" if w.enabled else "○"
            when = describe_condition(s.get("condition"))
            it = QListWidgetItem(f"{mark} {w.name} — every {s['every']:g}s — {when}\n"
                                 f"    {w.status}   ·   {w.runs} checks, {w.matches} matches   ·   {s['url'][:70]}")
            it.setData(Qt.UserRole, w.id)
            self.list.addItem(it)
            if w.id == sel:
                self.list.setCurrentItem(it)
        if not self.list.count():
            self.list.addItem("No automations yet. Click New…, or in Local mode say: "
                              "refresh every 30 seconds until “in stock” appears and notify me")
            self.list.item(0).setFlags(Qt.NoItemFlags)
        self.list.blockSignals(False)
        self._buttons()

    def _current_id(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _watcher(self):
        return self.watches.items.get(self._current_id())

    def _buttons(self):
        has = self._watcher() is not None
        for k in ("toggle", "run", "del"):
            self.btns[k].setEnabled(has)

    def _new(self):
        tab = self.win.current_tab()
        d = NewWatchDialog(tab.url().toString() if tab else "", self)
        if d.exec() and d.spec:
            try:
                self.watches.create(d.spec)
            except ValueError as e:
                QMessageBox.warning(self, "Automation", str(e))

    def _toggle(self):
        w = self._watcher()
        if w:
            w.pause() if w.enabled else w.resume()
            self.watches.save()

    def _run(self):
        w = self._watcher()
        if w:
            w.run_now()

    def _delete(self):
        w = self._watcher()
        if w:
            self.watches.delete(w.id)
