"""WatchManager: owns every Watcher (creation, persistence, wake-up actions, desktop notifications)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from .automation import MAX_WATCHERS, Watcher, describe_spec


class Watches(QObject):
    changed = Signal()
    notified = Signal(str, str)     # title, message (also shown in the AI panel)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.items: dict[str, Watcher] = {}
        self.notifications: list[tuple[str, str]] = []
        self._tray = None
        self._closing = False

    # -- creation / persistence
    def create(self, spec: dict, confirm=None, start: bool = True) -> Watcher:
        live = [w for w in self.items.values() if w.enabled]
        if len(live) >= MAX_WATCHERS:
            raise ValueError(f"at most {MAX_WATCHERS} watchers can run at once; delete or pause one first")
        if confirm is not None and not confirm(describe_spec(spec)):
            raise ValueError("the user declined this watcher")
        w = Watcher(self.ctx, spec, self)
        w.fired.connect(self.on_fired)
        w.changed.connect(self.changed)
        w.ended.connect(self.save)
        self.items[w.id] = w
        if start:
            w.start()
        self.save()
        self.changed.emit()
        return w

    def delete(self, wid: str):
        w = self.items.pop(wid, None)
        if w:
            w.stop("deleted")
        self.save()
        self.changed.emit()

    def find(self, key: str) -> Watcher | None:
        key = str(key).strip().lower()
        for w in self.items.values():
            if w.id == key or w.name.lower() == key:
                return w
        return next((w for w in self.items.values() if key and key in w.name.lower()), None)

    def save(self):
        if self._closing:    # quitting stops every watcher; keep the last saved list so they resume next launch
            return
        keep = [{**w.spec, "_enabled": w.enabled} for w in self.items.values()
                if not (not w.enabled and w.status.startswith(("done", "finished", "deleted")))]
        self.ctx.store.set("watchers", keep)

    def load(self):
        for spec in self.ctx.store.get("watchers") or []:
            try:
                enabled = spec.pop("_enabled", True)
                spec.setdefault("then", ["notify"])
                w = self.create(spec, start=False)
                if enabled:
                    w.start(3000 + 700 * len(self.items))
                else:
                    w.enabled, w.status = False, "paused"
            except (ValueError, KeyError):
                continue

    def stop_all(self):
        self._closing = True
        for w in list(self.items.values()):
            w.stop("app closed")

    # -- wake-ups
    def notify(self, title: str, msg: str):
        self.notifications.append((title, msg))
        del self.notifications[:-50]
        self.notified.emit(title, msg)
        try:
            from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
            from PySide6.QtWidgets import QSystemTrayIcon
            if QSystemTrayIcon.isSystemTrayAvailable():
                if self._tray is None:
                    pix = QPixmap(32, 32)
                    pix.fill(Qt.transparent)
                    p = QPainter(pix)
                    p.setRenderHint(QPainter.Antialiasing)
                    p.setBrush(QColor("#1B8C9A"))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(2, 2, 28, 28)
                    p.end()
                    self._tray = QSystemTrayIcon(QIcon(pix))
                    self._tray.setToolTip("Pelagic")
                    self._tray.show()
                self._tray.showMessage(title, msg[:240], QSystemTrayIcon.Information, 9000)
        except Exception:  # noqa: BLE001 - a notification problem must never break a watcher
            pass

    def on_fired(self, w: Watcher, reason: str, snap):
        from PySide6.QtWidgets import QApplication
        then, url = w.spec["then"], w.spec["url"]
        self.notify(f"Pelagic: {w.name}", f"{reason} — {url}")
        if "beep" in then:
            QApplication.beep()
        if "open" in then:
            self.ctx.open_urls([url])
        panel = self.ctx.window().panel
        if "ask_ai" in then:
            panel.watch_ask(w, reason, snap)
        if "agent" in then:
            panel.watch_agent(w)
        self.save()
        self.changed.emit()
