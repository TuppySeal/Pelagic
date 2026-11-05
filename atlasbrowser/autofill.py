"""Addresses and payment cards: saved encrypted (like passwords), offered when a form field is focused, and
offered for saving after a form is sent.

Like passwords, saved entries stay on the Python side until the user picks one to fill. Security codes (CVC) are
never saved, the AI agent never sees card fields (see pagejs) and the fill menu never opens while the agent is
working. Settings: "autofill" (offer to save and fill; on by default).
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QMenu

from .secretbox import protect, unprotect

ADDRESS_FIELDS = ("name", "organization", "street", "street2", "city", "state", "postal", "country", "tel", "email")
CARD_FIELDS = ("cc_name", "cc_number", "cc_month", "cc_year", "nickname")


# ---------------------------------------------------------------- cards
def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def luhn_ok(number: str) -> bool:
    d = digits(number)
    if not 12 <= len(d) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def card_brand(number: str) -> str:
    d = digits(number)
    if d.startswith("4"):
        return "Visa"
    if re.match(r"5[1-5]|2[2-7]", d):
        return "Mastercard"
    if re.match(r"3[47]", d):
        return "Amex"
    if re.match(r"6(011|5|4[4-9])", d):
        return "Discover"
    return "Card"


def card_label(card: dict) -> str:
    """'Visa •••• 4242' (the nickname instead of the brand when there is one)."""
    return f"{card.get('nickname') or card_brand(card.get('cc_number', ''))} •••• {digits(card.get('cc_number', ''))[-4:]}"


def address_label(a: dict) -> str:
    bits = [a.get("name"), a.get("street"), a.get("city")]
    return ", ".join(b for b in bits if b) or a.get("email") or "(address)"


class AutofillStore:
    """{"addresses": [...], "cards": [...]} in autofill.dat, encrypted (DPAPI on Windows, the system keyring elsewhere)."""

    def __init__(self, root: Path):
        self.path = Path(root) / "autofill.dat"
        self._lock = threading.RLock()
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            self._data = {"addresses": [], "cards": []}
            try:
                raw = base64.b64decode(self.path.read_text())
                plain = unprotect(raw)
                self._data.update(json.loads(plain.decode("utf-8")))
            except FileNotFoundError:
                pass
            except Exception:
                self._data["unreadable"] = True     # never overwrite a file we couldn't read
        return self._data

    def _save(self):
        data = self._load()
        if data.get("unreadable"):
            raise RuntimeError("The saved addresses and cards file could not be decrypted, so it was left untouched.")
        plain = json.dumps({"addresses": data["addresses"], "cards": data["cards"]}).encode("utf-8")
        raw = protect(plain)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(base64.b64encode(raw).decode("ascii"))
        os.replace(tmp, self.path)

    def items(self, kind: str) -> list[dict]:
        """kind is 'addresses' or 'cards'; most recently used first."""
        with self._lock:
            return sorted((dict(x) for x in self._load()[kind]), key=lambda x: -x.get("last_used", 0))

    def get(self, kind: str, item_id: str) -> dict | None:
        return next((x for x in self.items(kind) if x["id"] == item_id), None)

    def save(self, kind: str, fields: dict, item_id: str | None = None) -> dict:
        allowed = ADDRESS_FIELDS if kind == "addresses" else CARD_FIELDS
        clean = {k: str(fields.get(k, "") or "").strip() for k in allowed}
        if kind == "cards":
            clean["cc_number"] = digits(clean["cc_number"])
        with self._lock:
            items = self._load()[kind]
            old = next((x for x in items if x["id"] == item_id), None) if item_id else None
            if old is None:     # (a given id that isn't here yet is kept: sync brings items with their ids)
                old = {"id": item_id or uuid.uuid4().hex, "created": time.time(), "last_used": 0}
                items.append(old)
            old.update(clean)
            old["updated"] = time.time()
            self._save()
            return dict(old)

    def delete(self, kind: str, item_id: str):
        with self._lock:
            data = self._load()
            data[kind] = [x for x in data[kind] if x["id"] != item_id]
            self._save()

    def touch(self, kind: str, item_id: str):
        with self._lock:
            for x in self._load()[kind]:
                if x["id"] == item_id:
                    x["last_used"] = time.time()
                    self._save()
                    return

    def known(self, kind: str, fields: dict) -> bool:
        """Already saved (same card number, or same street and postal code)?"""
        if kind == "cards":
            n = digits(fields.get("cc_number", ""))
            return any(x.get("cc_number") == n for x in self.items(kind))
        key = lambda a: (a.get("street", "").strip().lower(), digits(a.get("postal", "")) or a.get("postal", "").lower())
        return any(key(x) == key(fields) for x in self.items(kind))


# ---------------------------------------------------------------- page side
# Runs in the same isolated world as the password script and reaches Python through its channel (window.__wfBridge).
PAGE_JS = r"""
(function () {
  if (window.__pfAf) return;
  window.__pfAf = true;
  var AC = { 'name': 'name', 'given-name': 'given', 'family-name': 'family', 'organization': 'organization',
    'street-address': 'street', 'address-line1': 'street', 'address-line2': 'street2', 'address-level2': 'city',
    'address-level1': 'state', 'postal-code': 'postal', 'country': 'country', 'country-name': 'country',
    'tel': 'tel', 'tel-national': 'tel', 'email': 'email', 'cc-name': 'cc_name', 'cc-number': 'cc_number',
    'cc-exp': 'cc_exp', 'cc-exp-month': 'cc_month', 'cc-exp-year': 'cc_year', 'cc-csc': 'cc_csc' };
  var RULES = [
    [/cvc|cvv|csc|security.?code|card.?code|verification/, 'cc_csc'],
    [/card.?num|cc.?num|cardnumber|credit.?card|ccnum|card.?no\b/, 'cc_number'],
    [/name.?on.?card|card.?holder|cc.?name|cardname/, 'cc_name'],
    [/exp\w*.?month|cc.?mo|card.?month/, 'cc_month'],
    [/exp\w*.?year|cc.?y|card.?year/, 'cc_year'],
    [/expir|exp.?date|mm.?\/?.?yy/, 'cc_exp'],
    [/e.?mail/, 'email'],
    [/phone|mobile|\btel\b|telephone/, 'tel'],
    [/zip|postal|post.?code|postcode/, 'postal'],
    [/city|town|locality|suburb/, 'city'],
    [/state|province|region|county/, 'state'],
    [/country/, 'country'],
    [/address.?(line)?.?2|apt|apartment|suite|unit\b|flat/, 'street2'],
    [/address|street|addr/, 'street'],
    [/company|organi[sz]ation|business/, 'organization'],
    [/first.?name|given.?name|fname|forename/, 'given'],
    [/last.?name|surname|family.?name|lname/, 'family'],
    [/full.?name|^name$|your.?name|\bname\b/, 'name']
  ];
  function visible(el) { var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.disabled && !el.readOnly; }
  function kindOf(el) {
    if (!el || !/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return '';
    var t = (el.type || 'text').toLowerCase();
    if (/^(password|hidden|checkbox|radio|submit|button|file|image|search|date|number|range|color)$/.test(t) && !(t === 'number' && /cc|card/i.test(el.name + el.id))) return '';
    var ac = (el.getAttribute('autocomplete') || '').toLowerCase().trim().split(/\s+/).pop();
    if (ac === 'off' || ac === 'one-time-code' || ac === 'username' || ac === 'new-password' || ac === 'current-password') ac = '';
    if (AC[ac]) return AC[ac];
    if (t === 'email') return 'email';
    if (t === 'tel') return 'tel';
    var label = (el.labels && el.labels[0]) ? el.labels[0].innerText : '';
    var hay = [el.name, el.id, el.placeholder, el.getAttribute('aria-label'), label].join(' ').toLowerCase();
    for (var i = 0; i < RULES.length; i++) if (RULES[i][0].test(hay)) return RULES[i][1];
    return '';
  }
  function section(k) { return k.indexOf('cc_') === 0 ? 'card' : 'address'; }
  function scope(el) { return (el && el.form) || document; }
  function hasPassword(root) { return !!root.querySelector('input[type=password]'); }
  function fieldsIn(root, sec) {
    return Array.prototype.slice.call(root.querySelectorAll('input, select, textarea')).filter(function (el) {
      var k = kindOf(el); return k && visible(el) && section(k) === sec;
    });
  }
  function setValue(el, v) {
    if (el.tagName === 'SELECT') {
      var want = String(v).toLowerCase(), best = -1;
      for (var i = 0; i < el.options.length; i++) {
        var o = el.options[i], ov = o.value.toLowerCase(), ot = o.text.trim().toLowerCase();
        if (ov === want || ot === want) { best = i; break; }
        if (best < 0 && want.length > 2 && (ot.indexOf(want) === 0 || want.indexOf(ot) === 0) && ot.length > 1) best = i;
        if (best < 0 && /^\d+$/.test(want) && /^\d+$/.test(ov) && +ov === +want) best = i;
      }
      if (best < 0) return;
      el.selectedIndex = best;
    } else {
      var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function valueFor(el, k, d) {
    var parts = (d.name || '').trim().split(/\s+/);
    var yy = (d.cc_year || '').slice(-2), mm = ('0' + (d.cc_month || '')).slice(-2);
    switch (k) {
      case 'given': return parts.length > 1 ? parts.slice(0, -1).join(' ') : (d.name || '');
      case 'family': return parts.length > 1 ? parts[parts.length - 1] : '';
      case 'cc_month': return el.tagName === 'SELECT' ? String(+d.cc_month || '') : mm;
      case 'cc_year':
        if (el.tagName === 'SELECT') return d.cc_year || '';
        return (el.maxLength > 0 && el.maxLength <= 2) || /yy(?!yy)/i.test(el.placeholder || '') ? yy : (d.cc_year || '');
      case 'cc_exp': return d.cc_month ? mm + '/' + ((el.maxLength > 0 && el.maxLength < 7) || !/yyyy/i.test(el.placeholder || '') ? yy : d.cc_year) : '';
      case 'cc_csc': return '';
      default: return d[k] || '';
    }
  }
  window.__pfFill = function (sec, d) {
    var a = document.activeElement, root = scope(kindOf(a) ? a : null);
    fieldsIn(root, sec).forEach(function (el) {
      var v = valueFor(el, kindOf(el), d);
      if (v && !(el.value && el !== a && el.tagName !== 'SELECT')) setValue(el, v);
    });
  };
  function collect(root) {
    var out = {};
    ['address', 'card'].forEach(function (sec) {
      fieldsIn(root, sec).forEach(function (el) {
        var k = kindOf(el), v = el.tagName === 'SELECT' ? (el.selectedOptions[0] ? el.selectedOptions[0].text : '') : el.value;
        if (k === 'cc_csc' || !v || !v.trim()) return;
        if (el.tagName === 'SELECT' && /^(cc_month|cc_year)$/.test(k)) v = el.value;
        if (!out[k]) out[k] = v.trim();
      });
    });
    return out;
  }
  var lastSent = '';
  function sent(root) {
    var b = window.__wfBridge;
    if (!b || !root || hasPassword(root)) return;
    var data = collect(root), key = JSON.stringify(data);
    if (key === '{}' || key === lastSent) return;
    lastSent = key;
    b.autofillSubmitted(key);
  }
  document.addEventListener('focusin', function (e) {
    var el = e.target, b = window.__wfBridge, k = kindOf(el);
    if (!b || !e.isTrusted || !k || k === 'cc_csc' || hasPassword(scope(el))) return;
    var r = el.getBoundingClientRect();
    b.autofillFocused(r.left, r.bottom, section(k));
  }, true);
  document.addEventListener('submit', function (e) { sent(e.target); }, true);
  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest && e.target.closest('button, input[type=submit]');
    if (btn && btn.form && (btn.type || 'submit').toLowerCase() === 'submit') sent(btn.form);
  }, true);
})();
"""


def _from_page(data: dict) -> tuple[dict, dict]:
    """The page's collected fields -> (address, card), each in the store's shape."""
    name = data.get("name") or " ".join(x for x in (data.get("given"), data.get("family")) if x)
    address = {"name": name, "organization": data.get("organization", ""), "street": data.get("street", ""),
               "street2": data.get("street2", ""), "city": data.get("city", ""), "state": data.get("state", ""),
               "postal": data.get("postal", ""), "country": data.get("country", ""), "tel": data.get("tel", ""),
               "email": data.get("email", "")}
    month, year = data.get("cc_month", ""), data.get("cc_year", "")
    m = re.match(r"\s*(\d{1,2})\s*[/\-. ]\s*(\d{2,4})", data.get("cc_exp", ""))
    if m:
        month, year = m.group(1), m.group(2)
    year = digits(year)
    if len(year) == 2:
        year = "20" + year
    card = {"cc_name": data.get("cc_name", ""), "cc_number": digits(data.get("cc_number", "")),
            "cc_month": str(int(digits(month))) if digits(month) else "", "cc_year": year}
    return address, card


class Autofill:
    """Shows the fill menu for address and card fields and offers to save what was typed."""

    def __init__(self, store: AutofillStore, settings):
        self.store, self.settings = store, settings

    def enabled(self) -> bool:
        return self.settings.get("autofill") is not False

    @staticmethod
    def _agent_busy(win) -> bool:
        agent = getattr(getattr(win, "panel", None), "agent", None)
        return bool(agent and agent.running and not agent.waiting_for_user)

    def field_focused(self, tab, x, y, section: str):
        win = getattr(tab, "_pw_win", None)
        if win is None or not self.enabled() or self._agent_busy(win) or win.current_tab() is not tab:
            return
        kind = "cards" if section == "card" else "addresses"
        items = self.store.items(kind)
        if not items:
            return
        menu = QMenu(tab)
        for it in items[:6]:
            label = card_label(it) if kind == "cards" else address_label(it)
            if kind == "cards" and it.get("cc_month"):
                label += f"   ·  expires {int(it['cc_month']):02d}/{it.get('cc_year', '')[-2:]}"
            menu.addAction(label).triggered.connect(lambda _=False, i=it["id"]: self.fill(tab, kind, i))
        menu.addSeparator()
        menu.addAction("Manage addresses and cards…").triggered.connect(lambda: win.show_autofill())
        z = tab.zoomFactor()
        menu.popup(tab.mapToGlobal(QPoint(round(x * z), round(y * z) + 2)))

    def fill(self, tab, kind: str, item_id: str):
        it = self.store.get(kind, item_id)
        if not it:
            return
        section = "card" if kind == "cards" else "address"
        tab.run_js(f"window.__pfFill && window.__pfFill({json.dumps(section)}, {json.dumps(it)})")
        self.store.touch(kind, item_id)

    def submitted(self, tab, payload: str):
        win = getattr(tab, "_pw_win", None)
        if win is None or not self.enabled() or tab.private or self._agent_busy(win):
            return
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        address, card = _from_page({k: str(v) for k, v in data.items()})
        offers = []
        if luhn_ok(card["cc_number"]) and not self.store.known("cards", card):
            offers.append(("cards", card, f"Save card <b>{_esc(card_label(card))}</b> for next time? "
                                          "(The security code is never saved.)"))
        if address["street"] and (address["city"] or address["postal"]) and not self.store.known("addresses", address):
            offers.append(("addresses", address, f"Save address <b>{_esc(address_label(address))}</b>?"))
        if not offers:
            return
        kind, fields, text = offers[0]

        def save():
            self.store.save(kind, fields)
            if len(offers) > 1:     # card and address in one form: ask about the address next
                k2, f2, t2 = offers[1]
                win.save_bar.offer_custom(t2, "Save", lambda: self.store.save(k2, f2))
        QTimer.singleShot(600, lambda: win.save_bar.offer_custom(text, "Save", save) if tab in win.tab_list() else None)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
