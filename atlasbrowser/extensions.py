"""Pelagic extensions: userscripts (Greasy Fork / OpenUserJS / Tampermonkey format) and the user's own site
scripts and styles, kept per profile. Scripts are injected with QWebEngineScript, which understands the
==UserScript== @match/@include/@exclude/@run-at header itself; a small GM_* shim covers the common API.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
import uuid
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineScript

from . import darkmode

GREASY_FORK = "https://greasyfork.org/en/scripts"
_HEADER = re.compile(r"//\s*==UserScript==(.*?)//\s*==/UserScript==", re.S)
_META = re.compile(r"^\s*//\s*@([\w:-]+)(?:\s+(.*?))?\s*$", re.M)
MULTI = {"match", "include", "exclude", "exclude-match", "require", "grant", "connect", "resource"}


def parse_meta(code: str) -> dict:
    m = _HEADER.search(code)
    meta: dict = {k: [] for k in MULTI}
    if not m:
        return meta
    for key, value in _META.findall(m.group(1)):
        key, value = key.lower(), (value or "").strip()
        if key in MULTI:
            meta[key].append(value)
        elif ":" not in key or key not in meta:   # keep the first (default-locale) name/description
            meta.setdefault(key, value)
    return meta


def header_for(name: str, sites: list[str], run_at: str = "document-end", description: str = "") -> str:
    lines = ["// ==UserScript==", f"// @name        {name}"]
    if description:
        lines.append(f"// @description {description}")
    lines += [f"// @match       {s}" for s in sites] or ["// @match       *://*/*"]
    lines += [f"// @run-at      {run_at}", "// ==/UserScript==", ""]
    return "\n".join(lines)


def site_patterns(text: str) -> list[str]:
    """'example.com' -> the site and its subdomains; full match patterns pass through."""
    t = text.strip()
    if t in ("<all_urls>", "*"):
        return ["*://*/*"]
    if "://" in t:
        return [t]
    t = t.strip("/").removeprefix("www.")
    return [f"*://{t}/*", f"*://*.{t}/*"]


def _version_tuple(v: str):
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v or "0"))


_SHIM = r"""
var __wfId = %(id)s, __wfKey = '__wf_gm_' + __wfId + '_';
var unsafeWindow = window;
var GM_info = { script: %(info)s, scriptHandler: 'Pelagic', version: '1.0' };
function GM_addStyle(css) { var s = document.createElement('style'); s.textContent = css;
  (function put() { var p = document.head || document.documentElement;
    if (p) p.appendChild(s); else document.addEventListener('readystatechange', put, { once: true }); })();
  return s; }
function GM_getValue(k, d) { try { var v = localStorage.getItem(__wfKey + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }
function GM_setValue(k, v) { try { localStorage.setItem(__wfKey + k, JSON.stringify(v)); } catch (e) {} }
function GM_deleteValue(k) { try { localStorage.removeItem(__wfKey + k); } catch (e) {} }
function GM_listValues() { var out = []; try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i);
  if (k.indexOf(__wfKey) === 0) out.push(k.slice(__wfKey.length)); } } catch (e) {} return out; }
function GM_openInTab(url) { return window.open(url, '_blank'); }
function GM_setClipboard(t) { try { navigator.clipboard.writeText(String(t)); } catch (e) {} }
function GM_notification(d) { console.log('[Pelagic] ' + (typeof d === 'string' ? d : d && d.text)); }
function GM_log(m) { console.log(m); }
function GM_registerMenuCommand(caption, fn) {
  var m = window.__wfMenu = window.__wfMenu || {}; (m[__wfId] = m[__wfId] || []).push({ caption: String(caption), fn: fn });
  return m[__wfId].length - 1; }
function GM_unregisterMenuCommand(id) {
  var c = (window.__wfMenu || {})[__wfId]; if (c && c[id]) c[id] = null; }   // keeps the other commands' numbers
function GM_xmlhttpRequest(d) {   // same-site requests only: Pelagic doesn't give scripts cross-site network access
  var x = new XMLHttpRequest(); x.open(d.method || 'GET', d.url, true);
  for (var h in (d.headers || {})) try { x.setRequestHeader(h, d.headers[h]); } catch (e) {}
  if (d.responseType) x.responseType = d.responseType;
  x.onload = function () { d.onload && d.onload({ status: x.status, statusText: x.statusText, responseText: x.responseType ? '' : x.responseText,
    response: x.response, responseHeaders: x.getAllResponseHeaders(), finalUrl: x.responseURL }); };
  x.onerror = function (e) { d.onerror && d.onerror(e); }; x.send(d.data || null); return { abort: function () { x.abort(); } }; }
var GM = { info: GM_info, addStyle: GM_addStyle, openInTab: GM_openInTab, setClipboard: GM_setClipboard,
  notification: GM_notification, registerMenuCommand: GM_registerMenuCommand, xmlHttpRequest: GM_xmlhttpRequest,
  getValue: function (k, d) { return Promise.resolve(GM_getValue(k, d)); },
  setValue: function (k, v) { return Promise.resolve(GM_setValue(k, v)); },
  deleteValue: function (k) { return Promise.resolve(GM_deleteValue(k)); },
  listValues: function () { return Promise.resolve(GM_listValues()); } };
