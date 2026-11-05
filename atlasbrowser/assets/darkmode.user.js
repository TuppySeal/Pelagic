// ==UserScript==
// @name        Dark mode for websites
// @description Makes light websites dark. Sites that are already dark are left alone. Turn it off for one site from the extensions (puzzle) menu.
// @version     1.4
// @match       *://*/*
// @run-at      document-start
// ==/UserScript==

// Inverts the page's colours and turns photos, videos and other media back, so they keep their real colours.
// The per-site switch is stored in the site's own storage, so it only affects that site.
//
// Frames: the page turns embedded frames back to normal, and a same-site frame (like the ones school and work
// portals are built from) then darkens itself, following its parent. Other sites' frames (videos, maps) stay
// as they are.
//
// The style is added as a constructed style sheet where possible: sites with a strict Content-Security-Policy
// block <style> tags added by scripts, but not those.
var OFF_KEY = 'darkmode-off';
var FLAG = 'pelagicDark';     // data-pelagic-dark on <html> while this document is darkened
var CSS = [
  'html { filter: invert(0.9) hue-rotate(180deg) !important; background: #fff !important; }',
  'img, picture, video, canvas, svg image, iframe, frame, embed, object,',
  '[style*="background-image"], [style*="background: url"], [style*="background:url"]',
  '{ filter: invert(1) hue-rotate(180deg) !important; }',
  'img img, picture img, [style*="background-image"] img { filter: none !important; }',
  // video players keep their real (black) background and controls; the video inside them isn't turned twice
  '.html5-video-player, .video-js, .jwplayer, .plyr { filter: invert(1) hue-rotate(180deg) !important; }',
  '.html5-video-player video, .html5-video-player img, .html5-video-player canvas, .video-js video,',
  '.jwplayer video, .plyr video { filter: none !important; }',
  // big drawings (slides and thumbnails in Google Slides and other editors, charts, maps) keep their real colours
  // like photos do; small ones (icons) are darkened with the page
  '[data-pelagic-keep] { filter: invert(1) hue-rotate(180deg) !important; }',
  '[data-pelagic-keep] image, [data-pelagic-keep] img, [data-pelagic-keep] canvas, [data-pelagic-keep] svg,',
  '[data-pelagic-keep] [style*="background-image"] { filter: none !important; }'
].join('\n');

var KEEP = 'pelagicKeep', BIG_W = 160, BIG_H = 90;

// Marks big <svg> drawings so the style above turns them back. Drawings inside one already turned back aren't
// marked again, so nothing is turned twice.
function markDrawings() {
  if (!document.body) return;
  var list = document.body.getElementsByTagName('svg');
  for (var i = 0; i < list.length; i++) {
    var el = list[i];
    if (el.dataset[KEEP] || el.parentElement && el.parentElement.closest('[data-pelagic-keep]')) continue;
    var r = el.getBoundingClientRect();
    if (r.width >= BIG_W && r.height >= BIG_H) el.dataset[KEEP] = '1';
  }
}
var markTimer = 0, markObserver = null;
function watchDrawings(on) {
  if (on && !markObserver && document.body) {
    markObserver = new MutationObserver(function () {
      if (!markTimer) markTimer = setTimeout(function () { markTimer = 0; markDrawings(); }, 400);
    });
    markObserver.observe(document.body, { childList: true, subtree: true });
  } else if (!on && markObserver) {
    markObserver.disconnect();
    markObserver = null;
  }
  if (on) markDrawings();
}

var sheet = null, styleEl = null;
try { sheet = new CSSStyleSheet(); sheet.replaceSync(CSS); } catch (e) { sheet = null; }

function applied() { return document.documentElement && document.documentElement.dataset[FLAG] === '1'; }

function apply() {
  if (applied() || !document.documentElement) return;
  if (sheet && 'adoptedStyleSheets' in document) {
    if (document.adoptedStyleSheets.indexOf(sheet) < 0)
      document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sheet]);
  } else {
    styleEl = styleEl || GM_addStyle(CSS);
    if (!styleEl.isConnected) (document.head || document.documentElement).appendChild(styleEl);
  }
  document.documentElement.dataset[FLAG] = '1';
  watchDrawings(true);
}

function remove() {
  if (sheet && 'adoptedStyleSheets' in document)
    document.adoptedStyleSheets = document.adoptedStyleSheets.filter(function (s) { return s !== sheet; });
  if (styleEl) styleEl.remove();
  if (document.documentElement) delete document.documentElement.dataset[FLAG];
  watchDrawings(false);
}

function luminance(color) {
  var m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/.exec(color || '');
  if (!m || (m[4] !== undefined && parseFloat(m[4]) < 0.1)) return null;   // transparent: look further up
  return (0.2126 * m[1] + 0.7152 * m[2] + 0.0722 * m[3]) / 255;
}

