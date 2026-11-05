// ==UserScript==
// @name        Highlighter & Page Notes
// @description Highlight text on any page in four colours, add notes to highlights, keep a note for the whole page, and copy everything out as study notes. Highlights come back when you revisit the page.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// @noframes
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
//   • Select text and pick a colour from the little bar that pops up (or press Alt+H for yellow).
//   • Click a highlight to change its colour, write a note on it, or remove it.
//   • Alt+N opens the notes panel: your page note, every highlight on the page, and "Copy all" which copies
//     them as tidy notes you can paste into a doc.
// Highlights are saved in Pelagic for that page's address, on this computer only.

if (window.top !== window) return;

var COLORS = { yellow: '#fde68a', green: '#bbf7d0', pink: '#fbcfe8', blue: '#bfdbfe' };
var CONTEXT = 32;   // characters kept before and after a highlight, to find the same spot again

function pageKey() { return 'hl:' + location.pathname + location.search; }
function load() { return GM_getValue(pageKey(), { items: [], note: '' }); }
function save(data) {
  if (!data.items.length && !data.note) GM_deleteValue(pageKey());
  else GM_setValue(pageKey(), data);
}

function el(tag, props, kids) {
  var e = document.createElement(tag);
  Object.keys(props || {}).forEach(function (k) {
    if (k === 'text') e.textContent = props[k];
    else if (k === 'class') e.className = props[k];
    else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), props[k]);
    else e.setAttribute(k, props[k]);
  });
  (kids || []).forEach(function (c) { if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return e;
}

// ---------------------------------------------------------------- finding text on the page

var SKIP = /^(SCRIPT|STYLE|NOSCRIPT|TEXTAREA|INPUT|SELECT|OPTION|TEMPLATE|IFRAME|SVG|CANVAS|PELAGIC-NOTES)$/;

// Every visible text node in order, with where it starts in the page's text.
function textIndex() {
  var nodes = [], text = '';
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: function (n) {
      for (var p = n.parentElement; p && p !== document.body; p = p.parentElement)
        if (SKIP.test(p.tagName.toUpperCase()) || p.isContentEditable) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  for (var n = walker.nextNode(); n; n = walker.nextNode()) {
    nodes.push({ node: n, start: text.length, end: text.length + n.data.length });
    text += n.data;
  }
  return { nodes: nodes, text: text };
}

function boundaryOffset(idx, container, offset) {
  if (container.nodeType === 3) {
    for (var i = 0; i < idx.nodes.length; i++) if (idx.nodes[i].node === container) return idx.nodes[i].start + offset;
  }
  var probe = document.createRange();
  probe.setStart(container, offset);
  for (var j = 0; j < idx.nodes.length; j++)   // first indexed text at or after the boundary
    if (probe.comparePoint(idx.nodes[j].node, 0) >= 0) return idx.nodes[j].start;
  return idx.text.length;
}

function locate(idx, item) {   // where a saved highlight is now, using its text and what was around it
  var best = -1, bestScore = -1, from = 0, at;
  while ((at = idx.text.indexOf(item.text, from)) >= 0) {
    var score = 0, before = idx.text.slice(Math.max(0, at - item.prefix.length), at), after = idx.text.substr(at + item.text.length, item.suffix.length);
    for (var i = 1; i <= before.length && before[before.length - i] === item.prefix[item.prefix.length - i]; i++) score++;
    for (var k = 0; k < after.length && after[k] === item.suffix[k]; k++) score++;
    if (score > bestScore) { best = at; bestScore = score; }
    from = at + 1;
  }
  return best;
}

function paint(mark, color) {
  mark.style.setProperty('background-color', COLORS[color] || COLORS.yellow, 'important');
  mark.style.setProperty('color', '#111', 'important');
  mark.style.setProperty('border-radius', '2px', 'important');
  mark.style.setProperty('cursor', 'pointer', 'important');
  mark.style.setProperty('box-decoration-break', 'clone', 'important');
}

function wrap(idx, start, end, item) {
  var made = 0;
  idx.nodes.forEach(function (n) {
    if (n.end <= start || n.start >= end) return;
    var t = n.node, a = Math.max(start, n.start) - n.start, b = Math.min(end, n.end) - n.start;
    if (!t.data.slice(a, b).trim()) return;   // whitespace between blocks
    if (b < t.data.length) t.splitText(b);
    if (a > 0) t = t.splitText(a);
    var mark = document.createElement('pelagic-hl');
    mark.dataset.id = item.id;
    if (item.note) mark.title = item.note;
    paint(mark, item.color);
    t.parentNode.insertBefore(mark, t);
    mark.appendChild(t);
    made++;
  });
  return made > 0;
}

function marksFor(id) { return document.querySelectorAll('pelagic-hl[data-id="' + id + '"]'); }

function unwrap(id) {
  marksFor(id).forEach(function (m) {
    var p = m.parentNode;
    while (m.firstChild) p.insertBefore(m.firstChild, m);
    m.remove();
    p.normalize();
  });
}

function restore() {
  var data = load();
  data.items.forEach(function (item) {
    if (marksFor(item.id).length) return;
    var idx = textIndex(), at = locate(idx, item);
    if (at >= 0) wrap(idx, at, at + item.text.length, item);
  });
  if (panel.isConnected) fillPanel();
}

// ---------------------------------------------------------------- the interface

var CSS = [
  ':host { all: initial; }',
  '.ui { font: 13px/1.4 "Segoe UI", system-ui, sans-serif; color: #e6f4f1; }',
  ':host-context(html[data-pelagic-dark="1"]) .ui { filter: invert(1) hue-rotate(180deg); }',
  '.bar, .pop { position: fixed; z-index: 2147483647; display: flex; align-items: center; gap: 6px; padding: 6px 8px;',
  '  background: #0b2430; border-radius: 999px; box-shadow: 0 6px 20px rgba(0,0,0,.3); }',
  '.pop { border-radius: 12px; flex-direction: column; align-items: stretch; padding: 10px; width: 260px; gap: 8px; }',
  '.dots { display: flex; gap: 6px; align-items: center; }',
  '.dot { width: 20px; height: 20px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; padding: 0; }',
  '.dot:hover, .dot.on { border-color: #fff; }',
  '.btn { background: none; border: 0; color: #cfe6e2; font: inherit; cursor: pointer; padding: 3px 8px; border-radius: 6px; }',
  '.btn:hover { background: #1b3b47; color: #fff; }',
  '.btn.danger:hover { background: #5b1f24; }',
  '.sep { width: 1px; height: 18px; background: #2c5560; }',
  'textarea { font: inherit; color: #e6f4f1; background: #071a24; border: 1px solid #2c5560; border-radius: 8px;',
  '  padding: 8px; resize: vertical; min-height: 64px; outline: none; }',
  'textarea:focus { border-color: #2bb3a3; }',
  '.row { display: flex; justify-content: space-between; align-items: center; gap: 6px; }',
  '.panel { position: fixed; top: 0; right: 0; bottom: 0; width: 360px; max-width: 92vw; z-index: 2147483647;',
  '  background: #0b2430; box-shadow: -8px 0 30px rgba(0,0,0,.3); display: flex; flex-direction: column; }',
  '.panel header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }',
  '.panel h2 { font-size: 16px; margin: 0; font-weight: 600; }',
  '.panel .body { overflow: auto; padding: 0 16px 16px; flex: 1; }',
  '.panel h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #7fa5a0; margin: 14px 0 6px; }',
  '.panel textarea { width: 100%; box-sizing: border-box; min-height: 90px; }',
  '.item { border-left: 4px solid; padding: 6px 8px; margin-bottom: 8px; background: #102e3a; border-radius: 0 6px 6px 0; cursor: pointer; }',
  '.item:hover { background: #143845; }',
  '.item .q { color: #e6f4f1; }',
  '.item .n { color: #9cbcb7; margin-top: 4px; font-style: italic; }',
  '.empty { color: #7fa5a0; }',
  '.panel footer { display: flex; gap: 6px; padding: 10px 16px 14px; border-top: 1px solid #1b3b47; flex-wrap: wrap; }',
  '.toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #2bb3a3; color: #04211d;',
  '  padding: 8px 16px; border-radius: 999px; font-weight: 600; z-index: 2147483647; }'
].join('\n');

var hostEl = document.createElement('pelagic-notes');
var root = hostEl.attachShadow({ mode: 'closed' });
try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
catch (e) { root.appendChild(el('style', { text: CSS })); }
var ui = el('div', { class: 'ui' });
root.appendChild(ui);
document.documentElement.appendChild(hostEl);

function toast(text) {
  var t = el('div', { class: 'toast', text: text });
  ui.appendChild(t);
  setTimeout(function () { t.remove(); }, 1800);
}

function inUi(e) { return e.composedPath().indexOf(hostEl) >= 0; }

// --- selection bar
var bar = el('div', { class: 'bar' });
Object.keys(COLORS).forEach(function (c) {
  var d = el('button', { class: 'dot', title: 'Highlight ' + c,
    onmousedown: function (e) { e.preventDefault(); }, onclick: function () { highlightSelection(c); } });
  d.style.background = COLORS[c];
  bar.appendChild(d);
});
bar.appendChild(el('span', { class: 'sep' }));
bar.appendChild(el('button', { class: 'btn', text: 'Note', title: 'Highlight and add a note',
  onmousedown: function (e) { e.preventDefault(); }, onclick: function () { var id = highlightSelection('yellow'); if (id) openPop(id, true); } }));

function selectionRange() {
  var s = window.getSelection();
  if (!s || s.isCollapsed || !s.rangeCount) return null;
  var r = s.getRangeAt(0), c = r.commonAncestorContainer;
  var host = c.nodeType === 1 ? c : c.parentElement;
  if (!host || !document.body.contains(host) || host.closest('input, textarea, [contenteditable=""], [contenteditable="true"]')) return null;
  return r.toString().trim() ? r : null;
}

function showBar() {
  var r = selectionRange();
  if (!r) { bar.remove(); return; }
  var rect = r.getBoundingClientRect();
  ui.appendChild(bar);
  var w = bar.offsetWidth, top = rect.top - bar.offsetHeight - 8;
  bar.style.left = Math.max(6, Math.min(rect.left + rect.width / 2 - w / 2, innerWidth - w - 6)) + 'px';
  bar.style.top = (top < 6 ? rect.bottom + 8 : top) + 'px';
}

function highlightSelection(color) {
  var r = selectionRange();
  bar.remove();
  if (!r) return null;
  var idx = textIndex();
  var start = boundaryOffset(idx, r.startContainer, r.startOffset), end = boundaryOffset(idx, r.endContainer, r.endOffset);
  while (start < end && /\s/.test(idx.text[start])) start++;
  while (end > start && /\s/.test(idx.text[end - 1])) end--;
  if (end <= start) return null;
  var item = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), color: color, note: '',
               text: idx.text.slice(start, end), prefix: idx.text.slice(Math.max(0, start - CONTEXT), start),
               suffix: idx.text.slice(end, end + CONTEXT), created: Date.now() };
  if (!wrap(idx, start, end, item)) return null;
  var data = load();
  data.items.push(item);
  save(data);
  window.getSelection().removeAllRanges();
  if (panel.isConnected) fillPanel();
  return item.id;
}

