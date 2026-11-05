// ==UserScript==
// @name        Auto-Scroll
// @description Hands-free reading: Alt+S scrolls the page slowly at a speed you pick. Also adds middle-click scrolling, like Chrome and Edge on Windows.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// Reading mode
//   Alt+S          start or stop
//   ↑ / ↓  or  + / −   slower / faster while it's running
//   Space          pause or resume
//   Esc            stop (so does clicking the page)
// Middle-click scrolling
//   Middle-click on the page (not on a link), then move the mouse up or down. Click again to stop. Or hold the
//   middle button, move, and let go.

var MIDDLE_CLICK = true;   // set to false if Pelagic already scrolls on middle-click

function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

function typing(e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
}

// The thing that actually scrolls here: the page, or for app-style sites the biggest scrolling box.
function scrollerAt(x, y) {
  for (var n = document.elementFromPoint(x, y); n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    var s = getComputedStyle(n);
    if (/(auto|scroll|overlay)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 4) return n;
  }
  return document.scrollingElement || document.documentElement;
}

function canScroll(s) { return s.scrollHeight > s.clientHeight + 4; }

var CSS = [
  ':host { all: initial; }',
  '.ui { font: 600 12px/1 "Segoe UI", system-ui, sans-serif; }',
  ':host-context(html[data-pelagic-dark="1"]) .ui { filter: invert(1) hue-rotate(180deg); }',
  '.pill { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 2147483647;',
  '  display: flex; gap: 10px; align-items: center; padding: 8px 14px; border-radius: 999px;',
  '  background: rgba(7, 26, 36, .9); color: #e6f4f1; box-shadow: 0 4px 16px rgba(0,0,0,.25); user-select: none; }',
  '.pill .k { color: #7fa5a0; font-weight: 400; }',
  '.anchor { position: fixed; z-index: 2147483647; width: 28px; height: 28px; margin: -14px 0 0 -14px;',
  '  border-radius: 50%; background: rgba(7, 26, 36, .8); border: 2px solid #e6f4f1; box-sizing: border-box;',
  '  box-shadow: 0 2px 8px rgba(0,0,0,.3); pointer-events: none; }',
  '.anchor::before, .anchor::after { content: ""; position: absolute; left: 50%; margin-left: -4px;',
  '  border: 4px solid transparent; }',
  '.anchor::before { top: 1px; border-bottom-color: #e6f4f1; }',
  '.anchor::after { bottom: 1px; border-top-color: #e6f4f1; }',
  '.anchor i { position: absolute; left: 50%; top: 50%; width: 4px; height: 4px; margin: -2px; border-radius: 50%; background: #e6f4f1; }'
].join('\n');

var hostEl = document.createElement('pelagic-autoscroll');
var root = hostEl.attachShadow({ mode: 'closed' });
try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
catch (e) { root.appendChild(el('style', '', CSS)); }
var ui = el('div', 'ui');
root.appendChild(ui);
function attach() { if (!hostEl.isConnected) (document.fullscreenElement || document.documentElement).appendChild(hostEl); }

// ---------------------------------------------------------------- reading mode

var speed = GM_getValue('autoscroll-speed', 40);   // pixels per second
var reading = null;   // { scroller, paused, carry, last }
var pill = el('div', 'pill'), pillText = el('span'), pillKeys = el('span', 'k', '↑↓ speed · Space pause · Esc stop');
pill.append(pillText, pillKeys);
var hintTimer = null;

function showPill() {
  pillText.textContent = (reading && reading.paused ? 'Paused · ' : 'Auto-scroll · ') + Math.round(speed) + ' px/s';
  attach();
  if (!pill.isConnected) ui.appendChild(pill);
  pill.style.opacity = '1';
  clearTimeout(hintTimer);
  hintTimer = setTimeout(function () { pill.style.opacity = '0.45'; }, 2500);
}

function step(now) {
  if (!reading) return;
  var dt = Math.min(0.1, (now - reading.last) / 1000);
  reading.last = now;
  if (!reading.paused) {
    reading.carry += speed * dt;
    var px = Math.floor(reading.carry);
    if (px >= 1) {
      reading.carry -= px;
      var s = reading.scroller, before = s.scrollTop;
      s.scrollTop = before + px;
      if (s.scrollTop === before && before + s.clientHeight >= s.scrollHeight - 2) {   // reached the end
        stopReading();
        pillText.textContent = 'End of page';
        attach(); ui.appendChild(pill); pill.style.opacity = '1';
        setTimeout(function () { if (!reading) pill.remove(); }, 1500);
        return;
      }
    }
  }
  requestAnimationFrame(step);
}

