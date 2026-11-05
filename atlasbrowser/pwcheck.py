"""Password checkup: leaked (found in known data breaches), reused, and weak saved passwords.

Leaks are looked up with Have I Been Pwned's range API (k-anonymity): only the first 5 characters of each password's
SHA-1 hash leave the computer, and the matching is done here, so neither the password nor its full hash is ever sent.
Nothing goes to the AI. The check only runs when the user presses the button.
"""
from __future__ import annotations

import hashlib
import urllib.request

RANGE_URL = "https://api.pwnedpasswords.com/range/{}"
COMMON = {"password", "123456", "12345678", "123456789", "qwerty", "abc123", "111111", "letmein", "iloveyou",
          "admin", "welcome", "monkey", "dragon", "football", "baseball", "sunshine", "princess", "password1",
          "qwerty123", "1q2w3e4r", "000000", "trustno1", "passw0rd", "starwars", "whatever"}


def sha1(pw: str) -> str:
    return hashlib.sha1(pw.encode("utf-8")).hexdigest().upper()


def fetch_range(prefix: str, timeout: float = 15) -> str:
    req = urllib.request.Request(RANGE_URL.format(prefix), headers={"User-Agent": "Pelagic-password-checkup",
                                                                     "Add-Padding": "true"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def leak_count(pw: str, ranges: dict, fetch=fetch_range) -> int:
    h = sha1(pw)
    prefix, rest = h[:5], h[5:]
    if prefix not in ranges:
        ranges[prefix] = fetch(prefix)
    for line in ranges[prefix].splitlines():
        suffix, _, count = line.strip().partition(":")
        if suffix.upper() == rest:
            return int(count or 0)
    return 0


def is_weak(pw: str) -> bool:
    if len(pw) < 8 or pw.lower() in COMMON or len(set(pw)) <= 3:
        return True
    kinds = sum(bool(any(f(c) for c in pw)) for f in (str.islower, str.isupper, str.isdigit,
                                                        lambda c: not c.isalnum()))
    return kinds < 2 and len(pw) < 14


def checkup(logins: list[dict], fetch=fetch_range) -> dict:
    """Runs off the UI thread. Returns {"issues": {login id: {"leaked": n, "reused": k, "weak": bool}},
    "checked": n, "error": str} where reused is how many other saved logins share the password."""
    by_pw: dict[str, list[str]] = {}
    for x in logins:
        if x.get("password"):
            by_pw.setdefault(x["password"], []).append(x["id"])
    ranges: dict[str, str] = {}
    issues, error = {}, ""
    for pw, ids in by_pw.items():
        leaked = 0
        if not error:
            try:
                leaked = leak_count(pw, ranges, fetch)
            except OSError as e:
                error = f"couldn't reach the breach database ({getattr(e, 'reason', e)})"
        weak = is_weak(pw)
        for lid in ids:
            if leaked or weak or len(ids) > 1:
                issues[lid] = {"leaked": leaked, "reused": len(ids) - 1, "weak": weak}
    return {"issues": issues, "checked": sum(len(v) for v in by_pw.values()), "error": error}
