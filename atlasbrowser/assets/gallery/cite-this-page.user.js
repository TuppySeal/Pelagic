// ==UserScript==
// @name        Cite This Page
// @description Makes an MLA, APA or Chicago citation for the page you're on, with the author, title and date filled in from the page. Fix anything it got wrong, then copy.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// @noframes
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// Alt+C (or "Cite this page" in the puzzle menu) opens the citation box. Copy keeps the italics when you paste
// into Google Docs or Word. Always give it a quick check: websites don't always label their authors and dates.

if (window.top !== window) return;

var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
              'November', 'December'];
var MLA_MONTHS = ['Jan.', 'Feb.', 'Mar.', 'Apr.', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.'];

// ---------------------------------------------------------------- reading the page

function meta(names) {
  for (var i = 0; i < names.length; i++) {
    var m = document.querySelector('meta[name="' + names[i] + '" i], meta[property="' + names[i] + '" i]');
    if (m && m.content && m.content.trim()) return m.content.trim();
  }
  return '';
}

function metaAll(name) {
  return Array.prototype.map.call(document.querySelectorAll('meta[name="' + name + '" i]'), function (m) { return m.content.trim(); })
    .filter(Boolean);
}

function jsonLd() {
  var found = {};
  document.querySelectorAll('script[type="application/ld+json"]').forEach(function (s) {
    var data;
    try { data = JSON.parse(s.textContent); } catch (e) { return; }
    var stack = [].concat(data);
    while (stack.length) {
      var d = stack.shift();
      if (!d || typeof d !== 'object') continue;
      if (d['@graph']) stack = stack.concat(d['@graph']);
      var type = [].concat(d['@type'] || []).join(' ');
      if (/Article|Posting|Report|WebPage|CreativeWork|Blog/.test(type) && !found.headline) {
        found.headline = d.headline || d.name;
        found.date = d.datePublished || d.dateCreated;
        found.authors = [].concat(d.author || []).map(function (a) { return typeof a === 'string' ? a : a && a.name; }).filter(Boolean);
        var pub = d.publisher || (d.isPartOf && d.isPartOf.name ? d.isPartOf : null);
        found.publisher = pub && (typeof pub === 'string' ? pub : pub.name);
      }
    }
  });
  return found;
}

function siteNameFromTitle(title) {
  var parts = title.split(/\s+[|\-–—·:]\s+/);
  return parts.length > 1 ? parts[parts.length - 1] : '';
}

function cleanTitle(title, site) {
  var t = title.trim();
  if (site) {
    var re = new RegExp('\\s+[|\\-–—·:]\\s+' + site.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*$', 'i');
    t = t.replace(re, '');
  }
  return t;
}

function readPage() {
  var ld = jsonLd();
  var site = meta(['og:site_name', 'citation_journal_title', 'application-name']) || ld.publisher ||
             siteNameFromTitle(document.title) || location.hostname.replace(/^www\./, '');
  var title = meta(['citation_title']) || ld.headline || meta(['og:title', 'twitter:title']) || document.title;
  var authors = metaAll('citation_author');
  if (!authors.length) authors = ld.authors || [];
  if (!authors.length) authors = [meta(['author', 'article:author', 'dc.creator', 'parsely-author', 'sailthru.author'])].filter(function (a) {
    return a && !/^https?:/.test(a);   // some sites put a profile link here
  });
  var date = meta(['citation_publication_date', 'citation_date', 'article:published_time', 'datePublished', 'dc.date',
                   'date', 'pubdate', 'publish-date']) || ld.date || '';
  if (!date) { var t = document.querySelector('article time[datetime], time[datetime]'); if (t) date = t.getAttribute('datetime'); }
  var doi = meta(['citation_doi']);
  return {
    authors: authors.join('; '),
    title: cleanTitle(title, site),
    site: site,
    date: date ? date.slice(0, 10) : '',
    url: doi ? 'https://doi.org/' + doi.replace(/^https?:\/\/doi\.org\//, '') : location.href.replace(/#.*$/, ''),
    accessed: new Date().toISOString().slice(0, 10)
  };
}

// ---------------------------------------------------------------- formatting

// "Jane Q. Doe" -> { first: 'Jane Q.', last: 'Doe' }; "Doe, Jane" too. Organisations stay whole.
function person(name) {
  name = name.replace(/^by\s+/i, '').trim();
  if (name.indexOf(',') > 0) { var p = name.split(','); return { last: p[0].trim(), first: p.slice(1).join(',').trim() }; }
  var words = name.split(/\s+/);
  if (words.length < 2 || words.length > 4 || /\b(inc|ltd|news|staff|team|editors?|university|association|press|times|post|bbc|cnn)\b/i.test(name))
    return { org: name };
  return { first: words.slice(0, -1).join(' '), last: words[words.length - 1] };
}

function people(s) { return s.split(/\s*;\s*|\s+and\s+|\s*&\s*/).filter(Boolean).map(person); }
function initials(first) { return first.split(/[\s-]+/).filter(Boolean).map(function (w) { return w[0].toUpperCase() + '.'; }).join(' '); }

function parseDate(s) {
  var m = /^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?/.exec(s || '');
  return m ? { y: +m[1], m: m[2] ? +m[2] - 1 : null, d: m[3] ? +m[3] : null } : null;
}

function mlaDate(d) { return d ? (d.d ? d.d + ' ' : '') + (d.m !== null ? MLA_MONTHS[d.m] + ' ' : '') + d.y : ''; }
function longDate(d) { return d ? (d.m !== null ? MONTHS[d.m] + ' ' : '') + (d.d ? d.d + ', ' : '') + d.y : ''; }
function end(s) { return /[.?!]$/.test(s) ? s : s + '.'; }

// Each style returns a list of [text, italic] pieces so it can be shown and copied with italics.
var STYLES = {
  MLA: function (f) {
    var a = people(f.authors), out = [], names = '';
    if (a.length === 1) names = a[0].org || a[0].last + ', ' + a[0].first;
    else if (a.length === 2) names = (a[0].org || a[0].last + ', ' + a[0].first) + ', and ' + (a[1].org || a[1].first + ' ' + a[1].last);
    else if (a.length > 2) names = (a[0].org || a[0].last + ', ' + a[0].first) + ', et al';
    if (names) out.push([end(names) + ' ', false]);
    out.push(['“' + end(f.title) + '” ', false]);
    var site = f.site && f.site !== f.title ? f.site : '';
    if (site) out.push([site, true], [', ', false]);
    var d = mlaDate(parseDate(f.date));
    out.push([(d ? d + ', ' : '') + f.url.replace(/^https?:\/\//, '') + '. ', false]);
    out.push(['Accessed ' + mlaDate(parseDate(f.accessed)) + '.', false]);
    return out;
  },
  APA: function (f) {
    var a = people(f.authors), out = [];
    var names = a.map(function (p) { return p.org || p.last + ', ' + initials(p.first); });
    var who = names.length === 0 ? '' : names.length === 1 ? names[0] : names.length <= 20
      ? names.slice(0, -1).join(', ') + ', & ' + names[names.length - 1] : names.slice(0, 19).join(', ') + ', . . . ' + names[names.length - 1];
    var d = parseDate(f.date);
    var when = '(' + (d ? d.y + (d.m !== null ? ', ' + MONTHS[d.m] + (d.d ? ' ' + d.d : '') : '') : 'n.d.') + '). ';
    if (who) out.push([end(who) + ' ' + when, false], [end(f.title), true], [' ', false]);
    else out.push([end(f.title), true], [' ' + when, false]);
    if (f.site && f.site !== f.title && !(a.length === 1 && a[0].org === f.site)) out.push([end(f.site) + ' ', false]);
    if (!d) out.push(['Retrieved ' + longDate(parseDate(f.accessed)) + ', from ', false]);
    out.push([f.url, false]);
    return out;
  },
  Chicago: function (f) {
    var a = people(f.authors), out = [], names = '';
    if (a.length) {
      names = a.map(function (p, i) { return p.org || (i === 0 ? p.last + ', ' + p.first : p.first + ' ' + p.last); });
      names = names.length > 10 ? names.slice(0, 7).join(', ') + ', et al' : names.length > 1
        ? names.slice(0, -1).join(', ') + ', and ' + names[names.length - 1] : names[0];
      out.push([end(names) + ' ', false]);
    }
    out.push(['“' + end(f.title) + '” ', false]);
    if (f.site && f.site !== f.title) out.push([end(f.site) + ' ', false]);
    var d = parseDate(f.date);
    out.push([(d ? end(longDate(d)) : 'Accessed ' + end(longDate(parseDate(f.accessed)))) + ' ', false]);
    out.push([end(f.url), false]);
    return out;
  }
};

function asText(parts) { return parts.map(function (p) { return p[0]; }).join(''); }
function escapeHtml(s) { return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
function asHtml(parts) { return parts.map(function (p) { return p[1] ? '<i>' + escapeHtml(p[0]) + '</i>' : escapeHtml(p[0]); }).join(''); }

function copy(parts) {
  var text = asText(parts), html = asHtml(parts);
  try {
    return navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }),
                                                          'text/plain': new Blob([text], { type: 'text/plain' }) })]);
  } catch (e) {
    return navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject(e);
  }
}

// ---------------------------------------------------------------- the box

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

var CSS = [
  ':host { all: initial; }',
  '.ui { position: fixed; inset: 0; z-index: 2147483647; display: flex; align-items: flex-start; justify-content: center;',
  '  padding-top: 8vh; background: rgba(0, 10, 15, .45); font: 14px/1.45 "Segoe UI", system-ui, sans-serif; color: #e6f4f1; }',
  ':host-context(html[data-pelagic-dark="1"]) .ui { filter: invert(1) hue-rotate(180deg); }',
  '.box { width: 640px; max-width: calc(100vw - 32px); max-height: 84vh; overflow: auto; background: #0b2430;',
  '  border-radius: 14px; box-shadow: 0 20px 60px rgba(0,0,0,.4); padding: 18px 20px 20px; box-sizing: border-box; }',
  'header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }',
  'h2 { margin: 0; font-size: 17px; font-weight: 600; }',
  '.tabs { display: flex; gap: 4px; background: #071a24; padding: 3px; border-radius: 999px; }',
  '.tabs button { border: 0; background: none; color: #9cbcb7; font: inherit; font-weight: 600; padding: 5px 14px; border-radius: 999px; cursor: pointer; }',
  '.tabs button.on { background: #2bb3a3; color: #04211d; }',
  '.out { background: #f8fbfa; color: #111; border-radius: 10px; padding: 14px 16px; padding-left: 36px; text-indent: -20px;',
  '  font: 15px/1.6 "Times New Roman", Georgia, serif; user-select: text; word-break: break-word; }',
  '.actions { display: flex; justify-content: flex-end; gap: 8px; margin: 12px 0 4px; }',
  '.btn { border: 0; border-radius: 999px; padding: 8px 18px; font: inherit; font-weight: 600; cursor: pointer; }',
  '.primary { background: #2bb3a3; color: #04211d; } .primary:hover { background: #3fcab9; }',
  '.ghost { background: none; color: #9cbcb7; } .ghost:hover { color: #fff; }',
  'details { margin-top: 10px; } summary { cursor: pointer; color: #9cbcb7; }',
  '.grid { display: grid; grid-template-columns: 110px 1fr; gap: 8px 10px; align-items: center; margin-top: 10px; }',
  'label { color: #9cbcb7; font-size: 13px; }',
  'input { font: inherit; color: #e6f4f1; background: #071a24; border: 1px solid #2c5560; border-radius: 8px; padding: 6px 9px; outline: none; }',
  'input:focus { border-color: #2bb3a3; }',
  '.hint { grid-column: 2; font-size: 12px; color: #7fa5a0; margin-top: -4px; }'
].join('\n');

var hostEl = null;

function open() {
  if (hostEl) { close(); return; }
  var fields = readPage(), style = GM_getValue('cite-style', 'MLA');
  hostEl = document.createElement('pelagic-cite');
  var root = hostEl.attachShadow({ mode: 'closed' });
  try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
  catch (e) { root.appendChild(el('style', { text: CSS })); }

  var out = el('div', { class: 'out' });
  var copyBtn = el('button', { class: 'btn primary', text: 'Copy' });
  var tabs = el('div', { class: 'tabs' });
  function render() {
    while (out.firstChild) out.firstChild.remove();
    STYLES[style](fields).forEach(function (p) { out.appendChild(p[1] ? el('i', { text: p[0] }) : document.createTextNode(p[0])); });
    tabs.querySelectorAll('button').forEach(function (b) { b.className = b.textContent === style ? 'on' : ''; });
  }
  Object.keys(STYLES).forEach(function (s) {
    tabs.appendChild(el('button', { text: s, onclick: function () { style = s; GM_setValue('cite-style', s); render(); } }));
  });
  copyBtn.addEventListener('click', function () {
    copy(STYLES[style](fields)).then(function () { copyBtn.textContent = 'Copied ✓'; setTimeout(function () { copyBtn.textContent = 'Copy'; }, 1500); },
                                     function () { GM_setClipboard(asText(STYLES[style](fields))); copyBtn.textContent = 'Copied ✓'; });
  });

  var grid = el('div', { class: 'grid' });
  [['authors', 'Author(s)', 'Separate people with ; like  Jane Doe; Sam Lee'], ['title', 'Title'], ['site', 'Website'],
   ['date', 'Published', 'YYYY-MM-DD, or just YYYY. Leave empty if there is none.'], ['url', 'URL'],
   ['accessed', 'Accessed']].forEach(function (f) {
    var input = el('input', { type: 'text' });
    input.value = fields[f[0]];
    input.addEventListener('input', function () { fields[f[0]] = input.value; render(); });
    grid.append(el('label', { text: f[1] }), input);
    if (f[2]) grid.appendChild(el('div', { class: 'hint', text: f[2] }));
  });
  var details = el('details', {}, [el('summary', { text: 'Check or edit the details' }), grid]);
  if (!fields.authors || !fields.date) details.open = true;   // something's missing: show the fields

  var box = el('div', { class: 'box' }, [
    el('header', {}, [el('h2', { text: 'Cite this page' }), tabs]),
    out,
    el('div', { class: 'actions' }, [el('button', { class: 'btn ghost', text: 'Close', onclick: close }), copyBtn]),
    details
  ]);
  var shade = el('div', { class: 'ui', onclick: function (e) { if (e.target === shade) close(); } }, [box]);
  shade.addEventListener('keydown', function (e) { e.stopPropagation(); if (e.key === 'Escape') close(); });
  root.appendChild(shade);
  document.documentElement.appendChild(hostEl);
  render();
  copyBtn.focus();
}

function close() { if (hostEl) { hostEl.remove(); hostEl = null; } }

document.addEventListener('keydown', function (e) {
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyC') { e.preventDefault(); open(); }
}, true);
GM_registerMenuCommand('Cite this page (Alt+C)', open);
