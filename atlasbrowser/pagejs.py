"""JavaScript snippets the agent runs inside pages (isolated world, so page scripts can't see them)."""
import json

# Preserve paragraph boundaries and repetition counts while removing whitespace noise.
# Do not deduplicate interactive elements: each one must keep its own actionable id.
_NORMALIZE_TEXT = r"""
  const cleanText = (raw, limit) => {
    const lines = String(raw || '').replace(/\r/g, '').split('\n')
      .map(s => s.replace(/[ \t]+/g, ' ').trim()).filter(Boolean);
    const out = [];
    for (let i = 0; i < lines.length;) {
      let end = i + 1;
      while (end < lines.length && lines[end] === lines[i]) end++;
      out.push(lines[i] + (end - i > 1 ? ' [repeated x' + (end - i) + ']' : ''));
      i = end;
    }
    const text = out.join('\n');
    return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
  };
"""

# Secret fields: real password boxes, password boxes switched to plain text by a "show password" eye (remembered
# from an earlier look, and caught by their names), and fields for one-time codes, PINs and keys. The agent never
# sees their values, never types into them, and they are blacked out in its screenshots.
_SECRET = r"""
  const __pw = window.__atlasPw || (window.__atlasPw = new WeakSet());
  const __SECRET_NAME = /passw|passwd|passphrase|passcode|pwd|(^|[^a-z])(pass|pin|otp|totp|mfa|2fa|cvv|cvc)([^a-z]|$)|one.?time|verification.?code|security.?code|auth(entication)?.?code|secret|api.?key|access.?token/i;
  const isSecret = (el) => {
    if (!el || !el.tagName) return false;
    const tag = el.tagName.toLowerCase();
    if (tag !== 'input' && tag !== 'textarea') return false;
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'password') { __pw.add(el); return true; }
    if (__pw.has(el)) return true;
    if (['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type)) return false;
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    if (/current-password|new-password|one-time-code/.test(ac)) return true;
    return __SECRET_NAME.test([el.name, el.id, el.getAttribute('aria-label'), el.placeholder].join(' '));
  };
"""

# Checkboxes, radios and switches: what they are called, whether they are on, and what to click.
# Many sites hide the real <input> (opacity 0, 1px, display:none) and draw a styled <label> instead, so the
# label stands in for it. Without this the agent saw "on"/no state/nothing at all and concluded its click failed.
_CHECKABLE = r"""
  const __CHECK_ROLES = ['checkbox', 'radio', 'switch', 'menuitemcheckbox', 'menuitemradio'];
  const isCheckable = (el) => {
    if (!el || !el.tagName) return false;
    if (el.tagName.toLowerCase() === 'input') return ['checkbox', 'radio'].includes((el.type || '').toLowerCase());
    return __CHECK_ROLES.includes((el.getAttribute('role') || '').toLowerCase());
  };
  const checkState = (el) => {
    if (!isCheckable(el)) return null;
    if (el.tagName.toLowerCase() === 'input') return el.indeterminate ? 'mixed' : !!el.checked;
    const a = (el.getAttribute('aria-checked') || '').toLowerCase();
    if (a === 'mixed') return 'mixed';
    if (a === 'true') return true;
    const inner = el.querySelector('input[type=checkbox],input[type=radio]');
    return inner ? !!inner.checked : false;
  };
  const __txt = (n) => n ? (n.innerText || n.textContent || '').replace(/\s+/g, ' ').trim() : '';
  // The words a person reads next to a form control: aria-labelledby, <label for>, wrapping <label>.
  const controlLabel = (el) => {
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map(id => __txt(document.getElementById(id))).filter(Boolean).join(' ');
      if (t) return t;
    }
    for (const l of Array.from(el.labels || [])) { const t = __txt(l); if (t) return t; }
    const wrap = el.closest && el.closest('label');
    return wrap ? __txt(wrap) : '';
  };
  const __shown = (n) => {
    const r = n.getBoundingClientRect(), cs = getComputedStyle(n);
    return r.width >= 2 && r.height >= 2 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) !== 0;
  };
  // A hidden native checkbox/radio is toggled through its visible label (or the styled box around it).
  const clickProxy = (el) => {
    if (!el || el.tagName.toLowerCase() !== 'input' || !isCheckable(el) || __shown(el)) return null;
    const cands = Array.from(el.labels || []);
    const wrap = el.closest('label'); if (wrap) cands.push(wrap);
    if (el.parentElement && !cands.length) cands.push(el.parentElement);
    return cands.find(__shown) || null;
  };
"""

