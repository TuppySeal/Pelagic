// ==UserScript==
// @name        Word Count & Reading Time
// @description Shows how long an article takes to read, and live word and character counts for text you select or type (handy for essay limits).
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// @noframes
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// A small pill in the bottom-right corner shows:
//   • on articles: "1,240 words · 6 min read"
//   • while text is selected: the selection's words and characters
//   • while you type in a text box: that box's words and characters
// Alt+W hides or shows it. Hide it for one site from the puzzle menu.

if (window.top !== window) return;

var WPM = 230;          // reading speed, words per minute
var MIN_ARTICLE = 250;  // pages with fewer words don't show a reading time

var hidden = GM_getValue('wc-hidden', false);
var seg = null;
try { seg = new Intl.Segmenter(undefined, { granularity: 'word' }); } catch (e) {}

function countWords(text) {
  if (!text) return 0;
  if (seg) {   // also handles languages without spaces, like Chinese and Japanese
    var n = 0;
    for (var it = seg.segment(text)[Symbol.iterator](), s = it.next(); !s.done; s = it.next()) if (s.value.isWordLike) n++;
    return n;
  }
  var m = text.match(/[\p{L}\p{N}][\p{L}\p{N}'’\-]*/gu);
  return m ? m.length : 0;
}

function fmt(n) { return n.toLocaleString(); }

function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

var CSS = [
  ':host { all: initial; }',
  '.ui { position: fixed; right: 16px; bottom: 16px; z-index: 2147483646; display: flex; align-items: center; gap: 8px;',
  '  padding: 7px 14px; border-radius: 999px; background: rgba(7, 26, 36, .88); color: #e6f4f1;',
  '  font: 500 13px/1.3 "Segoe UI", system-ui, sans-serif; box-shadow: 0 4px 16px rgba(0,0,0,.25);',
  '  backdrop-filter: blur(6px); transition: opacity .25s, transform .25s; cursor: default; user-select: none; }',
  ':host-context(html[data-pelagic-dark="1"]) .ui { filter: invert(1) hue-rotate(180deg); }',
  '.ui.quiet { opacity: .35; }',
  '.ui:hover { opacity: 1; }',
  '.ui.gone { opacity: 0; transform: translateY(8px); pointer-events: none; }',
  '.dot { width: 8px; height: 8px; border-radius: 50%; background: #2bb3a3; flex: none; }',
  '.dot.sel { background: #f5c451; } .dot.field { background: #7aa7ff; }',
  '.sub { color: #9cbcb7; font-weight: 400; }',
  '.x { margin-left: 2px; color: #9cbcb7; cursor: pointer; font-size: 15px; line-height: 1; }',
  '.x:hover { color: #fff; }'
].join('\n');

var host = document.createElement('pelagic-wordcount');
var root = host.attachShadow({ mode: 'closed' });
try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
catch (e) { root.appendChild(el('style', '', CSS)); }
var pill = el('div', 'ui gone'), dot = el('span', 'dot'), main = el('span'), sub = el('span', 'sub'), x = el('span', 'x', '×');
x.title = 'Hide (Alt+W)';
x.addEventListener('click', function () { toggle(true); });
pill.append(dot, main, sub, x);
root.appendChild(pill);
document.documentElement.appendChild(host);

var article = { words: 0, url: '' }, quietTimer = null;

function articleText() {
  var best = null, bestLen = 0;
  document.querySelectorAll('article, main, [role="main"], .post-content, .entry-content, #content').forEach(function (c) {
    var len = (c.innerText || '').length;
    if (len > bestLen) { best = c; bestLen = len; }
  });
  if (!best || bestLen < 500) best = document.body;
  return best ? best.innerText : '';
}

function measureArticle() {
  article = { words: countWords(articleText()), url: location.href };
  render();
}

function selectionText() {
  var a = document.activeElement;
  if (a && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && /^(text|search|)$/i.test(a.type))) &&
      a.selectionStart !== a.selectionEnd) return a.value.slice(a.selectionStart, a.selectionEnd);
  var s = window.getSelection();
  return s && !s.isCollapsed ? s.toString() : '';
}

function fieldText() {
  var a = document.activeElement;
  if (!a) return null;
  if (a.tagName === 'TEXTAREA') return a.value;
  if (a.isContentEditable) {
    var top = a;   // count the whole editor, not just the paragraph that has focus
    while (top.parentElement && top.parentElement.isContentEditable) top = top.parentElement;
    return top.innerText;
  }
  return null;
}

function show(kind, a, b) {
  dot.className = 'dot' + (kind ? ' ' + kind : '');
  main.textContent = a;
  sub.textContent = b || '';
  pill.className = 'ui';
  clearTimeout(quietTimer);
  if (!kind) quietTimer = setTimeout(function () { pill.className = 'ui quiet'; }, 5000);   // reading time fades back
}

function render() {
  if (hidden) { pill.className = 'ui gone'; return; }
  var sel = selectionText();
  if (sel.trim()) {
    var w = countWords(sel);
    return show('sel', fmt(w) + (w === 1 ? ' word' : ' words') + ' selected',
                fmt(sel.length) + ' chars · ' + fmt(sel.replace(/\s/g, '').length) + ' without spaces');
  }
  var f = fieldText();
  if (f !== null) {
    var fw = countWords(f);
    return show('field', fmt(fw) + (fw === 1 ? ' word' : ' words'), fmt(f.replace(/\n$/, '').length) + ' chars');
  }
  if (article.words >= MIN_ARTICLE) {
    var mins = Math.max(1, Math.round(article.words / WPM));
    return show('', fmt(article.words) + ' words', mins + ' min read');
  }
  pill.className = 'ui gone';
}

function toggle(hide) {
  hidden = hide;
  GM_setValue('wc-hidden', hidden);
  render();
}

var raf = 0;
function soon() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; render(); }); }
document.addEventListener('selectionchange', soon);
document.addEventListener('input', soon, true);
document.addEventListener('focusin', soon);
document.addEventListener('focusout', function () { setTimeout(render, 0); });
document.addEventListener('keydown', function (e) {
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyW') { e.preventDefault(); toggle(!hidden); }
}, true);

measureArticle();
setTimeout(measureArticle, 2500);    // pages that load their text late
setInterval(function () { if (location.href !== article.url) { article.url = location.href; setTimeout(measureArticle, 800); } }, 1000);   // single-page sites

GM_registerMenuCommand('Hide or show on this site (Alt+W)', function () { toggle(!hidden); });