// The background actually behind a point: the first element up from it that paints one.
function backgroundOf(el) {
  for (; el && el.nodeType === 1; el = el.parentElement) {
    var l = luminance(getComputedStyle(el).backgroundColor);
    if (l !== null) return l;
  }
  return null;
}

// Is the page dark by itself? Computed styles don't include our filter, and remove() takes our white html
// background away first. Web apps like Discord paint their dark theme on an inner element and leave <html> and
// <body> transparent, so what's on screen is sampled at 9 points, not just the body.
function alreadyDark() {
  var de = document.documentElement;
  if (!de) return false;
  var w = window.innerWidth, h = window.innerHeight, dark = 0, seen = 0;
  if (w > 0 && h > 0 && document.elementFromPoint) {
    [0.2, 0.5, 0.8].forEach(function (fy) {
      [0.2, 0.5, 0.8].forEach(function (fx) {
        var l = backgroundOf(document.elementFromPoint(w * fx, h * fy));
        if (l !== null) { seen++; if (l < 0.45) dark++; }
      });
    });
    if (seen >= 5) return dark * 2 > seen;
  }
  var els = [document.body, de];
  for (var i = 0; i < els.length; i++) {
    if (!els[i] || els[i].tagName === 'FRAMESET') continue;
    var l = luminance(getComputedStyle(els[i]).backgroundColor);
    if (l !== null) return l < 0.45;
  }
  // nothing paints a background: a dark color scheme, or light text, means the page is meant to be dark
  var scheme = getComputedStyle(de).colorScheme || '';
  if (/dark/.test(scheme) && !/light/.test(scheme)) return true;
  var text = luminance(getComputedStyle(document.body || de).color);
  return text !== null && text > 0.7;
}

// In a frame: follow the parent page if it's the same site, otherwise leave the frame alone.
function parentState() {
  if (window === window.parent) return 'top';
  try { return window.parent.document.documentElement.dataset[FLAG] === '1' ? 'on' : 'off'; }
  catch (e) { return 'off'; }   // another site's frame
}

function sync() {
  if (document.fullscreenElement) return;   // paused while a video is full screen
  var where = parentState();
  if (where === 'top') {
    if (GM_getValue(OFF_KEY, false)) { remove(); }
    else {   // measured without our filter, in the same task, so nothing flickers
      var was = applied();
      remove();
      if (!alreadyDark()) apply();
      if (was !== applied()) syncFrames();
      return;
    }
  } else if (where === 'on') {
    remove();
    if (!alreadyDark()) apply();
  } else {
    remove();
  }
  syncFrames();
}

function syncFrames() {
  for (var i = 0; i < window.frames.length; i++) {
    try { if (window.frames[i].__pelagicDarkSync) window.frames[i].__pelagicDarkSync(); } catch (e) {}
  }
}

// Full screen (a video): show the page as it really is, then darken again when it ends.
document.addEventListener('fullscreenchange', function () {
  if (document.fullscreenElement) { if (applied()) { remove(); document.documentElement.dataset.pelagicDarkPaused = '1'; } }
  else if (document.documentElement.dataset.pelagicDarkPaused) { delete document.documentElement.dataset.pelagicDarkPaused; sync(); }
});

window.__pelagicDarkSync = sync;
var start = parentState();
if ((start === 'top' && !GM_getValue(OFF_KEY, false)) || start === 'on') apply();
document.addEventListener('DOMContentLoaded', sync);
// Web apps draw their theme late and switch it later (Discord's settings): check again then.
window.addEventListener('load', function () { sync(); setTimeout(sync, 1500); setTimeout(sync, 5000); });
setTimeout(sync, 3000);
setTimeout(sync, 10000);
var pending = 0;
function soon() { clearTimeout(pending); pending = setTimeout(sync, 150); }
var watched = [];
function watch() {   // <html> may not exist yet at document-start, <body> only later
  [document.documentElement, document.body].forEach(function (el) {
    if (!el || watched.indexOf(el) >= 0) return;
    watched.push(el);
    new MutationObserver(soon).observe(el, { attributes: true,
      attributeFilter: ['class', 'style', 'data-theme', 'data-color-mode', 'data-color-scheme'] });
  });
}
watch();
document.addEventListener('DOMContentLoaded', watch);

// The puzzle menu shows "Dark mode for websites: Turn off for this site", and after that "… Turn on for this site".
var menuId = null;
function addMenu() {
  if (menuId !== null) GM_unregisterMenuCommand(menuId);
  menuId = GM_registerMenuCommand(GM_getValue(OFF_KEY, false) ? 'Turn on for this site' : 'Turn off for this site',
    function () {
      GM_setValue(OFF_KEY, !GM_getValue(OFF_KEY, false));
      sync();
      syncFrames();
      addMenu();
    });
}
if (start === 'top') addMenu();