// --- popup for one highlight
var pop = null;
function openPop(id, focusNote) {
  closePop();
  var data = load(), item = data.items.filter(function (i) { return i.id === id; })[0];
  var marks = marksFor(id);
  if (!item || !marks.length) return;
  var note = el('textarea', { placeholder: 'Add a note…' });
  note.value = item.note || '';
  var dots = el('div', { class: 'dots' });
  Object.keys(COLORS).forEach(function (c) {
    var d = el('button', { class: 'dot' + (c === item.color ? ' on' : ''), title: c, onclick: function () {
      item.color = c; marksFor(id).forEach(function (m) { paint(m, c); });
      dots.querySelectorAll('.dot').forEach(function (x) { x.classList.remove('on'); }); d.classList.add('on');
      save(data); if (panel.isConnected) fillPanel();
    } });
    d.style.background = COLORS[c];
    dots.appendChild(d);
  });
  function commit() {
    item.note = note.value.trim();
    marksFor(id).forEach(function (m) { m.title = item.note; });
    save(data);
    if (panel.isConnected) fillPanel();
  }
  note.addEventListener('input', commit);
  note.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePop(); e.stopPropagation(); });
  pop = el('div', { class: 'pop' }, [
    dots, note,
    el('div', { class: 'row' }, [
      el('button', { class: 'btn danger', text: 'Remove highlight', onclick: function () {
        unwrap(id); data.items = data.items.filter(function (i) { return i.id !== id; }); save(data);
        closePop(); if (panel.isConnected) fillPanel();
      } }),
      el('button', { class: 'btn', text: 'Done', onclick: closePop })
    ])
  ]);
  ui.appendChild(pop);
  var rect = marks[marks.length - 1].getBoundingClientRect();
  pop.style.left = Math.max(6, Math.min(rect.left, innerWidth - 272)) + 'px';
  var top = rect.bottom + 8;
  pop.style.top = (top + pop.offsetHeight > innerHeight ? Math.max(6, rect.top - pop.offsetHeight - 8) : top) + 'px';
  if (focusNote) note.focus();
}
function closePop() { if (pop) { pop.remove(); pop = null; } }

