"""Dark mode for websites, done by the browser engine itself.

The built-in "Dark mode for websites" extension used to be a userscript (assets/darkmode.user.js) that put a CSS
filter (invert + hue-rotate) on the whole page and on every photo. A filter on <html> makes Chromium redraw the
entire page through the filter on every scroll and animation, and each filtered photo becomes its own layer, so
long pages, feeds and image-heavy sites got laggy. Chromium has its own dark mode for web pages (Qt's
ForceDarkMode setting, Qt 6.7+): it darkens colours while painting, leaves photos alone and costs next to nothing.
Pelagic now uses that, and keeps the userscript only for a Qt without it.

The extension still shows in the extensions (puzzle) menu and Manage extensions, where it's turned on and off.
Chromium only uses the new setting when a page is next drawn from scratch (on some graphics cards an open page
keeps its old look until it's reloaded), so pages whose dark mode changes are reloaded. Sites it's turned off for are kept in the profile's settings ("darkmode_off_sites"); sites turned off with the old
script's menu are picked up from that site's storage the next time it's opened.
"""
from __future__ import annotations

import json
import os
import weakref

from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings

SOURCE = "pelagic:darkmode"          # the built-in extension's source address (see app.py)
OFF_SITES = "darkmode_off_sites"
OLD_OFF_KEY = "darkmode-off"         # the userscript's GM_setValue key
FORCE_DARK = getattr(QWebEngineSettings.WebAttribute, "ForceDarkMode", None)
# PELAGIC_DARKMODE_SCRIPT=1 brings back the old userscript (for comparing)
NATIVE = FORCE_DARK is not None and os.environ.get("PELAGIC_DARKMODE_SCRIPT") != "1"


def builtin(extensions) -> dict | None:
    return next((e for e in getattr(extensions, "items", []) if e.get("source") == SOURCE), None)


def enabled(extensions) -> bool:
    ext = builtin(extensions)
    return bool(ext and ext.get("enabled", True))


def _site(host: str) -> str:
    host = (host or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def site_off(store, host: str) -> bool:
    """Turned off for this site (or a site it's part of: off for example.com covers mail.example.com)."""
    host = _site(host)
    if not host or store is None:
        return False
    off = store.get(OFF_SITES) or []
    parts = host.split(".")
    return any(".".join(parts[i:]) in off for i in range(len(parts)))


def set_site_off(store, host: str, off: bool):
    host = _site(host)
    if not host:
        return
    sites = [h for h in (store.get(OFF_SITES) or []) if h != host]
    if off:
        sites.append(host)
    store.set(OFF_SITES, sites)


_PAGES = weakref.WeakSet()   # open pages (webview.WebPage registers itself), to reload when dark mode changes


def track(page):
    _PAGES.add(page)


def _live_pages(profile=None):
    out = []
    for p in list(_PAGES):
        try:
            if profile is None or p.profile() is profile:
                out.append(p)
        except RuntimeError:   # closed
            _PAGES.discard(p)
    return out


def _redraw(page, was_dark: bool):
    """A page that's already showing and whose dark mode changed is reloaded, so it changes at once. Sleeping
    tabs are left asleep (they load fresh when woken), and pages that aren't websites are left alone."""
    try:
        if page_is_dark(page) == was_dark or page.url().scheme() not in ("http", "https"):
            return
        if page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
            return
        page.triggerAction(QWebEnginePage.WebAction.Reload)
    except RuntimeError:
        pass


def apply_profile(profile, on: bool):
    """The profile-wide default: dark when the extension is on. Open pages that follow it are redrawn."""
    if not NATIVE:
        return
    s = profile.settings()
    if s.testAttribute(FORCE_DARK) == bool(on):
        return
    before = [(p, page_is_dark(p)) for p in _live_pages(profile)]
    s.setAttribute(FORCE_DARK, bool(on))
    for p, was in before:
        _redraw(p, was)


def apply_page(page, url, store):
    """Per page, before each main-frame navigation: Pelagic's own pages (start page, reader, files) and sites it's
    turned off for stay as they are; everything else follows the profile."""
    if not NATIVE:
        return
    s = page.settings()
    if url.scheme() not in ("http", "https") or site_off(store, url.host()):
        s.setAttribute(FORCE_DARK, False)
    else:
        s.resetAttribute(FORCE_DARK)


def page_is_dark(page) -> bool:
    return bool(NATIVE and page.settings().testAttribute(FORCE_DARK))


def migrate_js(ext_id: str) -> str:
    """Reads (and clears) the old script's per-site switch from the site's own storage."""
    key = json.dumps(f"__wf_gm_{ext_id}_{OLD_OFF_KEY}")
    return (f"(function(){{try{{var v=localStorage.getItem({key});if(v===null)return null;"
            f"localStorage.removeItem({key});return v;}}catch(e){{return null;}}}})()")


def migrate_page(tab, store, extensions):
    """After a site loads: if it had been turned off with the old script, keep it off."""
    ext = builtin(extensions)
    page = tab.page()
    url = page.url()
    if not NATIVE or ext is None or store is None or url.scheme() not in ("http", "https"):
        return

    def got(value):
        if value == "true" and not site_off(store, url.host()):
            set_site_off(store, url.host(), True)
            try:
                was = page_is_dark(page)
                apply_page(page, page.url(), store)
            except RuntimeError:   # the tab closed meanwhile
                return
            _redraw(page, was)
    page.runJavaScript(migrate_js(ext["id"]), QWebEngineScript.ScriptWorldId.ApplicationWorld, got)


def refresh_tabs(tabs, store):
    """After a per-site switch: every open tab of that site follows it right away."""
    for t in tabs:
        try:
            page = t.page()
            was = page_is_dark(page)
            apply_page(page, page.url(), store)
        except RuntimeError:
            continue
        _redraw(page, was)
