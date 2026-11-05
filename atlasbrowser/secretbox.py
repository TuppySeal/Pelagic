"""Encryption for what Pelagic saves on this computer: API keys (keys.dat), passwords (passwords.dat) and addresses
and cards (autofill.dat).

Windows: DPAPI, tied to the Windows account (unchanged from earlier versions).
Linux and other systems: encrypted with a random key (the sync vault's encrypt-then-MAC cipher, standard library
only). The key lives in the system keyring (Secret Service: GNOME Keyring, KWallet, KeePassXC) through the
`keyring` package. Without a keyring nothing secret is saved (protect raises KeyringMissing) unless
PELAGIC_PASSWORD_STORE=basic is set; then the key is a file only your user can read (<data folder>/secretbox.key,
mode 600), like Chrome's "basic" store. Which of the two was used is remembered in <data folder>/secretbox.backend,
so a keyring that is locked or missing later never makes Pelagic start over with a new key.
"""
from __future__ import annotations

import base64
import ctypes
import os
import sys
import threading

KEYRING_SERVICE = "Pelagic"
KEYRING_USER = "secretbox key"
_lock = threading.Lock()
_key: bytes | None = None


class KeyringMissing(RuntimeError):
    pass


# ---------------------------------------------------------------- Windows
def _dpapi(data: bytes, protect: bool) -> bytes:
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = (ctypes.byref(blob_in), "AtlasBrowser", None, None, None, 0, ctypes.byref(blob_out)) if protect else \
        (ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not fn(*args):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _use_dpapi() -> bool:
    return sys.platform == "win32"


# ---------------------------------------------------------------- everywhere else
def _root():
    from .store import data_dir
    return data_dir()


def _backend_file():
    return _root() / "secretbox.backend"


def _wanted() -> str:
    """'keyring' or 'basic' (PELAGIC_PASSWORD_STORE), for the first time a key is made."""
    return "basic" if os.environ.get("PELAGIC_PASSWORD_STORE", "").strip().lower() == "basic" else "keyring"


def _keyring():
    """The keyring module if a real (Secret Service, KWallet...) backend is available, else None."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    try:
        kr = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(kr, fail.Keyring) or "null" in type(kr).__module__ or "fail" in type(kr).__module__:
        return None
    return keyring


def _keyring_key(create: bool) -> bytes | None:
    kr = _keyring()
    if kr is None:
        return None
    stored = kr.get_password(KEYRING_SERVICE, KEYRING_USER)
    if stored:
        return base64.b64decode(stored)
    if not create:
        return None
    key = os.urandom(64)
    kr.set_password(KEYRING_SERVICE, KEYRING_USER, base64.b64encode(key).decode("ascii"))
    return key


def _file_key(create: bool) -> bytes | None:
    path = _root() / "secretbox.key"
    try:
        return base64.b64decode(path.read_bytes())
    except FileNotFoundError:
        if not create:
            return None
    key = os.urandom(64)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(base64.b64encode(key))
    return key


def _load_key() -> bytes:
    marker = _backend_file()
    try:
        used = marker.read_text().strip()
    except OSError:
        used = ""
    if used == "keyring" or (not used and _wanted() == "keyring"):
        try:
            key = _keyring_key(create=not used)
        except Exception as e:
            raise KeyringMissing(f"The system keyring couldn't be used ({e}).") from e
        if key is None:
            if used:
                raise KeyringMissing("Pelagic's encryption key is kept in the system keyring, which isn't available "
                                     "right now. Unlock or start your keyring (GNOME Keyring, KWallet) and try again.")
            raise KeyringMissing("No system keyring was found, so Pelagic won't save passwords, cards or API keys. "
                                 "Install and start GNOME Keyring or KWallet (and the Python 'keyring' package), or "
                                 "start Pelagic with PELAGIC_PASSWORD_STORE=basic to keep the key in a file only "
                                 "your user can read.")
    else:
        key = _file_key(create=not used)
        if key is None:
            raise KeyringMissing("Pelagic's encryption key file (secretbox.key) is missing.")
        used = used or "file"
    if not marker.exists():
        marker.write_text("keyring" if used != "file" else "file")
    return key


def _master_key() -> bytes:
    global _key
    with _lock:
        if _key is None:
            _key = _load_key()
        return _key


def forget_key():
    """Drop the cached key (tests, or after the data folder changes)."""
    global _key
    with _lock:
        _key = None


# ---------------------------------------------------------------- API
def protect(data: bytes) -> bytes:
    if _use_dpapi():
        return _dpapi(data, True)
    from .sync import seal
    return base64.b64decode(seal(data, _master_key()))


def unprotect(raw: bytes) -> bytes:
    if _use_dpapi():
        return _dpapi(raw, False)
    if raw.lstrip()[:1] in (b"{", b"["):
        return raw   # plain JSON from an earlier non-Windows build (tests only); encrypted on the next save
    from .sync import unseal
    return unseal(base64.b64encode(raw).decode("ascii"), _master_key())


def available() -> str:
    """'' when secrets can be saved, else why not (without unlocking or creating anything)."""
    if _use_dpapi():
        return ""
    try:
        used = _backend_file().read_text().strip()
    except OSError:
        used = ""
    if used == "file" or (not used and _wanted() == "basic"):
        return ""
    if _keyring() is None:
        return ("No system keyring was found, so Pelagic won't save passwords, cards or API keys. Install and start "
                "GNOME Keyring or KWallet, or start Pelagic with PELAGIC_PASSWORD_STORE=basic to keep the key in a "
                "file only your user can read.")
    return ""


def where() -> str:
    """How saved secrets are protected, for notes in the UI ("encrypted with ...")."""
    if _use_dpapi():
        return "your Windows account"
    try:
        used = _backend_file().read_text().strip()
    except OSError:
        used = "file" if _wanted() == "basic" else "keyring"
    return "a key file only your user can read" if used == "file" else "a key in your system keyring"