// --- side panel
var panel = el('div', { class: 'panel' });
function fillPanel() {
  var data = load();
  while (panel.firstChild) panel.firstChild.remove();
  var pageNote = el('textarea', { placeholder: 'Notes about this page…' });
  pageNote.value = data.note || '';
  pageNote.addEventListener('input', function () { var d = load(); d.note = pageNote.value; save(d); });
  pageNote.addEventListener('keydown', function (e) { e.stopPropagation(); if (e.key === 'Escape') panel.remove(); });
  var list = el('div');
  if (!data.items.length) list.appendChild(el('div', { class: 'empty', text: 'Select text on the page to highlight it.' }));
  data.items.forEach(function (item) {
    var box = el('div', { class: 'item', title: 'Show on the page', onclick: function () {
      var m = marksFor(item.id)[0];
      if (m) { m.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(function () { openPop(item.id); }, 450); }
      else toast('This one isn’t on the page right now');
    } }, [el('div', { class: 'q', text: item.text.length > 240 ? item.text.slice(0, 240) + '…' : item.text }),
          item.note ? el('div', { class: 'n', text: item.note }) : null]);
    box.style.borderLeftColor = COLORS[item.color] || COLORS.yellow;
    list.appendChild(box);
  });
  panel.append(
    el('header', {}, [el('h2', { text: 'Notes for this page' }), el('button', { class: 'btn', text: '✕', title: 'Close (Alt+N)', onclick: function () { panel.remove(); } })]),
    el('div', { class: 'body' }, [el('h3', { text: 'Page note' }), pageNote,
                                  el('h3', { text: 'Highlights (' + data.items.length + ')' }), list]),
    el('footer', {}, [
      el('button', { class: 'btn', text: 'Copy all', onclick: copyAll }),
      el('button', { class: 'btn danger', text: 'Clear this page', onclick: clearPage })
    ]));
}
function togglePanel() {
  if (panel.isConnected) { panel.remove(); return; }
  fillPanel();
  ui.appendChild(panel);
}