SNAPSHOT = r"""
(() => {
@@NORMALIZE_TEXT@@
@@SECRET@@
@@CHECKABLE@@
  const vh = window.innerHeight, vw = window.innerWidth, MAX = 80;
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],' +
    '[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],' +
    '[role=textbox],[onclick],[contenteditable=""],[contenteditable=true],[tabindex]:not([tabindex="-1"])';
  const found = [];
  const collect = root => {
    root.querySelectorAll(sel).forEach(e => found.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) collect(e.shadowRoot); });
  };
  collect(document);
  const seen = new Set(), refs = [], items = [], masks = [], proxies = [];
  const clip = (s, n) => { s = (s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  // card fields (and anything that looks like a card number) are never shown to the agent
  const isCard = (el) => /^cc-/.test((el.getAttribute('autocomplete') || '').toLowerCase().trim().split(/\s+/).pop() || '') ||
    /card.?num|cc.?num|cardnumber|cvc|cvv|csc|security.?code/i.test((el.name || '') + ' ' + (el.id || '')) ||
    /^[\d\s-]{13,23}$/.test(el.value || '') && (el.value.match(/\d/g) || []).length >= 13;
  for (const el of found) {
    if (seen.has(el) || items.length >= MAX) continue;
    seen.add(el);
    const proxy = clickProxy(el);
    if (proxy) seen.add(proxy);
    const box = proxy || el;
    const r = box.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom < -vh * 0.2 || r.top > vh * 1.6 || r.right < 0 || r.left > vw) continue;
    const cs = getComputedStyle(box);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : tag === 'button' ? 'button' : '')).toLowerCase();
    const formy = tag === 'input' || tag === 'select' || tag === 'textarea' || isCheckable(el);
    // A checkbox's value is usually just "on": never use it as the name.
    const value = isCheckable(el) ? '' : el.value;
    let label = el.getAttribute('aria-label') || (formy ? controlLabel(el) : '') || el.innerText || value ||
      el.placeholder || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('name') || el.value || '';
    if (!label) { const img = el.querySelector('img[alt]'); if (img) label = img.alt; }
    const secret = isSecret(el);
    if (secret) label = el.getAttribute('aria-label') || el.placeholder || el.name || 'password';
    else if ((tag === 'input' || tag === 'textarea') && isCard(el)) label = el.getAttribute('aria-label') || el.placeholder || el.name || 'card field';
    const it = { i: refs.length, tag: tag + (type ? ':' + type : ''), text: clip(label, 60),
                 inView: r.top >= 0 && r.bottom <= vh };
    if (tag === 'a' && el.href) it.href = clip(el.href.replace(location.origin, ''), 50);
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role && isCheckable(el)) it.tag += '[' + role + ']';
    if (isCheckable(el)) it.checked = checkState(el);
    else if (el.hasAttribute('aria-pressed')) it.pressed = el.getAttribute('aria-pressed') === 'true';
    if (['tab', 'option'].includes(role) && el.hasAttribute('aria-selected')) it.selected = el.getAttribute('aria-selected') === 'true';
    if (tag === 'input' || tag === 'textarea') {
      if (type === 'checkbox' || type === 'radio') { /* state is reported above */ }
      else if (secret) it.secret = true;   // its value is never read
      else it.value = isCard(el) ? (el.value ? '(card detail, hidden)' : '') : clip(el.value, 40);
      if (el.placeholder) it.placeholder = clip(el.placeholder, 40);
    }
    if (tag === 'select') {
      it.options = Array.from(el.options).slice(0, 10).map(o => clip(o.text, 24));
      it.value = clip(el.selectedOptions[0] ? el.selectedOptions[0].text : '', 30);
    }
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') it.disabled = true;
    if (secret && type !== 'password' && (el.value || '') && r.bottom > 0 && r.top < vh) masks.push([r.left, r.top, r.width, r.height]);
    refs.push(el); items.push(it); proxies.push(proxy);
  }
  window.__atlasRefs = refs;
  window.__atlasProxies = proxies;
  window.__atlasLabels = items.map(it => ({ t: (it.text || '').toLowerCase(),
    all: ((it.text || '') + ' ' + (it.placeholder || '') + ' ' + (it.href || '')).toLowerCase() }));
  const visual = Array.from(document.querySelectorAll('canvas,video,svg,img,object,embed')).some(el => {
    const r = el.getBoundingClientRect(), tag = el.tagName.toLowerCase();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0 ||
        r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) return false;
    // Keep vision on charts, viewers and large pictures; ordinary icons do not need an image.
    return r.width >= (tag === 'canvas' || tag === 'video' ? 80 : 240) &&
           r.height >= (tag === 'canvas' || tag === 'video' ? 80 : 160);
  });
  const de = document.documentElement;
  return JSON.stringify({
    url: location.href, title: document.title, ready: document.readyState, scrollY: Math.round(window.scrollY),
    scrollMax: Math.max(0, Math.round(de.scrollHeight - vh)), vh: vh, vw: vw,
    items: items, visual: visual, masks: masks,
    text: cleanText(document.body ? document.body.innerText : '', 2500)
  });
})()
""".replace("@@NORMALIZE_TEXT@@", _NORMALIZE_TEXT).replace("@@SECRET@@", _SECRET).replace("@@CHECKABLE@@", _CHECKABLE)

