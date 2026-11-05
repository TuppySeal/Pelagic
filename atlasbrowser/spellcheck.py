"""Spell check as you type, with suggestions in the right-click menu.

The browser engine needs a dictionary file (.bdic) per language, and Pelagic doesn't ship them, so the first time
spell check is turned on for a language its dictionary is downloaded from Chromium's own dictionary repository
into <data>/dictionaries. QTWEBENGINE_DICTIONARIES_PATH must point there before the engine starts (see
prepare_environment), so a newly downloaded dictionary may only take effect after a restart.

Settings: "spellcheck" (on/off) and "spellcheck_lang" (e.g. "en-US").
"""
from __future__ import annotations

import base64
import os
import urllib.request
from pathlib import Path

from .store import data_dir

# language code -> (name shown, file in Chromium's hunspell_dictionaries repository)
LANGUAGES = {
    "en-US": ("English (US)", "en-US-10-1"),
    "en-GB": ("English (UK)", "en-GB-10-1"),
    "es-ES": ("Spanish", "es-ES-3-0"),
    "fr-FR": ("French", "fr-FR-3-0"),
    "de-DE": ("German", "de-DE-3-0"),
    "pt-BR": ("Portuguese (Brazil)", "pt-BR-3-0"),
    "it-IT": ("Italian", "it-IT-3-0"),
    "nl-NL": ("Dutch", "nl-NL-3-0"),
    "pl-PL": ("Polish", "pl-PL-3-0"),
    "ru-RU": ("Russian", "ru-RU-3-0"),
}
SOURCE = "https://chromium.googlesource.com/chromium/deps/hunspell_dictionaries/+/main/{}.bdic?format=TEXT"


def folder() -> Path:
    return data_dir() / "dictionaries"


def prepare_environment():
    """Call before the browser engine starts."""
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QTWEBENGINE_DICTIONARIES_PATH", str(d))


def have(lang: str) -> bool:
    return (folder() / f"{lang}.bdic").exists()


def download(lang: str, timeout: float = 60) -> Path:
    """Fetches one dictionary (runs off the UI thread). Raises OSError on failure."""
    name = LANGUAGES[lang][1]
    req = urllib.request.Request(SOURCE.format(name), headers={"User-Agent": "Pelagic/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = base64.b64decode(resp.read())
    if data[:4] != b"BDic":
        raise OSError("the dictionary file wasn't in the expected format")
    path = folder() / f"{lang}.bdic"
    folder().mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def apply(store, profiles):
    """Turn spell check on or off for these engine profiles, as the settings say."""
    lang = store.get("spellcheck_lang") or "en-US"
    on = bool(store.get("spellcheck")) and have(lang)
    for p in profiles:
        if on:
            p.setSpellCheckLanguages([lang])
        p.setSpellCheckEnabled(on)


def ensure(store, profiles, notify=None):
    """Settings changed: apply them, downloading the dictionary first if it's missing."""
    lang = store.get("spellcheck_lang") or "en-US"
    if not store.get("spellcheck") or have(lang):
        apply(store, profiles)
        return
    from .agent import run_in_pool
    if notify:
        notify(f"Downloading the {LANGUAGES.get(lang, (lang,))[0]} spelling dictionary…")

    def done(_tok, out):
        if isinstance(out, Exception):
            if notify:
                notify(f"Couldn't download the spelling dictionary ({out}). Spell check stays off for now.")
            return
        apply(store, profiles)
        if notify:
            notify("Spell check is on. If misspelled words aren't underlined yet, restart Pelagic.")
    run_in_pool(0, lambda: download(lang), done)
