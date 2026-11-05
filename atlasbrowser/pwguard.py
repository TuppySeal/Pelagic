"""Stops a message to the AI that looks like it has a password in it ("my password is …", "pin: 1234", an API key).

It only looks at the text you typed, here on your computer. The panel holds such a message back and offers a small
"Send anyway" button for when it isn't a password, or you're fine with the AI seeing it."""
from __future__ import annotations

import re

# "password", "pin", "2fa code"… followed by "is", ":", "=" and then the value itself.
_WORDS = (r"pass(?:word|wd|phrase|code)?|pwd|pin(?:\s*(?:code|number))?|(?:2fa|mfa|otp|one[\s-]?time|verification|"
          r"security|login|auth(?:entication)?)\s*code|otp|api[\s_-]?key|secret(?:\s*key)?|access\s*token|"
          r"(?:auth|bearer)\s*token|recovery\s*(?:code|key|phrase)|seed\s*phrase|login\s*details|credentials")
_PHRASE = re.compile(rf"\b(?P<what>{_WORDS})\b(?:\s+(?:for|on|to)\s+[\w.@-]+)?\s*(?P<sep>(?:is|was|would\s+be|will\s+be|should\s+be)\s*[:=]?|=|:|-)"
                     rf"\s*[\"'`“‘]?(?P<value>[^\s\"'`”’]{{3,}})", re.IGNORECASE)
# Values that follow "password is" in ordinary questions ("my password is wrong").
_NOT_VALUES = {
    "a", "an", "the", "my", "your", "not", "too", "very", "so", "now", "still", "also", "just", "being", "been", "no",
    "wrong", "incorrect", "correct", "right", "invalid", "expired", "weak", "strong", "secure", "safe", "unsafe",
    "short", "long", "same", "different", "required", "needed", "missing", "forgotten", "lost", "changed", "reset",
    "saved", "stored", "hidden", "shown", "visible", "empty", "blank", "set", "ok", "okay", "fine", "good", "bad",
    "case", "sensitive", "there", "here", "what", "which", "how", "why", "when", "where", "that", "this", "it",
    "stolen", "leaked", "compromised", "breached", "working", "accepted", "rejected", "locked", "manager",
    "generator", "field", "box", "page", "screen", "prompt", "and", "or", "but", "if", "for", "on", "in", "of",
    "to", "with", "you", "me", "i", "we", "they", "should", "would", "could", "can", "will", "must", "need",
}
_KEYS = re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                   r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[abpr]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{16,})")
# user:password@ in a link
_URL_LOGIN = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE)


def _mask(value: str) -> str:
    return value[:1] + "•" * min(max(len(value) - 1, 3), 8)


def check(text: str) -> str | None:
    """A short reason, with the value hidden, when `text` looks like it contains a password; None otherwise."""
    for m in _PHRASE.finditer(text or ""):
        value = m.group("value").rstrip(".,;!?)")
        # after "is" an ordinary word means a question ("my password is wrong"); after ":" or "=" it's the value
        if len(value) < 3 or (m.group("sep")[-1] not in ":=" and value.lower() in _NOT_VALUES):
            continue
        what = re.sub(r"\s+", " ", m.group("what").lower())
        what = {"pass": "password", "passwd": "password", "pwd": "password", "pin": "PIN", "otp": "one-time code",
                "pin code": "PIN", "pin number": "PIN"}.get(what, what)
        return f'it looks like it contains a {what} ({what}: {_mask(value)})'
    m = _KEYS.search(text or "")
    if m:
        return f"it looks like it contains an API key or token ({_mask(m.group(0))})"
    if _URL_LOGIN.search(text or ""):
        return "it has a link with a username and password in it"
    return None
