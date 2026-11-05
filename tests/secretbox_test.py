"""Encryption of saved secrets off Windows (atlasbrowser/secretbox.py), checked on any system: the Linux path is
forced and the system keyring is replaced by an in-memory fake, so your real keyring is never touched.

Run:  python tests/secretbox_test.py
"""
import base64
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_secretbox_test_")
os.environ.pop("PELAGIC_PASSWORD_STORE", None)

from atlasbrowser import secretbox  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def fresh_home():
    os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_secretbox_test_")
    secretbox.forget_key()
    return Path(os.environ["ATLASBROWSER_HOME"])


# -------- a fake `keyring` package: a working backend, or none at all
class FakeKeyring:
    def __init__(self):
        self.items, self.locked = {}, False

    def get_password(self, service, user):
        if self.locked:
            raise RuntimeError("keyring is locked")
        return self.items.get((service, user))

    def set_password(self, service, user, value):
        self.items[(service, user)] = value


class _Fail:
    pass


def install_keyring(backend):
    fake = types.ModuleType("keyring")
    backends = types.ModuleType("keyring.backends")
    fail = types.ModuleType("keyring.backends.fail")
    fail.Keyring = _Fail
    fake.backends, backends.fail = backends, fail
    fake.get_keyring = lambda: backend if backend is not None else _Fail()
    fake.get_password = lambda s, u: backend.get_password(s, u)
    fake.set_password = lambda s, u, v: backend.set_password(s, u, v)
    sys.modules.update({"keyring": fake, "keyring.backends": backends, "keyring.backends.fail": fail})


if sys.platform == "win32":
    check("Windows still uses DPAPI", secretbox.unprotect(secretbox.protect(b"dpapi")) == b"dpapi"
          and secretbox.protect(b"dpapi")[:3] != b"PS1")
secretbox._use_dpapi = lambda: False   # from here on: the Linux behaviour

# -------- with a keyring
kr = FakeKeyring()
install_keyring(kr)
home = fresh_home()
sealed = secretbox.protect(b'{"openai": "sk-test-123"}')
check("sealed data is not plain text", b"sk-test-123" not in sealed)
check("round trip", secretbox.unprotect(sealed) == b'{"openai": "sk-test-123"}')
check("the key is in the keyring", (secretbox.KEYRING_SERVICE, secretbox.KEYRING_USER) in kr.items)
check("no key file when the keyring is used", not (home / "secretbox.key").exists())
check("backend remembered", (home / "secretbox.backend").read_text() == "keyring")
check("UI says keyring", "keyring" in secretbox.where())
secretbox.forget_key()
check("same key after a restart", secretbox.unprotect(sealed) == b'{"openai": "sk-test-123"}')
tampered = sealed[:-1] + bytes([sealed[-1] ^ 1])
try:
    secretbox.unprotect(tampered)
    check("tampering is detected", False)
except ValueError:
    check("tampering is detected", True)
check("old plain-JSON files still load", secretbox.unprotect(b'{"a": 1}') == b'{"a": 1}')

# API keys through Store, then a locked keyring: nothing may be overwritten
from atlasbrowser.store import Store  # noqa: E402
store = Store()
store.set_key("openai", "sk-test-abc")
check("keys.dat is encrypted", b"sk-test-abc" not in base64.b64decode((store.root / "keys.dat").read_bytes()))
check("API key round trip", Store(store.root).get_key("openai") == "sk-test-abc")
secretbox.forget_key()
kr.locked = True
locked = Store(store.root)
check("locked keyring: key reads as empty", locked.get_key("openai") == "")
try:
    locked.set_key("anthropic", "sk-ant")
    check("locked keyring: saving refuses", False)
except secretbox.KeyringMissing:
    check("locked keyring: saving refuses", True)
kr.locked = False
check("unlocked again: nothing was lost", Store(store.root).get_key("openai") == "sk-test-abc")
locked.set_key("anthropic", "sk-ant")
both = Store(store.root)
check("saving after unlocking keeps the other keys", both.get_key("openai") == "sk-test-abc"
      and both.get_key("anthropic") == "sk-ant")

# -------- without a keyring: refuse, never plain text
install_keyring(None)
home = fresh_home()
check("available() explains the missing keyring", "keyring" in secretbox.available())
try:
    secretbox.protect(b"secret")
    check("no keyring: refuses to save", False)
except secretbox.KeyringMissing:
    check("no keyring: refuses to save", True)
check("no keyring: no key file made", not (home / "secretbox.key").exists())

# -------- a keyring that disappears later: never start over with a new key
install_keyring(kr)
home = fresh_home()
sealed = secretbox.protect(b"x")
install_keyring(None)
secretbox.forget_key()
try:
    secretbox.unprotect(sealed)
    check("keyring gone later: refuses (no new key)", False)
except secretbox.KeyringMissing:
    check("keyring gone later: refuses (no new key)", True)

# -------- PELAGIC_PASSWORD_STORE=basic: a key file only the user can read
os.environ["PELAGIC_PASSWORD_STORE"] = "basic"
home = fresh_home()
check("basic: available", secretbox.available() == "")
sealed = secretbox.protect(b"card 4242")
key_file = home / "secretbox.key"
check("basic: key file made", key_file.exists() and (home / "secretbox.backend").read_text() == "file")
if os.name == "posix":
    check("basic: key file is mode 600", (key_file.stat().st_mode & 0o777) == 0o600, oct(key_file.stat().st_mode))
secretbox.forget_key()
check("basic: round trip after restart", secretbox.unprotect(sealed) == b"card 4242")
check("basic: UI says key file", "key file" in secretbox.where())
os.environ.pop("PELAGIC_PASSWORD_STORE")
secretbox.forget_key()
check("basic stays basic without the variable", secretbox.unprotect(sealed) == b"card 4242")

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
sys.exit(1 if failed else 0)