FULL_TEXT = r"""
(() => {
@@NORMALIZE_TEXT@@
  return JSON.stringify({ url: location.href, title: document.title,
    text: cleanText(document.body ? document.body.innerText : '', 15000) });
})()
""".replace("@@NORMALIZE_TEXT@@", _NORMALIZE_TEXT)

SELECTION_AND_TEXT = r"""
(() => {
@@NORMALIZE_TEXT@@
  return JSON.stringify({ url: location.href, title: document.title,
    selection: String(window.getSelection() || ''),
    text: cleanText(document.body ? document.body.innerText : '', 8000) });
})()
""".replace("@@NORMALIZE_TEXT@@", _NORMALIZE_TEXT)

PREPARE_CLICK = r"""
((i) => {
@@CHECKABLE@@
  const el = window.__atlasRefs && window.__atlasRefs[i];
  if (!el || !el.isConnected) return JSON.stringify({ ok: false, err: 'Element ' + i + ' is gone or the page changed; use the latest element list.' });
  const stored = window.__atlasProxies && window.__atlasProxies[i];
  const box = (stored && stored.isConnected ? stored : null) || clickProxy(el) || el;
  box.scrollIntoView({ block: 'center', inline: 'center' });
  const r = box.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  let hit = document.elementFromPoint(x, y);
  while (hit && hit.shadowRoot) { const h2 = hit.shadowRoot.elementFromPoint(x, y); if (!h2 || h2 === hit) break; hit = h2; }
  const related = (n) => !!hit && !!n && (n === hit || n.contains(hit) || hit.contains(n));
  // A hit on the checkbox's own label toggles it too.
  const good = related(box) || related(el) || (isCheckable(el) && Array.from(el.labels || []).some(related));
  const checkable = isCheckable(el);
  const label = ((checkable ? el.getAttribute('aria-label') || controlLabel(el) : '') || el.getAttribute('aria-label') ||
    el.innerText || (checkable ? '' : el.value) || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const kind = el.tagName.toLowerCase() + ((el.getAttribute('type') || '') ? ':' + el.getAttribute('type') : '');
  window.__atlasLastTarget = el;
  return JSON.stringify({ ok: true, x: x, y: y, good: good, label: label, kind: kind,
                          checkable: checkable, before: checkState(el) });
})(%s)
""".replace("@@CHECKABLE@@", _CHECKABLE)