function copyAll() {
  var data = load(), title = document.title || location.hostname;
  var out = ['# ' + title, location.href, ''];
  if (data.note) out.push(data.note.trim(), '');
  data.items.forEach(function (i) { out.push('> ' + i.text.replace(/\s+/g, ' ')); if (i.note) out.push('  - ' + i.note); out.push(''); });
  var text = out.join('\n');
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
    .then(function () { toast('Copied ' + data.items.length + ' highlight' + (data.items.length === 1 ? '' : 's')); },
          function () { GM_setClipboard(text); toast('Copied'); });
}

function clearPage() {
  var data = load();
  if (!data.items.length && !data.note) return;
  if (!confirm('Remove all highlights and the note for this page?')) return;
  data.items.forEach(function (i) { unwrap(i.id); });
  save({ items: [], note: '' });
  fillPanel();
}

// ---------------------------------------------------------------- events

document.addEventListener('mouseup', function (e) { if (!inUi(e)) setTimeout(showBar, 10); });
document.addEventListener('keyup', function (e) { if (e.shiftKey && !inUi(e)) showBar(); });
document.addEventListener('mousedown', function (e) {
  if (inUi(e)) return;
  bar.remove();
  closePop();
});
document.addEventListener('click', function (e) {
  if (inUi(e)) return;
  var m = e.target.closest && e.target.closest('pelagic-hl');
  // (a highlighted link still works as a link)
  if (m && !m.closest('a') && window.getSelection().isCollapsed) { e.preventDefault(); e.stopPropagation(); openPop(m.dataset.id); }
}, true);
document.addEventListener('keydown', function (e) {
  if (!e.altKey || e.ctrlKey || e.metaKey) return;
  if (e.code === 'KeyH') { if (selectionRange()) { e.preventDefault(); highlightSelection('yellow'); } }
  else if (e.code === 'KeyN') { e.preventDefault(); togglePanel(); }
}, true);
window.addEventListener('scroll', function () { bar.remove(); closePop(); }, true);

restore();
setTimeout(restore, 1500);   // text that arrives after the page loads
setTimeout(restore, 4000);
var lastKey = pageKey();
setInterval(function () {      // single-page sites change address without reloading
  if (pageKey() !== lastKey) { lastKey = pageKey(); closePop(); setTimeout(restore, 800); }
}, 1000);

GM_registerMenuCommand('Open notes panel (Alt+N)', togglePanel);
GM_registerMenuCommand('Copy all highlights from this page', copyAll);