"""

_MENU_JS = """(function(){var m=window.__wfMenu||{},o=[];for(var id in m)m[id].forEach(function(c,i){if(c)o.push([id,i,c.caption]);});
return JSON.stringify(o);})()"""


class Extensions:
    """One profile's extensions: index.json plus one .user.js file each, under <profile>/extensions."""

    def __init__(self, root: Path):
        self.folder = Path(root) / "extensions"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.index_path = self.folder / "index.json"
        try:
            self.items: list[dict] = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []
        self._profiles = []   # web engine profiles the scripts are installed into
        self._inserted: dict[int, list] = {}

    # -- storage
    def _save(self):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def code(self, ext: dict) -> str:
        try:
            return (self.folder / f"{ext['id']}.user.js").read_text(encoding="utf-8")
        except OSError:
            return ""

    def get(self, ext_id: str) -> dict | None:
        return next((e for e in self.items if e["id"] == ext_id), None)

    def install(self, code: str, source_url: str = "", kind: str = "userscript", requires: dict | None = None,
                ext_id: str | None = None) -> dict:
        meta = parse_meta(code)
        existing = self.get(ext_id) if ext_id else next(
            (e for e in self.items if source_url and e.get("source") == source_url), None)
        ext = existing or {"id": uuid.uuid4().hex[:12], "enabled": True, "installed": time.time()}
        ext.update({"name": meta.get("name") or "Untitled script", "description": meta.get("description", ""),
                    "version": meta.get("version", ""), "kind": kind, "source": source_url or ext.get("source", ""),
                    "sites": meta["match"] + meta["include"], "updated": time.time()})
        (self.folder / f"{ext['id']}.user.js").write_text(code, encoding="utf-8")
        if requires is not None:
            (self.folder / f"{ext['id']}.requires.json").write_text(json.dumps(requires), encoding="utf-8")
        if existing is None:
            self.items.append(ext)
        self._save()
        self.apply()
        return ext

    def set_enabled(self, ext_id: str, on: bool):
        ext = self.get(ext_id)
        if ext:
            ext["enabled"] = bool(on)
            self._save()
            self.apply()

    def remove(self, ext_id: str):
        self.items = [e for e in self.items if e["id"] != ext_id]
        for suffix in (".user.js", ".requires.json"):
            (self.folder / f"{ext_id}{suffix}").unlink(missing_ok=True)
        self._save()
        self.apply()

    def _requires(self, ext: dict) -> dict:
        try:
            return json.loads((self.folder / f"{ext['id']}.requires.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # -- injection
    def attach_profile(self, web_profile):
        self._profiles.append(web_profile)
        self.apply()

    def build_source(self, ext: dict) -> str:
        code = self.code(ext)
        m = _HEADER.search(code)
        header = m.group(0) if m else header_for(ext["name"], ["*://*/*"])
        body = code[m.end():] if m else code
        info = json.dumps({"name": ext["name"], "version": ext.get("version", ""),
                           "description": ext.get("description", "")})
        shim = _SHIM % {"id": json.dumps(ext["id"]), "info": info}
        reqs = "\n;\n".join(self._requires(ext).values())
        return f"{header}\n(function () {{\n{shim}\ntry {{\n{reqs}\n;\n{body}\n}} catch (e) {{ " \
               f"console.error({json.dumps('[Pelagic] ' + ext['name'] + ' failed:')}, e); }}\n}})();\n"

    def apply(self):
        for prof in self._profiles:
            coll = prof.scripts()
            # Qt renames a script after its @name, so remember what we inserted instead of matching names.
            for s in self._inserted.pop(id(prof), []):
                coll.remove(s)
            inserted = self._inserted[id(prof)] = []
            darkmode.apply_profile(prof, darkmode.enabled(self))
            for ext in self.items:
                if not ext.get("enabled", True):
                    continue
                if darkmode.NATIVE and ext.get("source") == darkmode.SOURCE:
                    continue   # the browser engine does dark mode itself (darkmode.py); the script was slow
                code = self.code(ext)
                meta = parse_meta(code)
                s = QWebEngineScript()
                s.setName("wayfinder-ext-" + ext["id"])
                s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                s.setRunsOnSubFrames("noframes" not in meta)
                s.setSourceCode(self.build_source(ext))   # Qt reads @match/@include/@exclude/@run-at from the header
                coll.insert(s)
                inserted.append(s)

    # -- network (install and updates)
    @staticmethod
    def fetch(url: str) -> str:
        # Script addresses often hold spaces and other characters as typed (Greasy Fork puts the script's name in
        # them: "…/All-in-One Video Downloader – HD.user.js"); send them percent-encoded, keeping existing %XX.
        url = bytes(QUrl(url).toEncoded()).decode("ascii")
        req = urllib.request.Request(url, headers={"User-Agent": "Pelagic/1.0"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")

    def fetch_with_requires(self, url: str) -> tuple[str, dict]:
        code = self.fetch(url)
        if not _HEADER.search(code):
            raise ValueError("That address doesn't contain a userscript.")
        reqs = {}
        for r in parse_meta(code)["require"]:
            if r.startswith("https://"):
                reqs[r] = self.fetch(r)
        return code, reqs

    def check_update(self, ext: dict):
        """Returns (code, requires) for a newer version, or None."""
        meta = parse_meta(self.code(ext))
        url = meta.get("updateurl") or meta.get("downloadurl") or ext.get("source")
        if not url or not url.startswith("https://"):
            return None
        code = self.fetch(url)
        new = parse_meta(code)
        if _version_tuple(new.get("version", "")) <= _version_tuple(meta.get("version", "")):
            return None
        if url.endswith(".meta.js"):
            code, reqs = self.fetch_with_requires(meta.get("downloadurl") or ext["source"])
        else:
            reqs = {r: self.fetch(r) for r in new["require"] if r.startswith("https://")}
        return code, reqs


def is_userscript_url(url: QUrl) -> bool:
    return url.scheme() == "https" and url.path().endswith(".user.js")


def menu_commands_js() -> str:
    return _MENU_JS


def run_menu_command_js(ext_id: str, index: int) -> str:
    return f"(function(){{var c=(window.__wfMenu||{{}})[{json.dumps(ext_id)}];c&&c[{int(index)}]&&c[{int(index)}].fn();}})()"