PREPARE_COORDINATE_CLICK = r"""
((x, y) => {
@@CHECKABLE@@
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight)
    return JSON.stringify({ok: false, err: 'Coordinates are outside the current page viewport.'});
  let hit = document.elementFromPoint(x, y);
  while (hit && hit.shadowRoot) {
    const next = hit.shadowRoot.elementFromPoint(x, y);
    if (!next || next === hit) break;
    hit = next;
  }
  if (!hit) return JSON.stringify({ok: false, err: 'No visible content at these coordinates.'});
  const el = hit.closest('button,a,input,select,[role=button],[role=link]') || hit;
  if (el.disabled) return JSON.stringify({ok: false, err: 'This control is disabled.'});
  // The checkbox/radio this point toggles: itself, an ARIA one around it, or the control of the label it is in.
  let ctl = hit.closest('input[type=checkbox],input[type=radio],[role=checkbox],[role=radio],[role=switch],' +
                        '[role=menuitemcheckbox],[role=menuitemradio]');
  if (!ctl) { const lab = hit.closest('label'); if (lab && isCheckable(lab.control)) ctl = lab.control; }
  const checkable = isCheckable(ctl);
  const label = ((checkable ? ctl.getAttribute('aria-label') || controlLabel(ctl) : '') || el.getAttribute('aria-label') ||
    el.innerText || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const kind = checkable ? ctl.tagName.toLowerCase() + (ctl.type ? ':' + ctl.type : '') : el.tagName.toLowerCase();
  window.__atlasLastTarget = checkable ? ctl : null;
  return JSON.stringify({ok: true, x, y, good: true, label, kind, checkable, before: checkable ? checkState(ctl) : null});
})(%s)
""".replace("@@CHECKABLE@@", _CHECKABLE)

# After a click: is the checkbox/radio/switch the click was aimed at on now?
CHECK_STATE = r"""
(() => {
@@CHECKABLE@@
  const el = window.__atlasLastTarget;
  if (!el || !el.isConnected) return JSON.stringify({ ok: false });
  return JSON.stringify({ ok: true, state: checkState(el), radio: (el.type || el.getAttribute('role') || '').toLowerCase().includes('radio') });
})()
""".replace("@@CHECKABLE@@", _CHECKABLE)

# The real click did not toggle it: click the control itself (fires the page's normal click/change handlers).
TOGGLE_LAST = r"""
(() => { const el = window.__atlasLastTarget; if (!el || !el.isConnected) return 'gone'; el.click(); return 'ok'; })()
"""

# Resolve a visible label ("Email", "Sign in") to an element index, so a plan survives id changes.
RESOLVE_TARGET = r"""
((want) => {
  want = String(want).toLowerCase().trim();
  const L = window.__atlasLabels || [];
  let i = L.findIndex(l => l.t === want);
  if (i < 0) i = L.findIndex(l => l.t.startsWith(want));
  if (i < 0) i = L.findIndex(l => l.all.includes(want));
  return i;
})(%s)
"""

FALLBACK_CLICK = r"""
((i) => { const el = window.__atlasRefs && window.__atlasRefs[i]; if (!el) return 'gone'; el.click(); return 'ok'; })(%s)
"""

