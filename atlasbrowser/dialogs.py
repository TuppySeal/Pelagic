"""Settings and token usage dialogs."""
from __future__ import annotations

import os
import html
import re
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import providers, secretbox
from .agent import run_in_pool
from .store import SEARCH_ENGINES


class SettingsDialog(QDialog):
    TABS = ("general", "homepage", "profiles", "passwords", "privacy", "connection", "sync", "ai", "agent")

    def __init__(self, store, parent=None, win=None, start: str = "general"):
        super().__init__(parent)
        self.store, self.win = store, win
        self.setWindowTitle("Settings")
        self.resize(820, 560)
        self.current: str | None = None
        self.pending_keys: dict[str, str] = {}
        self.pending_models: dict[str, str] = {}
        self.pending_urls: dict[str, str] = {}
        self.pending_prices = dict(store.get("price_overrides") or {})
        self.removed_keys: set[str] = set()
        self.model_lists: dict[str, list[str]] = {}

        tabs = QTabWidget()
        tabs.addTab(self._browser_tab(), "General")
        from .homepage import HomepageSettings
        self.homepage = HomepageSettings(store)
        tabs.addTab(self.homepage, "Homepage")
        tabs.addTab(self._profiles_tab(), "Profiles")
        tabs.addTab(self._passwords_tab(), "Passwords")
        tabs.addTab(self._privacy_tab(), "Privacy")
        from .network_ui import ConnectionPage
        self.connection = ConnectionPage(store)
        tabs.addTab(self.connection, "Connection")
        ctx = getattr(self.win, "ctx", None)
        if ctx is not None and hasattr(ctx, "sync") and not getattr(self.win, "private", False):
            from .sync_ui import SyncPage
            tabs.addTab(SyncPage(ctx), "Sync")
        else:
            tabs.addTab(QLabel("  Sync isn't available in private windows."), "Sync")
        tabs.addTab(self._ai_tab(), "AI providers")
        tabs.addTab(self._agent_tab(), "Agent")
        tabs.setCurrentIndex(self.TABS.index(start) if start in self.TABS else 0)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)
        self._reload_list()

    # ------------------------------------------------------------ AI tab
    def _ai_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        self.plist = QListWidget()
        self.plist.setMaximumWidth(250)
        self.plist.currentItemChanged.connect(self._select)
        left.addWidget(self.plist, 1)
        add = QPushButton("Add custom provider…")
        add.clicked.connect(self._add_custom)
        left.addWidget(add)
        lay.addLayout(left)

        right = QFormLayout()
        self.title = QLabel("")
        self.title.setStyleSheet("font-size:16px;font-weight:600")
        self.url_edit = QLineEdit()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_hint = QLabel("")
        self.key_hint.setObjectName("muted")
        self.key_hint.setWordWrap(True)
        mrow = QHBoxLayout()
        self.model_edit = QComboBox()
        self.model_edit.setEditable(True)
        fetch = QPushButton("Fetch models")
        fetch.clicked.connect(self._fetch)
        mrow.addWidget(self.model_edit, 1)
        mrow.addWidget(fetch)
        brow = QHBoxLayout()
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        self.rm_key = QPushButton("Remove saved key")
        self.rm_key.clicked.connect(self._remove_key)
        self.rm_prov = QPushButton("Delete provider")
        self.rm_prov.clicked.connect(self._delete_custom)
        brow.addWidget(test)
        brow.addWidget(self.rm_key)
        brow.addWidget(self.rm_prov)
        brow.addStretch(1)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        right.addRow(self.title)
        right.addRow("Base URL", self.url_edit)
        right.addRow("API key", self.key_edit)
        right.addRow("", self.key_hint)
        right.addRow("Model", mrow)
        self.custom_price = QCheckBox("Set custom USD rates for this model")
        self.price_input, self.price_output, self.price_cache = QLineEdit(), QLineEdit(), QLineEdit()
        for edit in (self.price_input, self.price_output, self.price_cache):
            edit.setPlaceholderText("USD per 1 million tokens")
        right.addRow(self.custom_price)
        right.addRow("Input USD / million", self.price_input)
        right.addRow("Output USD / million", self.price_output)
        right.addRow("Cached input USD / million", self.price_cache)
        self.custom_price.toggled.connect(lambda v: [e.setEnabled(v) for e in
                                                    (self.price_input, self.price_output, self.price_cache)])
        right.addRow("", brow)
        right.addRow("", self.result)
        rw = QWidget()
        rw.setLayout(right)
        lay.addWidget(rw, 1)
        return w

    def _reload_list(self, select: str | None = None):
        self._commit()
        self.plist.blockSignals(True)
        self.plist.clear()
        for p in providers.all_providers(self.store):
            has = bool(self.pending_keys.get(p.id) or (providers.resolve_key(self.store, p) and p.id not in self.removed_keys)) \
                or not p.needs_key
            it = QListWidgetItem(("● " if has else "○ ") + p.name)
            it.setData(Qt.UserRole, p.id)
            self.plist.addItem(it)
        self.plist.blockSignals(False)
        target = select or self.current or self.store.get("selected")
        for i in range(self.plist.count()):
            if self.plist.item(i).data(Qt.UserRole) == target:
                self.current = None
                self.plist.setCurrentRow(i)
                return
        self.current = None
        self.plist.setCurrentRow(0)

    def _commit(self):
        pid = self.current
        if not pid:
            return
        if self.key_edit.text().strip():
            self.pending_keys[pid] = self.key_edit.text().strip()
            self.removed_keys.discard(pid)
        self.pending_models[pid] = self.model_edit.currentText().strip()
        self.pending_urls[pid] = self.url_edit.text().strip()
        model = self.model_edit.currentText().strip()
        rate_key = f"{pid}:{model}"
        if self.custom_price.isChecked():
            try:
                rates = {"input": float(self.price_input.text()), "output": float(self.price_output.text())}
                if self.price_cache.text().strip():
                    rates["cache_input"] = float(self.price_cache.text())
                if all(0 <= value < 1e9 for value in rates.values()):
                    self.pending_prices[rate_key] = rates
            except ValueError:
                pass
        else:
            self.pending_prices.pop(rate_key, None)

    def _select(self, item, _prev=None):
        self._commit()
        if not item:
            return
        pid = item.data(Qt.UserRole)
        self.current = pid
        p = providers.find_provider(self.store, pid)
        self.title.setText(p.name)
        self.url_edit.setText(self.pending_urls.get(pid, p.base_url))
        self.key_edit.clear()
        saved = bool(self.store.get_key(pid)) and pid not in self.removed_keys
        env = next((v for v in p.env if os.environ.get(v)), "")
        if pid in self.pending_keys:
            self.key_hint.setText("New key will be saved when you press OK.")
        elif saved:
            self.key_hint.setText(f"A key is saved (encrypted with {secretbox.where()}). Leave blank to keep it.")
        elif env:
            self.key_hint.setText(f"Using the {env} environment variable. Enter a key here to override.")
        elif not p.needs_key:
            self.key_hint.setText("No key needed for local servers.")
        else:
            self.key_hint.setText("Not set. " + (f"Also reads {', '.join(p.env)} from the environment." if p.env else ""))
        self.model_edit.clear()
        names = list(self.model_lists.get(pid) or (self.store.get("model_cache") or {}).get(pid, []))
        cur = self.pending_models.get(pid, p.model)
        if cur and cur not in names:
            names.insert(0, cur)
        self.model_edit.addItems(names)
        self.model_edit.setCurrentText(cur)
        rates = self.pending_prices.get(f"{pid}:{cur}")
        self.custom_price.setChecked(rates is not None)
        for key, edit in (("input", self.price_input), ("output", self.price_output), ("cache_input", self.price_cache)):
            edit.setText(str(rates.get(key, "")) if rates else "")
            edit.setEnabled(rates is not None)
        self.rm_prov.setVisible(p.custom)
        self.result.setText("")

    def _effective(self) -> tuple[providers.Provider, str]:
        self._commit()
        p = providers.find_provider(self.store, self.current)
        p.base_url = self.pending_urls.get(p.id) or p.base_url
        p.model = self.pending_models.get(p.id) or p.model
        p.rates = self.pending_prices.get(f"{p.id}:{p.model}", p.rates)
        key = self.pending_keys.get(p.id) or ("" if p.id in self.removed_keys else providers.resolve_key(self.store, p))
        return p, key

    def _fetch(self):
        p, key = self._effective()
        self.result.setText("Fetching models…")

        def done(_t, out):
            if isinstance(out, Exception):
                self.result.setText(f"✗ {out}")
                return
            self.model_lists[p.id] = out
            if self.current == p.id:
                cur = self.model_edit.currentText()
                self.model_edit.clear()
                self.model_edit.addItems(out)
                self.model_edit.setCurrentText(cur)
            self.result.setText(f"✓ {len(out)} models found.")
        run_in_pool(0, lambda: providers.list_models(p, key), done)

    def _test(self):
        p, key = self._effective()
        self.result.setText("Testing…")

        def done(_t, out):
            if self.parent() is not None and hasattr(self.parent(), "panel"):
                self.parent().panel._task_end("test", p, "Provider connection test", meter,
                                              "error" if isinstance(out, Exception) else "done")
            self.result.setText(f"✗ {out}" if isinstance(out, Exception) else f"✓ Works. Reply: {out.strip()[:120]}")
        from .usage import Meter
        parent_panel = getattr(self.parent(), "panel", None)
        meter = Meter(parent_panel.session if parent_panel else None)
        run_in_pool(0, lambda: providers.chat(p, key, [{"role": "user", "content": "Reply with the single word: OK"}],
                                               timeout=45, max_tokens=64, meter=meter), done)

    def _remove_key(self):
        if self.current:
            self.pending_keys.pop(self.current, None)
            self.removed_keys.add(self.current)
            self.key_edit.clear()
            self.key_hint.setText("Saved key will be removed when you press OK.")
            self._reload_list(self.current)

    def _add_custom(self):
        name, ok = QInputDialog.getText(self, "Custom provider", "Display name (e.g. My vLLM server):")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, "Custom provider", "Base URL (OpenAI-compatible ends in /v1):")
        if not ok or not url.strip():
            return
        kinds = ["OpenAI-compatible", "Anthropic", "Gemini"]
        kind, ok = QInputDialog.getItem(self, "Custom provider", "API format:", kinds, 0, False)
        if not ok:
            return
        model, ok = QInputDialog.getText(self, "Custom provider", "Default model name:")
        if not ok:
            return
        pid = "custom-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + f"-{int(time.time()) % 10000}"
        custom = list(self.store.get("custom") or [])
        custom.append({"id": pid, "name": name.strip(), "base_url": url.strip(), "model": model.strip(),
                       "kind": {"Anthropic": "anthropic", "Gemini": "gemini"}.get(kind, "openai"),
                       "needs_key": True})
        self.store.set("custom", custom)
        self._reload_list(pid)

    def _delete_custom(self):
        if not self.current:
            return
        if QMessageBox.question(self, "Delete provider", "Delete this custom provider?") != QMessageBox.Yes:
            return
        self.store.set("custom", [c for c in self.store.get("custom") if c["id"] != self.current])
        self.store.set_key(self.current, "")
        self.current = None
        self._reload_list("gemini")

    # ------------------------------------------------------------ other tabs
    def _browser_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.engine = QComboBox()
        for k, (name, _) in SEARCH_ENGINES.items():
            self.engine.addItem(name, k)
        self.engine.setCurrentIndex(max(self.engine.findData(self.store.get("search_engine")), 0))
        self.home = QLineEdit(self.store.get("home"))
        self.home.setPlaceholderText("atlas:start or https://…")
        f.addRow("Search engine", self.engine)
        f.addRow("Home page", self.home)
        self.autocomplete = QCheckBox("Autocomplete searches and URLs")
        self.autocomplete.setChecked(bool(self.store.get("autocomplete")))
        self.autocomplete.setToolTip("Suggests sites from your history and bookmarks as you type in the address bar, "
                                     "and asks your search engine for search suggestions")
        f.addRow("", self.autocomplete)
        self.tab_sleep = QCheckBox("Put unused tabs to sleep to save memory")
        self.tab_sleep.setChecked(bool(self.store.get("tab_sleep")))
        self.tab_sleep.setToolTip("Tabs you haven't looked at for a while give back their memory. They keep their "
                                  "place and reload when you click them. Pinned tabs and tabs playing sound stay awake.")
        self.sleep_minutes = QSpinBox()
        self.sleep_minutes.setRange(1, 24 * 60)
        self.sleep_minutes.setSuffix(" min")
        self.sleep_minutes.setValue(int(self.store.get("tab_sleep_minutes") or 30))
        self.sleep_minutes.setEnabled(self.tab_sleep.isChecked())
        self.tab_sleep.toggled.connect(self.sleep_minutes.setEnabled)
        sleep_row = QHBoxLayout()
        sleep_row.addWidget(self.tab_sleep)
        sleep_row.addWidget(QLabel("after"))
        sleep_row.addWidget(self.sleep_minutes)
        sleep_row.addStretch(1)
        f.addRow("", sleep_row)
        self.tab_previews = QCheckBox("Show a preview when the pointer rests on a tab")
        self.tab_previews.setChecked(self.store.get("tab_previews") is not False)
        f.addRow("", self.tab_previews)
        self.vertical_tabs = QCheckBox("Vertical tabs (down the left side)")
        self.vertical_tabs.setChecked(bool(self.store.get("vertical_tabs")))
        f.addRow("", self.vertical_tabs)
        from .spellcheck import LANGUAGES
        self.spellcheck = QCheckBox("Check spelling as I type, in")
        self.spellcheck.setChecked(bool(self.store.get("spellcheck")))
        self.spellcheck.setToolTip("Underlines misspelled words in text boxes; right-click one for suggestions. "
                                   "The first time, the dictionary for the language is downloaded.")
        self.spell_lang = QComboBox()
        for code, (name, _file) in LANGUAGES.items():
            self.spell_lang.addItem(name, code)
        self.spell_lang.setCurrentIndex(max(0, self.spell_lang.findData(self.store.get("spellcheck_lang") or "en-US")))
        self.spell_lang.setEnabled(self.spellcheck.isChecked())
        self.spellcheck.toggled.connect(self.spell_lang.setEnabled)
        spell_row = QHBoxLayout()
        spell_row.addWidget(self.spellcheck)
        spell_row.addWidget(self.spell_lang)
        spell_row.addStretch(1)
        f.addRow("", spell_row)
        self.memory_path = QLineEdit(self.store.get("memory_file") or "")
        self.memory_path.setPlaceholderText(str(self.store.root / "Atlas Memory.md"))
        f.addRow("Memory file (read only on request)", self.memory_path)
        return w

    @staticmethod
    def _note(text):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setObjectName("muted")
        return lab

    def _button_row(self, *buttons):
        row = QHBoxLayout()
        for text, slot in buttons:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        return row

    def _profiles_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hub = getattr(getattr(self.win, "ctx", None), "hub", None)
        if hub is None:
            v.addWidget(self._note("Profiles aren't available in this window."))
        else:
            me = hub.info(self.win.ctx.pid)
            v.addWidget(QLabel(f"You're using the <b>{html.escape(me['name'])}</b> profile."))
            v.addWidget(self._note("Each profile has its own passwords, history, bookmarks, sign-ins, tabs and "
                                   "automations. API keys and AI settings are shared by all profiles. "
                                   "The profile button at the right end of the toolbar switches between them."))
            from .profiles_ui import ManageProfilesDialog, add_profile
            v.addLayout(self._button_row(("Manage profiles…", lambda: ManageProfilesDialog(hub, self.win).exec()),
                                         ("Add profile…", lambda: add_profile(hub, self.win))))
        v.addStretch(1)
        return w

    def _passwords_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.offer_passwords = QCheckBox("Offer to save passwords when I sign in")
        self.offer_passwords.setChecked(self.store.get("save_passwords") is not False)
        v.addWidget(self.offer_passwords)
        v.addWidget(self._note(f"Saved passwords are encrypted with {secretbox.where()}, kept separately for each "
                               "profile, never saved from private windows and never shown to the AI."))
        if self.win is not None and hasattr(self.win, "show_passwords"):
            def google():
                self.win.ctx.passwords.start_google_import(self.win)
                self.accept()
            def manage():
                self.win.show_passwords()
                self.offer_passwords.setChecked(self.store.get("save_passwords") is not False)
            v.addLayout(self._button_row(("Manage passwords…", manage),
                                         ("Import from Google…", google)))
        self.offer_autofill = QCheckBox("Offer to save and fill addresses and payment cards")
        self.offer_autofill.setChecked(self.store.get("autofill") is not False)
        v.addSpacing(10)
        v.addWidget(self.offer_autofill)
        v.addWidget(self._note("Card security codes are never saved, and the AI never sees card details."))
        if self.win is not None and hasattr(self.win, "show_autofill"):
            def manage_autofill():
                self.win.show_autofill()
                self.offer_autofill.setChecked(self.store.get("autofill") is not False)
            v.addLayout(self._button_row(("Manage addresses and cards…", manage_autofill)))
        v.addStretch(1)
        return w

    def _privacy_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self._note("These apply to the current profile only."))
        self.safe_browsing = QCheckBox("Warn me before opening dangerous or deceptive sites")
        self.safe_browsing.setChecked(self.store.get("safe_browsing") is not False)
        v.addWidget(self.safe_browsing)
        v.addWidget(self._note("Checked on this computer against public phishing and malware lists that update "
                               "every few hours. The sites you visit aren't sent anywhere."))
        v.addSpacing(8)

        def clear_history():
            if QMessageBox.question(self, "Clear history", "Delete all browsing history for this profile?") \
                    == QMessageBox.Yes:
                self.store.clear_history()

        def clear_cookies():
            if self.win is None:
                return
            if QMessageBox.question(self, "Clear cookies", "Sign out of all sites and delete cookies and site data "
                                    "for this profile?") == QMessageBox.Yes:
                self.win.ctx.profile.cookieStore().deleteAllCookies()
                self.win.ctx.profile.clearAllVisitedLinks()

        def clear_cache():
            if self.win is not None:
                self.win.ctx.profile.clearHttpCache()
                QMessageBox.information(self, "Cache", "Cached images and files were cleared.")
        v.addLayout(self._button_row(("Clear history…", clear_history), ("Clear cookies and sign-ins…", clear_cookies),
                                     ("Clear cached files", clear_cache)))
        v.addSpacing(8)
        v.addWidget(QLabel("<b>Blocked domains</b>"))
        v.addWidget(self._note("Like Pi-hole: block whole domains (ads, trackers, distracting sites) in pages and in "
                               "everything pages load. Add your own or download blocklists."))

        def edit_blocklist():
            from .network_ui import BlocklistDialog
            BlocklistDialog(self.store, getattr(getattr(self.win, "ctx", None), "domains", None), self).exec()
        v.addLayout(self._button_row(("Edit blocked domains…", edit_blocklist)))
        v.addStretch(1)
        return w

    def _agent_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.steps = QSpinBox()
        self.steps.setRange(3, 200)
        self.steps.setValue(int(self.store.get("max_steps")))
        self.guard = QCheckBox("Ask me before clicks that look irreversible (buy, send, delete, post…)")
        self.guard.setChecked(bool(self.store.get("guard")))
        self.confirm_all = QCheckBox("Ask me before every agent action")
        self.confirm_all.setChecked(bool(self.store.get("confirm_all")))
        self.vision = QCheckBox("Send screenshots to the model (needs a vision-capable model)")
        self.vision.setChecked(bool(self.store.get("vision")))
        self.vision_every_step = QCheckBox("Send screenshots every step instead of only when visual context is needed")
        self.vision_every_step.setChecked(bool(self.store.get("vision_every_step")))
        self.humanize = QCheckBox("Humanize: glide the cursor slowly and type letter by letter with human-like pauses")
        self.humanize.setChecked(bool(self.store.get("humanize")))
        self.batch = QCheckBox("Let the AI plan several actions per reply (faster, fewer tokens); off = one step at a time")
        self.batch.setChecked(bool(self.store.get("batch")))
        self.token_saver = QCheckBox("Save tokens: compact context, concise output, and supported prompt caching")
        self.token_saver.setChecked(self.store.get("token_saver") is not False)
        f.addRow("Max steps per task", self.steps)
        f.addRow(self.batch)
        f.addRow(self.token_saver)
        f.addRow(self.humanize)
        f.addRow(self.guard)
        f.addRow(self.confirm_all)
        f.addRow(self.vision)
        f.addRow(self.vision_every_step)
        note = QLabel("The agent never types passwords or card numbers; it asks you to enter them yourself.")
        note.setObjectName("muted")
        f.addRow(note)
        return w

    def _accept(self):
        bad = self.connection.problem()
        if bad:
            QMessageBox.warning(self, "Connection", bad)
            return
        if self.custom_price.isChecked():
            try:
                values = [float(self.price_input.text()), float(self.price_output.text())]
                if self.price_cache.text().strip():
                    values.append(float(self.price_cache.text()))
                if not all(0 <= value < 1e9 for value in values):
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "Invalid price", "Enter nonnegative USD rates per million tokens.")
                return
        self._commit()
        ov = dict(self.store.get("overrides") or {})
        custom = list(self.store.get("custom") or [])
        presets = {p.id: p for p in providers.PRESETS}
        for pid in set(self.pending_models) | set(self.pending_urls):
            model, url = self.pending_models.get(pid, ""), self.pending_urls.get(pid, "")
            if pid in presets:
                entry = ov.setdefault(pid, {})
                if model and model != presets[pid].model:
                    entry["model"] = model
                else:
                    entry.pop("model", None)
                if url and url != presets[pid].base_url:
                    entry["base_url"] = url
                else:
                    entry.pop("base_url", None)
            else:
                for c in custom:
                    if c["id"] == pid:
                        c["model"] = model or c.get("model", "")
                        c["base_url"] = url or c.get("base_url", "")
        self.store.set("overrides", ov)
        self.store.set("custom", custom)
        try:
            for pid, key in self.pending_keys.items():
                self.store.set_key(pid, key)
            for pid in self.removed_keys:
                if pid not in self.pending_keys:
                    self.store.set_key(pid, "")
        except secretbox.KeyringMissing as e:   # Linux without a usable keyring: say so rather than save in the clear
            QMessageBox.warning(self, "API keys not saved", str(e))
        self.store.set("save_passwords", self.offer_passwords.isChecked())
        self.store.set("autofill", self.offer_autofill.isChecked())
        self.store.set("safe_browsing", self.safe_browsing.isChecked())
        self.store.set("search_engine", self.engine.currentData())
        self.store.set("autocomplete", self.autocomplete.isChecked())
        self.store.set("tab_sleep", self.tab_sleep.isChecked())
        self.store.set("tab_sleep_minutes", self.sleep_minutes.value())
        self.store.set("tab_previews", self.tab_previews.isChecked())
        self.store.set("vertical_tabs", self.vertical_tabs.isChecked())
        self.store.set("spellcheck", self.spellcheck.isChecked())
        self.store.set("spellcheck_lang", self.spell_lang.currentData())
        self.store.set("home", self.home.text().strip() or "atlas:start")
        self.homepage.save()
        if self.connection.save():
            QMessageBox.information(self, "Connection", "The new proxy setting takes effect when you restart Pelagic.")
        self.store.set("memory_file", self.memory_path.text().strip())
        self.store.set("max_steps", self.steps.value())
        self.store.set("guard", self.guard.isChecked())
        self.store.set("confirm_all", self.confirm_all.isChecked())
        self.store.set("vision", self.vision.isChecked())
        self.store.set("vision_every_step", self.vision_every_step.isChecked())
        self.store.set("humanize", self.humanize.isChecked())
        self.store.set("batch", self.batch.isChecked())
        self.store.set("token_saver", self.token_saver.isChecked())
        self.store.set("price_overrides", self.pending_prices)
        cache = dict(self.store.get("model_cache") or {})
        cache.update(self.model_lists)
        self.store.set("model_cache", cache)
        self.accept()