function startReading() {
  var s = scrollerAt(innerWidth / 2, innerHeight / 2);
  if (!canScroll(s)) s = document.scrollingElement || document.documentElement;
  reading = { scroller: s, paused: false, carry: 0, last: performance.now() };
  showPill();
  requestAnimationFrame(step);
}

function stopReading() {
  reading = null;
  pill.remove();
}

function setSpeed(factor) {
  speed = Math.max(5, Math.min(600, speed * factor));
  GM_setValue('autoscroll-speed', Math.round(speed));
  showPill();
}

document.addEventListener('keydown', function (e) {
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyS' && !typing(e)) {
    e.preventDefault();
    if (reading) stopReading(); else startReading();
    return;
  }
  if (!reading || typing(e) || e.altKey || e.ctrlKey || e.metaKey) return;
  var used = true;
  if (e.key === 'ArrowDown' || e.key === '+' || e.key === '=') setSpeed(1.25);
  else if (e.key === 'ArrowUp' || e.key === '-' || e.key === '_') setSpeed(0.8);
  else if (e.key === ' ') { reading.paused = !reading.paused; reading.last = performance.now(); showPill(); }
  else if (e.key === 'Escape') stopReading();
  else used = false;
  if (used) { e.preventDefault(); e.stopPropagation(); }
}, true);

document.addEventListener('mousedown', function (e) { if (reading && e.button === 0 && e.composedPath().indexOf(hostEl) < 0) stopReading(); }, true);

// ---------------------------------------------------------------- middle-click scrolling

var drag = null;   // { scroller, x, y, mx, my, moved, held, vx, vy, last }
var anchor = el('div', 'anchor');
anchor.appendChild(el('i'));

function dragStep(now) {
  if (!drag) return;
  var dt = Math.min(0.05, (now - drag.last) / 1000);
  drag.last = now;
  function v(d) {   // a small dead zone, then speed grows faster the further you move
    var a = Math.abs(d) - 12;
    return a <= 0 ? 0 : Math.sign(d) * Math.min(4000, a * 4 + a * a * 0.04);
  }
  drag.cy += v(drag.my - drag.y) * dt;
  drag.cx += v(drag.mx - drag.x) * dt;
  var py = Math.trunc(drag.cy), px = Math.trunc(drag.cx);
  if (py || px) { drag.scroller.scrollBy(px, py); drag.cy -= py; drag.cx -= px; }
  requestAnimationFrame(dragStep);
}

function endDrag() {
  if (!drag) return;
  drag = null;
  anchor.remove();
  document.documentElement.style.removeProperty('cursor');
}

if (MIDDLE_CLICK) {
  document.addEventListener('mousedown', function (e) {
    if (drag) { e.preventDefault(); e.stopPropagation(); endDrag(); return; }
    if (e.button !== 1 || e.ctrlKey || e.shiftKey || e.altKey || e.metaKey || typing(e)) return;
    var t = e.composedPath()[0];
    if (t && t.closest && t.closest('a[href], button, [role="button"], video, iframe, embed, object')) return;   // keep middle-click to open in a new tab
    var s = scrollerAt(e.clientX, e.clientY);
    if (!canScroll(s)) return;
    e.preventDefault();
    if (reading) stopReading();
    drag = { scroller: s, x: e.clientX, y: e.clientY, mx: e.clientX, my: e.clientY, cx: 0, cy: 0, moved: false, last: performance.now() };
    anchor.style.left = e.clientX + 'px';
    anchor.style.top = e.clientY + 'px';
    attach();
    ui.appendChild(anchor);
    document.documentElement.style.setProperty('cursor', 'all-scroll', 'important');
    requestAnimationFrame(dragStep);
  }, true);
  document.addEventListener('mousemove', function (e) {
    if (!drag) return;
    drag.mx = e.clientX; drag.my = e.clientY;
    if (Math.abs(e.clientY - drag.y) > 16 || Math.abs(e.clientX - drag.x) > 16) drag.moved = true;
  }, true);
  document.addEventListener('mouseup', function (e) {
    if (drag && e.button === 1 && drag.moved) endDrag();   // held and dragged: letting go stops
  }, true);
  document.addEventListener('auxclick', function (e) { if (e.button === 1 && drag) e.preventDefault(); }, true);
  document.addEventListener('keydown', function (e) { if (drag && e.key === 'Escape') endDrag(); }, true);
  window.addEventListener('blur', endDrag);
  document.addEventListener('wheel', endDrag, { passive: true, capture: true });
}