TYPE_TEXT = r"""
((i, text, clear) => {
@@SECRET@@
  const el = window.__atlasRefs && window.__atlasRefs[i];
  if (!el || !el.isConnected) return JSON.stringify({ ok: false, err: 'Element ' + i + ' is gone or the page changed.' });
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
  if (isSecret(el)) return JSON.stringify({ ok: false, err: 'password' });
  el.scrollIntoView({ block: 'center' });
  el.focus();
  if (el.isContentEditable) {
    if (clear) document.execCommand('selectAll');
    document.execCommand('insertText', false, text);
    return JSON.stringify({ ok: true });
  }
  if (tag !== 'input' && tag !== 'textarea') return JSON.stringify({ ok: false, err: 'Element ' + i + ' is not a text field.' });
  if (['checkbox', 'radio', 'button', 'submit', 'file', 'image', 'reset', 'range', 'color'].includes(type))
    return JSON.stringify({ ok: false, err: 'Element ' + i + ' (' + type + ') cannot be typed into.' });
  const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, clear ? text : el.value + text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return JSON.stringify({ ok: true });
})(%s)
""".replace("@@SECRET@@", _SECRET)

SELECT_OPTION = r"""
((i, want) => {
  const el = window.__atlasRefs && window.__atlasRefs[i];
  if (!el || !el.isConnected) return JSON.stringify({ ok: false, err: 'Element ' + i + ' is gone or the page changed.' });
  if (el.tagName.toLowerCase() !== 'select') return JSON.stringify({ ok: false, err: 'Element ' + i + ' is not a dropdown.' });
  const w = String(want).trim().toLowerCase();
  const opt = Array.from(el.options).find(o => o.text.trim().toLowerCase() === w || o.value.toLowerCase() === w) ||
              Array.from(el.options).find(o => o.text.toLowerCase().includes(w));
  if (!opt) return JSON.stringify({ ok: false, err: 'No option matching "' + want + '".' });
  el.value = opt.value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return JSON.stringify({ ok: true, chosen: opt.text.trim() });
})(%s)
"""

SCROLL = r"""
((dir, pages) => {
  const dy = window.innerHeight * pages * (dir === 'up' ? -1 : 1);
  window.scrollBy({ top: dy, behavior: 'instant' });
  return JSON.stringify({ y: Math.round(window.scrollY), max: Math.max(0, Math.round(document.documentElement.scrollHeight - window.innerHeight)) });
})(%s)
"""

AGENT_BADGE = r"""
(() => {
  if (document.getElementById('__atlas_agent_glow')) return;
  const d = document.createElement('div');
  d.id = '__atlas_agent_glow';
  d.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;' +
    'box-shadow:inset 0 0 0 3px rgba(124,92,255,.85),inset 0 0 38px rgba(80,160,255,.45);' +
    'animation:__atlas_pulse 1.8s ease-in-out infinite;';
  const s = document.createElement('style');
  s.textContent = '@keyframes __atlas_pulse{0%,100%{opacity:.55}50%{opacity:1}}';
  (document.head || document.documentElement).appendChild(s);
  (document.body || document.documentElement).appendChild(d);
})()
"""

AGENT_BADGE_OFF = r"""
(() => {
  ['__atlas_agent_glow', '__atlas_cursor'].forEach(id => { const d = document.getElementById(id); if (d) d.remove(); });
  window.__atlasCur = null;
})()
"""

ELEMENT_RECT = r"""
((i) => {
@@SECRET@@
  const el = window.__atlasRefs && window.__atlasRefs[i];
  if (!el || !el.isConnected) return JSON.stringify({ ok: false, err: 'Element ' + i + ' is gone or the page changed.' });
  if (isSecret(el)) return JSON.stringify({ ok: false, err: 'password' });
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect();
  return JSON.stringify({ ok: true, x: r.left + Math.min(r.width / 2, 40 + Math.random() * 30), y: r.top + r.height / 2 });
})(%s)
""".replace("@@SECRET@@", _SECRET)

