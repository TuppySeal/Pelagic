// ==UserScript==
// @name        Focus Blocker
// @description Blocks distracting sites during your study hours. Take a short break when you need one, after a 15-second pause to think it over.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// @noframes
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// ---- Your settings: edit these, then press Save ----------------------------------------------------------
// Sites to block. A site also blocks its subdomains (reddit.com blocks old.reddit.com).
var BLOCKED = ['tiktok.com', 'instagram.com', 'reddit.com', 'x.com', 'twitter.com', 'facebook.com', 'netflix.com',
               'twitch.tv'];
// When to block. Days: 0 = Sunday ... 6 = Saturday. An empty list blocks all the time.
var SCHEDULE = [
  { days: [1, 2, 3, 4, 5], from: '08:00', to: '15:30' },   // school day
  { days: [0, 1, 2, 3, 4], from: '19:00', to: '21:00' }    // homework
];
var BREAK_MINUTES = 5;    // how long a break lasts
var WAIT_SECONDS = 15;    // how long the break button makes you wait
// -----------------------------------------------------------------------------------------------------------
// You can also block any other site from the puzzle menu ("Focus Blocker: Block this site"). That choice is
// kept in that site's own storage.

if (window.top !== window) return;

var host = location.hostname.replace(/^www\./, '');
var listed = BLOCKED.some(function (d) { return host === d || host.slice(-(d.length + 1)) === '.' + d; });

function blockedHere() { return listed || GM_getValue('focus-block', false); }

function minutes(hhmm) { var p = hhmm.split(':'); return +p[0] * 60 + (+p[1] || 0); }

function inSchedule(now) {
  if (!SCHEDULE.length) return true;
  var m = now.getHours() * 60 + now.getMinutes();
  return SCHEDULE.some(function (s) {
    var a = minutes(s.from), b = minutes(s.to);
    if (a <= b) return s.days.indexOf(now.getDay()) >= 0 && m >= a && m < b;
    // overnight, e.g. 22:00 to 02:00: after midnight belongs to the day it started on
    var yesterday = (now.getDay() + 6) % 7;
    return (s.days.indexOf(now.getDay()) >= 0 && m >= a) || (s.days.indexOf(yesterday) >= 0 && m < b);
  });
}

function scheduleEnd(now) {   // when the current blocking window ends, for the screen's message
  var m = now.getHours() * 60 + now.getMinutes(), best = null;
  SCHEDULE.forEach(function (s) {
    var a = minutes(s.from), b = minutes(s.to);
    if ((a <= b && m >= a && m < b) || (a > b && (m >= a || m < b))) best = s.to;
  });
  return best;
}

function onBreak() { return Date.now() < GM_getValue('focus-break-until', 0); }

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
  '.ui { position: fixed; inset: 0; z-index: 2147483647; display: flex; align-items: center; justify-content: center;',
  '  background: radial-gradient(circle at 30% 20%, #12384a, #071a24 70%); color: #e6f4f1;',
  '  font: 16px/1.5 "Segoe UI", system-ui, sans-serif; }',
  ':host-context(html[data-pelagic-dark="1"]) .ui { filter: invert(1) hue-rotate(180deg); }',
  '.card { max-width: 460px; padding: 40px 36px; text-align: center; }',
  '.icon { font-size: 54px; line-height: 1; margin-bottom: 12px; }',
  'h1 { font-size: 28px; font-weight: 600; margin: 0 0 8px; }',
  'p { margin: 0 0 6px; color: #a9c8c4; }',
  '.site { color: #5fd3c4; font-weight: 600; }',
  '.row { display: flex; gap: 10px; justify-content: center; margin-top: 26px; flex-wrap: wrap; }',
  'button { font: inherit; font-size: 15px; border-radius: 999px; padding: 10px 20px; cursor: pointer; border: 0; }',
  '.primary { background: #2bb3a3; color: #04211d; font-weight: 600; }',
  '.primary:hover { background: #3fcab9; }',
  '.ghost { background: transparent; color: #a9c8c4; border: 1px solid #2c5560; }',
  '.ghost:hover:not([disabled]) { border-color: #5fd3c4; color: #e6f4f1; }',
  'button[disabled] { opacity: .5; cursor: default; }',
  '.quote { margin-top: 28px; font-size: 14px; font-style: italic; color: #7fa5a0; }'
].join('\n');

var QUOTES = ['Future you will be glad you did this.', 'One task at a time.', 'Small steps add up.',
              'You can scroll later. Finish this first.', 'Focus is a muscle. You are training it right now.'];

var shield = null, pauseTimer = null;

function pauseMedia() {
  document.querySelectorAll('video, audio').forEach(function (m) { try { m.pause(); } catch (e) {} });
}

function showShield() {
  if (shield) return;
  var hostEl = document.createElement('pelagic-focus');
  var root = hostEl.attachShadow({ mode: 'closed' });
  try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
  catch (e) { root.appendChild(el('style', { text: CSS })); }

  var end = scheduleEnd(new Date());
  var breakBtn = el('button', { class: 'ghost', disabled: '' });
  var wait = WAIT_SECONDS;
  function tick() {
    if (wait > 0) { breakBtn.textContent = 'Take a ' + BREAK_MINUTES + '-minute break (' + wait + ')'; wait--; setTimeout(tick, 1000); }
    else { breakBtn.textContent = 'Take a ' + BREAK_MINUTES + '-minute break'; breakBtn.removeAttribute('disabled'); }
  }
  tick();
  breakBtn.addEventListener('click', function () {
    if (breakBtn.hasAttribute('disabled')) return;
    GM_setValue('focus-break-until', Date.now() + BREAK_MINUTES * 60000);
    hideShield();
  });

  var card = el('div', { class: 'card' }, [
    el('div', { class: 'icon', text: '🌊' }),
    el('h1', { text: 'Stay in the flow' }),
    el('p', {}, [el('span', { class: 'site', text: host }), ' is blocked while you focus.']),
    end ? el('p', { text: 'Blocking ends at ' + end + '.' }) : null,
    el('div', { class: 'row' }, [
      el('button', { class: 'primary', text: 'Go back', onclick: function () {
        if (history.length > 1) history.back(); else location.href = 'about:blank';
      } }),
      breakBtn
    ]),
    el('div', { class: 'quote', text: QUOTES[Math.floor(Math.random() * QUOTES.length)] })
  ]);
  root.appendChild(el('div', { class: 'ui' }, [card]));
  document.documentElement.appendChild(hostEl);
  document.documentElement.style.setProperty('overflow', 'hidden', 'important');
  if (document.body) document.body.style.setProperty('visibility', 'hidden', 'important');
  pauseMedia();
  pauseTimer = setInterval(pauseMedia, 1000);
  shield = hostEl;
}

function hideShield() {
  if (!shield) return;
  shield.remove();
  shield = null;
  clearInterval(pauseTimer);
  document.documentElement.style.removeProperty('overflow');
  if (document.body) document.body.style.removeProperty('visibility');
}

function check() {
  if (blockedHere() && inSchedule(new Date()) && !onBreak()) showShield();
  else hideShield();
}

check();
setInterval(check, 15000);
document.addEventListener('visibilitychange', check);

if (!listed) GM_registerMenuCommand(GM_getValue('focus-block', false) ? 'Stop blocking this site'
                                                         : 'Block this site', function () {
  GM_setValue('focus-block', !GM_getValue('focus-block', false));
  check();
});
