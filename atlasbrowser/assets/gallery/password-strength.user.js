// ==UserScript==
// @name        Password Strength Meter
// @description Shows how strong a new password is while you type it, roughly how long it would take to crack, and how to make it better. Nothing leaves your computer.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// The meter appears under password boxes on sign-up and change-password forms. It stays out of the way on
// ordinary login forms. The check runs entirely in the page: your password is never stored or sent anywhere.
//
// The crack time assumes an attacker with a stolen password database guessing 10 billion times a second.

var GUESSES_PER_SECOND = 1e10;

// The most common passwords (from public breach lists), lowercase. Numbers and symbols added to the end of one
// of these, like "monkey123!", barely help.
var COMMON = ('password passw0rd 123456 12345678 123456789 1234567890 qwerty qwertyuiop asdfgh asdfghjkl zxcvbnm ' +
  'qazwsx 1qaz2wsx abc123 111111 000000 123123 654321 666666 121212 112233 iloveyou admin welcome login ' +
  'letmein monkey dragon master sunshine princess football baseball basketball soccer hockey shadow superman ' +
  'batman michael jennifer jordan hunter ranger buster thomas robert daniel andrew charlie tigger pepper ' +
  'ginger cookie summer winter spring autumn flower freedom whatever trustno1 starwars pokemon minecraft ' +
  'fortnite roblox naruto hello hello123 secret access mustang harley killer computer internet samsung apple ' +
  'google facebook instagram youtube twitter school student teacher college love lovely loveme family ' +
  'blink182 liverpool chelsea arsenal barcelona madrid cheese chocolate banana orange purple yellow ' +
  'qwerty123 password1 changeme default test testing guest user root abcdef abcd1234 aaaaaa zaq12wsx')
  .split(' ');