# Focus a field and empty it so real key presses can fill it letter by letter.
FOCUS_CLEAR = r"""
((i) => {
@@SECRET@@
  const el = window.__atlasRefs && window.__atlasRefs[i];
  if (!el || !el.isConnected) return JSON.stringify({ ok: false, err: 'Element ' + i + ' is gone or the page changed.' });
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || 'text').toLowerCase();
  if (isSecret(el)) return JSON.stringify({ ok: false, err: 'password' });
  el.focus();
  if (el.isContentEditable) { document.execCommand('selectAll'); document.execCommand('delete'); return JSON.stringify({ ok: true }); }
  if (tag !== 'input' && tag !== 'textarea')
    return JSON.stringify({ ok: false, err: 'Element ' + i + ' is not a text field.' });
  if (['checkbox', 'radio', 'button', 'submit', 'file', 'image', 'reset', 'range', 'color'].includes(type))
    return JSON.stringify({ ok: false, err: 'Element ' + i + ' (' + type + ') cannot be typed into.' });
  const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, '');
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return JSON.stringify({ ok: true });
})(%s)
""".replace("@@SECRET@@", _SECRET)

READ_VALUE = r"""
(() => {
@@SECRET@@
  const el = document.activeElement; if (!el || isSecret(el)) return ''; return el.isContentEditable ? el.innerText : (el.value || ''); })()
""".replace("@@SECRET@@", _SECRET)

INSERT_CHAR = r"""
((ch) => { const el = document.activeElement; if (!el) return false;
  if (el.isContentEditable) return document.execCommand('insertText', false, ch);
  const tag = el.tagName.toLowerCase();
  if (tag !== 'input' && tag !== 'textarea') return false;
  const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, el.value + ch);
  el.dispatchEvent(new Event('input', { bubbles: true })); return true; })(%s)
"""

# Which field has the keyboard in this frame (run in every frame): for typing into an editor without an id, such as
# a rich text box inside a frame. Secret and card fields are refused.
FOCUSED_FIELD = r"""
(() => { """ + _SECRET + r"""
  if (!document.hasFocus()) return JSON.stringify({ focus: false });
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el || el === document.body && !document.body.isContentEditable) return JSON.stringify({ focus: true, field: false });
  const tag = el.tagName.toLowerCase();
  if (tag === 'iframe' || tag === 'frame') return JSON.stringify({ focus: true, field: false, frame: true });
  const type = (el.getAttribute('type') || 'text').toLowerCase();
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase().trim().split(/\s+/).pop() || '';
  const card = /^cc-/.test(ac) || /card.?num|cc.?num|cardnumber|cvc|cvv|csc|security.?code/i.test((el.name || '') + ' ' + (el.id || ''));
  const field = el.isContentEditable || tag === 'textarea' ||
    (tag === 'input' && !['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type));
  return JSON.stringify({ focus: true, field: !!field, secret: isSecret(el), card: !!card,
    label: (el.getAttribute('aria-label') || el.placeholder || el.name || el.title || tag).slice(0, 60) });
})()
"""

# Formatted text into the focused field of this frame: a paste event first (rich editors handle it), then the
# browser's own insert commands, which keep undo and fire the page's input events.
PASTE_HTML = r"""
((html, plain) => {
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el) return JSON.stringify({ ok: false, err: 'Nothing has the keyboard.' });
  const tag = el.tagName.toLowerCase();
  const rich = el.isContentEditable;
  let handled = false;
  try {
    const dt = new DataTransfer();
    dt.setData('text/html', html);
    dt.setData('text/plain', plain);
    const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
    handled = !el.dispatchEvent(ev);
  } catch (e) {}
  if (handled) return JSON.stringify({ ok: true, how: 'editor' });
  if (rich) {
    const ok = document.execCommand('insertHTML', false, html);
    return JSON.stringify({ ok: !!ok, how: 'html', err: ok ? '' : 'The editor did not accept the text.' });
  }
  if (tag === 'input' || tag === 'textarea') {
    if (!document.execCommand('insertText', false, plain)) {
      const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const s = el.selectionStart ?? el.value.length, e = el.selectionEnd ?? el.value.length;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, el.value.slice(0, s) + plain + el.value.slice(e));
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    return JSON.stringify({ ok: true, how: 'text' });
  }
  return JSON.stringify({ ok: false, err: 'The focused element is not a text field.' });
})(%s)
"""

