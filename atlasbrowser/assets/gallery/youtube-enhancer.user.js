// ==UserScript==
// @name        YouTube Enhancer
// @description Hides Shorts and opens Shorts links in the normal player. Optional focus switches hide comments, recommendations and the home feed. Clicks "Continue watching?" for you.
// @version     1.0
// @match       *://youtube.com/*
// @match       *://*.youtube.com/*
// @run-at      document-end
// @noframes
// ==/UserScript==

// Each switch is in the extensions (puzzle) menu while you're on YouTube. Your choices are remembered.
// Pelagic sites field: youtube.com

if (window.top !== window) return;

var SWITCHES = [   // [key, menu label, on by default]
  ['shorts', 'hide Shorts', true],
  ['comments', 'hide comments', false],
  ['recs', 'hide recommendations', false],
  ['home', 'hide the home page feed', false]
];

var CSS = [
  // Shorts shelves, tiles, tabs, chips and the sidebar entry
  'html[data-pel-yt~="shorts"] ytd-reel-shelf-renderer,',
  'html[data-pel-yt~="shorts"] ytd-rich-shelf-renderer[is-shorts],',
  'html[data-pel-yt~="shorts"] ytd-rich-section-renderer:has(ytd-rich-shelf-renderer[is-shorts]),',
  'html[data-pel-yt~="shorts"] ytd-rich-section-renderer:has(ytm-shorts-lockup-view-model),',
  'html[data-pel-yt~="shorts"] grid-shelf-view-model:has(ytm-shorts-lockup-view-model),',
  'html[data-pel-yt~="shorts"] ytm-shorts-lockup-view-model,',
  'html[data-pel-yt~="shorts"] ytd-rich-item-renderer:has(a[href^="/shorts/"]),',
  'html[data-pel-yt~="shorts"] ytd-video-renderer:has(a[href^="/shorts/"]),',
  'html[data-pel-yt~="shorts"] ytd-grid-video-renderer:has(a[href^="/shorts/"]),',
  'html[data-pel-yt~="shorts"] ytd-compact-video-renderer:has(a[href^="/shorts/"]),',
  'html[data-pel-yt~="shorts"] yt-lockup-view-model:has(a[href^="/shorts/"]),',
  'html[data-pel-yt~="shorts"] ytd-guide-entry-renderer:has(a[title="Shorts"]),',
  'html[data-pel-yt~="shorts"] ytd-mini-guide-entry-renderer[aria-label="Shorts"],',
  'html[data-pel-yt~="shorts"] yt-tab-shape[tab-title="Shorts"],',
  'html[data-pel-yt~="shorts"] yt-chip-cloud-chip-renderer:has(yt-formatted-string[title="Shorts"])',
  '{ display: none !important; }',
  // focus switches
  'html[data-pel-yt~="comments"] ytd-comments#comments, html[data-pel-yt~="comments"] #comments.ytd-watch-flexy',
  '{ display: none !important; }',
  'html[data-pel-yt~="recs"] #secondary #related, html[data-pel-yt~="recs"] ytd-watch-next-secondary-results-renderer,',
  'html[data-pel-yt~="recs"] .ytp-endscreen-content, html[data-pel-yt~="recs"] .ytp-ce-element,',
  'html[data-pel-yt~="recs"] .ytp-fullscreen-grid',
  '{ display: none !important; }',
  'html[data-pel-yt~="home"] ytd-browse[page-subtype="home"] #contents.ytd-rich-grid-renderer,',
  'html[data-pel-yt~="home"] ytd-browse[page-subtype="home"] #header.ytd-rich-grid-renderer',
  '{ display: none !important; }',
  'html[data-pel-yt~="home"] ytd-browse[page-subtype="home"] ytd-rich-grid-renderer::before {',
  '  content: "Home feed hidden. Search for what you came for."; display: block; padding: 80px 24px;',
  '  text-align: center; font: 500 18px Roboto, Arial, sans-serif; color: var(--yt-spec-text-secondary, #606060); }'
].join('\n');

function addCss(css) {
  try {
    var sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sheet]);
  } catch (e) {
    var s = document.createElement('style');
    s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
  }
}

function isOn(key, def) { return GM_getValue('yt-' + key, def); }

function applySwitches() {
  var on = SWITCHES.filter(function (s) { return isOn(s[0], s[2]); }).map(function (s) { return s[0]; });
  document.documentElement.dataset.pelYt = on.join(' ');
}

function caption(s) { return s[1][0].toUpperCase() + s[1].slice(1) + (isOn(s[0], s[2]) ? '  ✓ on' : '  (off)'); }

function setCaption(index, text) {   // keeps the puzzle menu's wording current after a switch is flipped
  try { window.__wfMenu[__wfId][index].caption = text; } catch (e) {}
}

// Shorts links open in the normal player, with its speed, captions and seek bar.
function redirectShorts() {
  if (!isOn('shorts', true)) return;
  var m = /^\/shorts\/([\w-]{6,})/.exec(location.pathname);
  if (m) location.replace('/watch?v=' + m[1]);
}

// "Video paused. Continue watching?"
function continueWatching() {
  var dialogs = document.querySelectorAll('ytd-popup-container yt-confirm-dialog-renderer, ytd-popup-container tp-yt-paper-dialog');
  for (var i = 0; i < dialogs.length; i++) {
    var d = dialogs[i];
    if (!d.offsetParent || !/continue watching/i.test(d.textContent)) continue;
    var btn = d.querySelector('#confirm-button button, #confirm-button, yt-button-renderer[dialog-confirm] button');
    if (btn) { btn.click(); console.log('[YouTube Enhancer] Clicked "Continue watching".'); }
  }
}

addCss(CSS);
applySwitches();
redirectShorts();
document.addEventListener('yt-navigate-start', redirectShorts);
document.addEventListener('yt-navigate-finish', redirectShorts);
window.addEventListener('popstate', redirectShorts);
setInterval(function () { redirectShorts(); continueWatching(); }, 2000);

SWITCHES.forEach(function (s) {
  var index = GM_registerMenuCommand(caption(s), function () {
    GM_setValue('yt-' + s[0], !isOn(s[0], s[2]));
    applySwitches();
    setCaption(index, caption(s));
    redirectShorts();
  });
});
