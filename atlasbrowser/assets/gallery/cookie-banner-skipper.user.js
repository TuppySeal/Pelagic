// ==UserScript==
// @name        Cookie Banner Skipper
// @description Answers cookie pop-ups for you by choosing "Reject all" or "Only necessary". Works with OneTrust, Cookiebot, Didomi, Quantcast, Usercentrics, Google and many more.
// @version     1.0
// @match       *://*/*
// @run-at      document-end
// ==/UserScript==

// Pelagic sites field: leave empty (every site)
//
// It never clicks "Accept". If a banner only offers Accept, it's left alone so you can decide.
// Runs inside frames too, because some consent pop-ups (Sourcepoint, TrustArc) are a frame from another site.
// Pause it for one site from the puzzle menu.

if (GM_getValue('cookie-skip-off', false)) {
  if (window.top === window) GM_registerMenuCommand('Turn on for this site', function () {
    GM_setValue('cookie-skip-off', false); location.reload();
  });
  return;
}

// Buttons of the common consent platforms that mean "reject" or "only necessary".
var KNOWN = [
  '#onetrust-reject-all-handler', '.ot-pc-refuse-all-handler',
  '#CybotCookiebotDialogBodyButtonDecline', '#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll',
  '#didomi-notice-disagree-button', '.didomi-continue-without-agreeing',
  '.qc-cmp2-summary-buttons button[mode="secondary"]',
  '#truste-consent-required', '.truste-button2',
  '[data-testid="uc-deny-all-button"]',
  '.iubenda-cs-reject-btn', '.osano-cm-denyAll', '.cmplz-deny', '.cky-btn-reject',
  '[data-tid="banner-decline"]', '.cm-btn-decline', '.cc-deny', '.cc-btn.cc-dismiss[aria-label*="deny" i]',
  '#cookiescript_reject', '.js-cookie-consent-reject', '[data-cookiefirst-action="reject"]',
  '.fc-cta-do-not-consent', 'button.sp_choice_type_REJECT_ALL', 'button[title="Reject All" i]',
  'form[action*="consent.google"] button[aria-label^="Reject" i]', 'button[aria-label="Reject all" i]',
  '[data-action="reject"][data-consent]', '#tarteaucitronAllDenied2', '.moove-gdpr-infobar-reject-btn',
  '#wt-cli-reject-btn', '.termly-styles-decline'
];

// Button wording that means reject, in a few languages. Must be the whole label (trimmed).
var REJECT = new RegExp('^(' + [
  'reject( all)?( cookies)?', 'decline( all)?( cookies)?', 'deny( all)?', 'refuse( all)?', 'disagree',
  '(use |allow )?(only )?(strictly )?(necessary|essential|required)( cookies)?( only)?',
  'continue without (accepting|agreeing)', 'no,? thanks', 'i do not accept', 'do not consent',
  'alle ablehnen', 'ablehnen', 'nur (notwendige|erforderliche|essenzielle)( cookies)?', 'tout refuser', 'refuser',
  'continuer sans accepter', 'rechazar( todo| todas)?', 'solo necesarias', 'rifiuta( tutto)?',
  'alles weigeren', 'weigeren', 'rejeitar( tudo)?', 'odrzuć( wszystkie)?', 'avvisa alla', 'avvis alle', 'afvis alle'
].join('|') + ')[.!]?$', 'i');

// Text that tells us a box is about cookies, so a "Decline" button elsewhere on the page is never touched.
var ABOUT = /cookie|consent|gdpr|privacy|tracking|personal data|datenschutz|confidentialit|privacidad/i;

var clicked = new WeakSet(), clicks = 0, done = false;

function visible(e) {
  if (!e || !e.getClientRects().length) return false;
  var s = getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05;
}

function label(e) {
  return (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
}

// Is this button inside something that looks like a consent pop-up?
function inConsentBox(e) {
  for (var n = e, i = 0; n && i < 12; i++, n = n.parentElement || (n.getRootNode && n.getRootNode().host)) {
    if (n === document.body || n === document.documentElement) break;
    var tag = (n.id + ' ' + (typeof n.className === 'string' ? n.className : '')).toLowerCase();
    if (/cookie|consent|cmp|gdpr|privacy|onetrust|didomi|usercentrics|sp_message/.test(tag)) return true;
    if (n.getAttribute && (n.getAttribute('role') === 'dialog' || n.getAttribute('aria-modal') === 'true' ||
        /fixed|sticky/.test(getComputedStyle(n).position))) return ABOUT.test(n.innerText || '');
  }
  // a consent frame from another site: the whole frame is the pop-up
  return window.top !== window && ABOUT.test(document.body ? document.body.innerText.slice(0, 3000) : '');
}

function press(e, why) {
  if (clicked.has(e) || clicks >= 4) return false;
  clicked.add(e);
  clicks++;
  e.click();
  console.log('[Cookie Banner Skipper] ' + why + ': "' + label(e) + '"');
  return true;
}

// Search the page and any open shadow roots (Usercentrics and others put their banner in one).
function roots() {
  var out = [document];
  document.querySelectorAll('#usercentrics-root, #usercentrics-cmp-ui, [id^="cmpwrapper"], aside[id*="consent"]')
    .forEach(function (h) { if (h.shadowRoot) out.push(h.shadowRoot); });
  return out;
}

function scan() {
  if (done) return;
  var rs = roots();
  for (var r = 0; r < rs.length; r++) {
    for (var i = 0; i < KNOWN.length; i++) {
      var k = rs[r].querySelector(KNOWN[i]);
      if (k && visible(k) && press(k, 'Rejected')) { finish(); return; }
    }
  }
  for (r = 0; r < rs.length; r++) {
    var btns = rs[r].querySelectorAll('button, [role="button"], a[href="#"], a:not([href]), input[type="button"], input[type="submit"]');
    for (var j = 0; j < btns.length; j++) {
      var b = btns[j], text = label(b);
      if (text.length > 45 || !REJECT.test(text) || !visible(b) || !inConsentBox(b)) continue;
      if (press(b, 'Rejected')) { finish(); return; }
    }
  }
}

function finish() {
  // Some pop-ups have a second "save my choices" step after Reject; give it a moment, then look once more.
  setTimeout(function () { done = false; scan(); done = true; unlockScroll(); }, 900);
  done = true;
}

// Pages sometimes leave scrolling turned off after their banner closes.
function unlockScroll() {
  [document.documentElement, document.body].forEach(function (n) {
    var tall = document.documentElement.scrollHeight > innerHeight + 50;   // app-style pages scroll inside instead
    if (n && tall && getComputedStyle(n).overflow === 'hidden' && !document.querySelector('[aria-modal="true"]:not([hidden])'))
      n.style.setProperty('overflow', 'auto', 'important');
  });
}

var pending = false;
var obs = new MutationObserver(function () {
  if (pending || done) return;
  pending = true;
  setTimeout(function () { pending = false; scan(); }, 250);
});
scan();
if (!done) {
  obs.observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(function () { obs.disconnect(); }, 20000);   // banners show up in the first few seconds
}

if (window.top === window) GM_registerMenuCommand('Pause on this site', function () {
  GM_setValue('cookie-skip-off', true);
  obs.disconnect();
  done = true;
});