var LEET = { '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '8': 'b', '@': 'a', '$': 's', '!': 'i' };
var ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm', '1234567890', 'abcdefghijklmnopqrstuvwxyz'];

function log2(n) { return Math.log(n) / Math.LN2; }

function patterned(a, b) {   // b follows a by repeating it, counting up/down, or walking along a keyboard row
  if (a === b) return true;
  var x = a.toLowerCase(), y = b.toLowerCase();
  if (Math.abs(x.charCodeAt(0) - y.charCodeAt(0)) === 1) return true;
  return ROWS.some(function (r) { var i = r.indexOf(x); return i >= 0 && (r[i + 1] === y || r[i - 1] === y); });
}

// Estimates the password's strength in bits. Like a cracking program, it tries common passwords, words,
// years and keyboard patterns before brute force, so those count for much less than random characters.
function analyse(pw) {
  var tips = [], flags = {};
  var lower = pw.toLowerCase();
  function unleet(t) { return t.replace(/[0134578@$!]/g, function (c) { return LEET[c]; }); }
  var plain = unleet(lower);
  var core = unleet(lower.replace(/[^a-z]+$/, '').replace(/^[^a-z]+/, ''));   // "P@ssword123!" -> "password"

  if (COMMON.indexOf(lower) >= 0 || COMMON.indexOf(plain) >= 0) {
    return { bits: 4 + log2(COMMON.indexOf(plain) + 2), tips: ['This is one of the most common passwords. Pick something else.'] };
  }

  var bits = 0, runs = pw.match(/[a-zA-Z]+|[0-9]+|[^a-zA-Z0-9]+/g) || [];
  runs.forEach(function (run) {
    var eff = 1;   // characters that aren't a repeat or a sequence of the one before
    for (var i = 1; i < run.length; i++) eff += patterned(run[i - 1], run[i]) ? 0.25 : 1;
    if (eff < run.length * 0.6 && run.length >= 3) flags.pattern = true;
    if (/^[a-zA-Z]+$/.test(run)) {
      var l = run.toLowerCase();
      var vowels = (l.match(/[aeiouy]/g) || []).length / l.length;
      var wordy = l.length >= 3 && vowels >= 0.2 && vowels <= 0.65;
      if (COMMON.indexOf(l) >= 0) { bits += 6; flags.common = true; }
      else bits += wordy ? Math.max(8, eff * 2.4) : eff * log2(26);
      if (/[A-Z]/.test(run.slice(1)) && /[a-z]/.test(run)) bits += run.length * 0.7;   // mixed case inside
      else if (/[A-Z]/.test(run)) bits += 1;                                           // Capitalised or ALL CAPS
    } else if (/^[0-9]+$/.test(run)) {
      if (/^(19|20)\d\d$/.test(run)) { bits += 6; flags.year = true; }
      else bits += eff * log2(10);
    } else {
      bits += eff * 5;
    }
  });
  bits += Math.max(0, runs.length - 1) * 1.5;   // where the switches between letters, digits and symbols go
  if (core.length >= 4 && COMMON.indexOf(core) >= 0) { bits = Math.min(bits, 18 + (pw.length - core.length) * 2); flags.common = true; }

  if (flags.common) tips.push('It’s built on a very common password.');
  if (pw.length < 12) tips.push('Make it at least 12 characters long.');
  if (flags.pattern) tips.push('Avoid repeats and patterns like 1234, abcd or qwerty.');
  if (flags.year) tips.push('Avoid years and birthdays.');
  if (runs.length === 1 && pw.length < 16) tips.push('Mix in numbers and symbols, or use 4 or more random words.');
  if (!tips.length && bits < 60) tips.push('Longer is stronger: try adding another word.');
  return { bits: bits, tips: tips };
}

function crackTime(bits) {
  var s = Math.pow(2, bits) / 2 / GUESSES_PER_SECOND;   // on average, found halfway through
  var units = [[60, 'second'], [60, 'minute'], [24, 'hour'], [30.4, 'day'], [12, 'month'], [Infinity, 'year']];
  if (s < 1) return 'instantly';
  for (var i = 0; i < units.length; i++) {
    if (s < units[i][0]) {
      var n = Math.round(s);
      if (n > 100000) return 'in more than 100,000 years';
      if (n > 100) n = Number(n.toPrecision(2));
      return 'in about ' + n.toLocaleString() + ' ' + units[i][1] + (n === 1 ? '' : 's');
    }
    s /= units[i][0];
  }
}

var LEVELS = [   // [minimum bits, label, colour]
  [0, 'Very weak', '#e5484d'], [28, 'Weak', '#f0803c'], [40, 'Fair', '#f5c451'], [56, 'Strong', '#46c28b'],
  [72, 'Very strong', '#2bb3a3']
];

// ---- where to show it

function looksLikeLogin(input) {
  if (input.autocomplete === 'new-password') return false;
  if (input.autocomplete === 'current-password') return true;
  var scope = input.form || document;
  if (scope.querySelectorAll('input[type="password"]').length > 1) return false;   // new + confirm
  var hint = (input.name + ' ' + input.id + ' ' + (input.placeholder || '')).toLowerCase();
  if (/new|confirm|create|choose|repeat/.test(hint)) return false;
  var url = location.href.toLowerCase();
  if (/sign-?up|register|join|create|reset|change|new|onboard/.test(url)) return false;
  var formText = (input.form ? input.form.innerText : '').toLowerCase();
  if (/create (an |your )?account|sign up|register/.test(formText)) return false;
  return true;
}

// ---- the meter

var CSS = [
  ':host { all: initial; }',
  '.ui { position: fixed; z-index: 2147483646; box-sizing: border-box; padding: 8px 10px 9px; border-radius: 8px;',
  '  background: #0b2430; color: #e6f4f1; font: 12px/1.4 "Segoe UI", system-ui, sans-serif;',
  '  box-shadow: 0 6px 20px rgba(0,0,0,.25); pointer-events: none; }',
  ':host-context(html[data-pelagic-dark="1"]) .ui { filter: invert(1) hue-rotate(180deg); }',
  '.bars { display: flex; gap: 4px; margin-bottom: 6px; }',
  '.bars i { flex: 1; height: 5px; border-radius: 3px; background: #24414c; transition: background .2s; }',
  '.head { display: flex; justify-content: space-between; gap: 10px; }',
  '.label { font-weight: 600; }',
  '.time { color: #9cbcb7; text-align: right; }',
  '.tip { margin-top: 4px; color: #c9dcd9; }'
].join('\n');

var hostEl = null, ui, bars = [], labelEl, timeEl, tipEl, current = null;

function build() {
  hostEl = document.createElement('pelagic-pwmeter');
  var root = hostEl.attachShadow({ mode: 'closed' });
  try { var sh = new CSSStyleSheet(); sh.replaceSync(CSS); root.adoptedStyleSheets = [sh]; }
  catch (e) { var st = document.createElement('style'); st.textContent = CSS; root.appendChild(st); }
  ui = document.createElement('div'); ui.className = 'ui';
  var barRow = document.createElement('div'); barRow.className = 'bars';
  for (var i = 0; i < 5; i++) { var b = document.createElement('i'); bars.push(b); barRow.appendChild(b); }
  var head = document.createElement('div'); head.className = 'head';
  labelEl = document.createElement('span'); labelEl.className = 'label';
  timeEl = document.createElement('span'); timeEl.className = 'time';
  head.append(labelEl, timeEl);
  tipEl = document.createElement('div'); tipEl.className = 'tip';
  ui.append(barRow, head, tipEl);
  root.appendChild(ui);
}

function place() {
  if (!current || !hostEl || !hostEl.isConnected) return;
  var r = current.getBoundingClientRect();
  if (!r.width) { hide(); return; }
  var w = Math.max(220, Math.min(340, r.width));
  ui.style.width = w + 'px';
  ui.style.left = Math.max(4, Math.min(r.left, innerWidth - w - 4)) + 'px';
  var below = r.bottom + 6, h = ui.offsetHeight || 70;
  ui.style.top = (below + h > innerHeight ? Math.max(4, r.top - h - 6) : below) + 'px';
}

function update() {
  if (!current) return;
  var pw = current.value;
  if (!pw) { if (hostEl) hostEl.remove(); return; }
  if (!hostEl) build();
  if (!hostEl.isConnected) document.documentElement.appendChild(hostEl);
  var a = analyse(pw), level = 0;
  for (var i = 0; i < LEVELS.length; i++) if (a.bits >= LEVELS[i][0]) level = i;
  bars.forEach(function (b, i) { b.style.background = i <= level ? LEVELS[level][2] : ''; });
  labelEl.textContent = LEVELS[level][1];
  labelEl.style.color = LEVELS[level][2];
  timeEl.textContent = 'Cracked ' + crackTime(a.bits);
  tipEl.textContent = a.tips[0] || 'Nice. Use it only on this site.';
  place();
}

function hide() { current = null; if (hostEl) hostEl.remove(); }

document.addEventListener('focusin', function (e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  if (t && t.tagName === 'INPUT' && t.type === 'password' && !looksLikeLogin(t)) { current = t; update(); }
  else if (t !== current) hide();
}, true);
document.addEventListener('input', function (e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  if (t === current) update();   // keeps working if the site's "show password" switch turns it into a text box
}, true);
document.addEventListener('focusout', function (e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  if (t === current) setTimeout(function () { if (document.activeElement !== current) hide(); }, 150);
}, true);
window.addEventListener('scroll', place, true);
window.addEventListener('resize', place);