# Visible pointer that glides to the target before the agent clicks or types.
CURSOR_MOVE = r"""
((x, y, ms) => {
  let c = document.getElementById('__atlas_cursor');
  if (!c) {
    c = document.createElement('div');
    c.id = '__atlas_cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;' +
      'will-change:transform;filter:drop-shadow(0 2px 4px rgba(0,0,0,.55));';
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M3 2 L3 22 L8.5 17 L12 25 L15.5 23.5 L12 15.5 L19.5 15.5 Z" ' +
      'fill="#2FB3B4" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const p = window.__atlasCur || { x: innerWidth * 0.5, y: innerHeight * 0.4 };
    c.style.transform = 'translate(' + p.x + 'px,' + p.y + 'px)';
    (document.body || document.documentElement).appendChild(c);
    c.getBoundingClientRect();
  }
  c.style.transition = 'transform ' + ms + 'ms cubic-bezier(.22,.8,.3,1)';
  c.style.transform = 'translate(' + x + 'px,' + y + 'px)';
  window.__atlasCur = { x: x, y: y };
  return true;
})(%s)
"""

CURSOR_CLICK = r"""
(() => {
  const p = window.__atlasCur; if (!p) return false;
  const r = document.createElement('div');
  r.style.cssText = 'position:fixed;left:' + (p.x - 16) + 'px;top:' + (p.y - 16) + 'px;width:32px;height:32px;border-radius:50%;' +
    'border:3px solid #2FB3B4;z-index:2147483646;pointer-events:none;opacity:.9;transition:transform .45s ease-out,opacity .45s ease-out;';
  (document.body || document.documentElement).appendChild(r);
  r.getBoundingClientRect();
  r.style.transform = 'scale(2.2)'; r.style.opacity = '0';
  setTimeout(() => r.remove(), 520);
  return true;
})()
"""


# A visible CAPTCHA challenge on the page (reCAPTCHA/hCaptcha/Turnstile widgets, Cloudflare/Google interstitials).
# Invisible reCAPTCHA v3 badges don't count. Returns the kind, or "".
CAPTCHA = r"""
(function () {
  function shown(el) {
    var r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 40 && r.height > 40 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  }
  var frames = document.querySelectorAll('iframe');
  for (var i = 0; i < frames.length; i++) {
    var src = frames[i].src || '', title = (frames[i].title || '').toLowerCase();
    if (!shown(frames[i])) continue;
    if (/recaptcha\/(api2|enterprise)\/(anchor|bframe)/.test(src) && src.indexOf('size=invisible') < 0) return 'reCAPTCHA';
    if (/hcaptcha\.com/.test(src) || title.indexOf('hcaptcha') >= 0) return 'hCaptcha';
    if (/challenges\.cloudflare\.com/.test(src)) return 'Cloudflare Turnstile';
    if (title.indexOf('captcha') >= 0) return 'CAPTCHA';
  }
  if (document.querySelector('#challenge-form, #challenge-running, #cf-challenge-running')) return 'Cloudflare check';
  if (/\/sorry\/index/.test(location.pathname) && document.querySelector('#captcha-form, form[action*="sorry"]'))
    return 'Google unusual-traffic check';
  return '';
})()
"""


def call(template: str, *args) -> str:
    """Fill a %s template with JSON-encoded arguments."""
    return template % ", ".join(json.dumps(a) for a in args)
