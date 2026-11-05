// ==UserScript==
// @name        Video Speed Controller
// @description Speed up or slow down any video with the keyboard (lectures at 1.75×!), skip back and forward, and remember your speed for each site.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// Keys, when a video is on the page (not while you're typing):
//   D  faster (+0.25×)        S  slower (−0.25×)
//   R  switch between 1× and your speed
//   Z  back 10 seconds        X  forward 10 seconds
// Works on YouTube, Canvas, Khan Academy, Vimeo, Coursera, and video players inside other pages.
// Your speed is remembered per site and applied to every new video there.

var STEP = 0.25, MIN = 0.25, MAX = 4, SKIP = 10;

var speed = GM_getValue('vsc-speed', 1);
var ours = new WeakMap();      // video -> the rate we last set, to tell our changes from the site's
var started = new WeakMap();   // video -> when it started playing

function typing(e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
}

function videos() {
  var list = Array.prototype.slice.call(document.querySelectorAll('video'));
  // players that keep their video in a shadow root
  document.querySelectorAll('*').forEach(function (n) { if (n.shadowRoot) list = list.concat(Array.prototype.slice.call(n.shadowRoot.querySelectorAll('video'))); });
  return list.filter(function (v) { return v.readyState > 0 || v.src || v.currentSrc; });
}

function target() {   // the playing video, otherwise the biggest one on screen
  var vs = videos(), best = null, area = 0;
  for (var i = 0; i < vs.length; i++) {
    if (!vs[i].paused && !vs[i].ended) return vs[i];
    var r = vs[i].getBoundingClientRect(), a = Math.max(0, r.width) * Math.max(0, r.height);
    if (a > area) { area = a; best = vs[i]; }
  }
  return best;
}

function setRate(v, rate) {
  rate = Math.round(Math.max(MIN, Math.min(MAX, rate)) * 100) / 100;
  ours.set(v, rate);
  try { v.playbackRate = rate; } catch (e) {}
  return rate;
}

// ---- the little speed badge over the video
var CSS = [
  ':host { all: initial; }',
  '.badge { position: fixed; z-index: 2147483647; padding: 6px 12px; border-radius: 8px;',
  '  background: rgba(0, 0, 0, .72); color: #fff; font: 600 18px/1 "Segoe UI", system-ui, sans-serif;',
  '  pointer-events: none; transition: opacity .3s; }'
].join('\n');
var hostEl = document.createElement('pelagic-vsc'), root = hostEl.attachShadow({ mode: 'closed' });
try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
catch (e) { var st = document.createElement('style'); st.textContent = CSS; root.appendChild(st); }
var badge = document.createElement('div');
badge.className = 'badge';
root.appendChild(badge);
var badgeTimer = null;

function flash(v, text) {
  (document.fullscreenElement || document.documentElement).appendChild(hostEl);   // stays visible in full screen
  var r = v.getBoundingClientRect();
  badge.textContent = text;
  badge.style.left = Math.max(8, r.left + 14) + 'px';
  badge.style.top = Math.max(8, r.top + 14) + 'px';
  badge.style.opacity = '1';
  clearTimeout(badgeTimer);
  badgeTimer = setTimeout(function () { badge.style.opacity = '0'; }, 900);
}

function fmtRate(r) { return (Math.round(r * 100) / 100) + '×'; }

// ---- keys
document.addEventListener('keydown', function (e) {
  if (e.ctrlKey || e.altKey || e.metaKey || typing(e)) return;
  var k = e.key.toLowerCase();
  if ('dsrzx'.indexOf(k) < 0 || k.length !== 1) return;
  var v = target();
  if (!v) return;
  e.preventDefault();
  e.stopPropagation();
  if (k === 'd' || k === 's') {
    speed = setRate(v, v.playbackRate + (k === 'd' ? STEP : -STEP));
    GM_setValue('vsc-speed', speed);
    flash(v, fmtRate(speed));
  } else if (k === 'r') {
    var last = GM_getValue('vsc-last', 1.5);
    if (v.playbackRate !== 1) { GM_setValue('vsc-last', v.playbackRate); speed = setRate(v, 1); }
    else speed = setRate(v, last);
    GM_setValue('vsc-speed', speed);
    flash(v, fmtRate(speed));
  } else {
    v.currentTime = Math.max(0, Math.min((v.duration || Infinity), v.currentTime + (k === 'x' ? SKIP : -SKIP)));
    flash(v, (k === 'x' ? '» +' : '« −') + SKIP + 's');
  }
}, true);

// ---- keep the chosen speed on new videos (sites like YouTube reset it to 1× for each video)
function enforce(e) {
  var v = e.target;
  if (!(v instanceof HTMLMediaElement) || v.tagName !== 'VIDEO') return;
  if (e.type === 'playing') started.set(v, Date.now());
  if (e.type === 'ratechange') {
    if (ours.get(v) === v.playbackRate) return;
    // Changed by the site's own speed menu while the video was playing: that's you, so remember it.
    if (!v.paused && Date.now() - (started.get(v) || Date.now()) > 1500) {
      speed = v.playbackRate;
      ours.set(v, speed);
      GM_setValue('vsc-speed', speed);
      return;
    }
  }
  if (speed !== 1 && v.playbackRate !== speed) setRate(v, speed);
}
['loadedmetadata', 'play', 'playing', 'ratechange'].forEach(function (t) { document.addEventListener(t, enforce, true); });
videos().forEach(function (v) { if (speed !== 1) setRate(v, speed); });

if (window.top === window) {
  GM_registerMenuCommand('Reset this site to 1×', function () {
    speed = 1;
    GM_setValue('vsc-speed', 1);
    videos().forEach(function (v) { setRate(v, 1); });
  });
}