class UsageDialog(QDialog):
    """Session totals by provider plus the most recent tasks from usage.log."""

    def __init__(self, session, log, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Token usage")
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        head = QLabel("<b>This session</b><br>" + html.escape(session.summary())
                      + ("<br>" + "<br>".join(f"{html.escape(pid)}: {c} calls, {i:,} in / {o:,} out"
                                              for pid, (c, i, o) in sorted(session.by.items())) if session.by else ""))
        head.setTextFormat(Qt.RichText)
        lay.addWidget(head)
        from .usage import format_cost
        lay.addWidget(QLabel("Saved total so far: " + format_cost(log.totals())))
        lay.addWidget(QLabel("Recent tasks (newest first; ~ means estimated because the provider reported no usage):"))
        lst = QListWidget()
        for e in log.recent(200):
            approx = "~" if e.get("estimated") else ""
            lst.addItem(f"{e['time']}  [{e['mode']}/{e.get('status', '')}]  {approx}{e['in'] + e['out']:,} tokens "
                        f"({e['calls']} calls, {e['in']:,} in / {e['out']:,} out)  {e.get('model', '')} "
                        f"· {log.cost_summary(e)}\n    {e['task']}")
        if not lst.count():
            lst.addItem("No tasks logged yet.")
        lay.addWidget(lst, 1)
        lay.addWidget(QLabel(f"Log file: {log.path}"))
