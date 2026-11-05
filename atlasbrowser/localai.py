"""Pelagic Local: a rule-based command interpreter for basic browser tasks. No model, no network, zero tokens.

parse(text, current_url) -> {"kind": "steps"|"watch"|"help"|"unknown", ...}
"""
from __future__ import annotations

import re

SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "reddit": "https://www.reddit.com", "wikipedia": "https://en.wikipedia.org",
    "amazon": "https://www.amazon.com", "twitter": "https://x.com", "x": "https://x.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com", "netflix": "https://www.netflix.com",
    "twitch": "https://www.twitch.tv", "linkedin": "https://www.linkedin.com", "ebay": "https://www.ebay.com",
    "stackoverflow": "https://stackoverflow.com", "stack overflow": "https://stackoverflow.com",
    "hacker news": "https://news.ycombinator.com", "hackernews": "https://news.ycombinator.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "gemini": "https://gemini.google.com", "spotify": "https://open.spotify.com",
    "discord": "https://discord.com/app", "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "calendar": "https://calendar.google.com", "news": "https://news.google.com", "weather": "https://weather.com",
    "roblox": "https://www.roblox.com", "duckduckgo": "https://duckduckgo.com", "bing": "https://www.bing.com",
}
SEARCH_SITES = {
    "youtube": "https://www.youtube.com/results?search_query=%s", "amazon": "https://www.amazon.com/s?k=%s",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search=%s", "github": "https://github.com/search?q=%s",
    "reddit": "https://www.reddit.com/search/?q=%s", "google": "https://www.google.com/search?q=%s",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw=%s", "maps": "https://www.google.com/maps/search/%s",
    "google maps": "https://www.google.com/maps/search/%s", "stackoverflow": "https://stackoverflow.com/search?q=%s",
    "stack overflow": "https://stackoverflow.com/search?q=%s", "bing": "https://www.bing.com/search?q=%s",
    "duckduckgo": "https://duckduckgo.com/?q=%s", "twitter": "https://x.com/search?q=%s", "x": "https://x.com/search?q=%s",
}
HELP = """**Pelagic Local** runs simple commands with no AI and no tokens. Chain steps with “then”.

- `open youtube` · `go to example.com` · `search for cute cats` · `search cats on youtube`
- `click Sign in` · `type hello in Search` · `fill Email with me@x.com and submit` · `select Two in Size`
- `scroll down` · `scroll up 2` · `scroll to bottom` · `back` · `forward` · `reload`
- `press Enter` · `wait 3 seconds` · `new tab` · `close tab` · `bookmark this` · `zoom in` · `read this page`
- `find price on this page`

**Repeat until something happens** (runs quietly in the background, wakes you only when it matches):
- `refresh every 30 seconds until "in stock" appears and notify me`
- `watch this page every 5 minutes for "sale"`
- `check https://example.com every 10 minutes when price drops below 50`
- `reload every minute until the page changes`
- `click Refresh every 20 seconds until "Confirmed" appears and open the page`
- Add `and ask ai` to have the AI look at the page once, only after the match."""

_UNIT = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60, "minute": 60,
         "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}
_EVERY = re.compile(r"\bevery\s+(?:(\d+(?:\.\d+)?)\s*)?(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b", re.I)
_HOST = re.compile(r"^(https?://\S+|localhost(:\d+)?(/\S*)?|(\d{1,3}\.){3}\d{1,3}(:\d+)?(/\S*)?|[\w-]+(\.[\w-]+)+(/\S*)?)$", re.I)
_Q = r"""["“”'‘’]?"""
_KEYS = {"enter": "Enter", "return": "Enter", "tab": "Tab", "escape": "Escape", "esc": "Escape", "space": "Space",
         "backspace": "Backspace", "delete": "Delete", "home": "Home", "end": "End", "page down": "PageDown",
         "pagedown": "PageDown", "page up": "PageUp", "pageup": "PageUp", "arrow down": "ArrowDown",
         "arrow up": "ArrowUp", "arrow left": "ArrowLeft", "arrow right": "ArrowRight", "down": "ArrowDown",
         "up": "ArrowUp", "left": "ArrowLeft", "right": "ArrowRight"}


def _clean(s: str) -> str:
    s = s.strip().strip("\"“”'‘’").strip()
    return re.sub(r"\s+(?:button|link|field|box|input|bar|tab)$", "", s, flags=re.I).strip()


def site_url(name: str) -> str | None:
    n = name.strip().lower().rstrip(".")
    if n in SITES:
        return SITES[n]
    if _HOST.match(name.strip()):
        u = name.strip()
        return u if re.match(r"^https?://", u, re.I) else "https://" + u
    return None


def _split(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,\s*)?(?:\band\s+then\b|\bthen\b|;|\bafter\s+that\b)\s*|\s+and\s+(?=(?:click|press|type|scroll|open|go|search|fill|select|wait|reload|refresh)\b)",
                     text.strip(), flags=re.I)
    return [p.strip(" ,.") for p in parts if p and p.strip(" ,.")]


def _clause(c: str):
    """One clause -> step dict, or None if not understood."""
    low = c.lower().strip()
    m = re.match(r"^(?:please\s+)?(?:go\s+)?back$", low)
    if m:
        return {"action": "back", "args": {}}
    if re.match(r"^(?:go\s+)?forward$", low):
        return {"action": "forward", "args": {}}
    if re.match(r"^(?:reload|refresh)(?:\s+(?:the\s+)?(?:page|tab|site))?$", low):
        return {"action": "reload", "args": {}}
    m = re.match(r"^scroll\s+(?:all\s+the\s+way\s+)?(?:to\s+(?:the\s+)?)?(top|bottom)$", low)
    if m:
        return {"action": "scroll", "args": {"direction": "up" if m.group(1) == "top" else "down", "pages": 60}}
    m = re.match(r"^scroll\s+(down|up)(?:\s+(?:by\s+)?(\d+(?:\.\d+)?)(?:\s*(?:pages?|screens?))?)?$", low)
    if m:
        return {"action": "scroll", "args": {"direction": m.group(1), "pages": float(m.group(2) or 1)}}
    m = re.match(r"^press\s+(?:the\s+)?(?:key\s+)?([\w +]+)$", low)
    if m:
        key = m.group(1).strip()
        if key in _KEYS:
            return {"action": "press_key", "args": {"key": _KEYS[key]}}
        if re.match(r"^(?:ctrl|control|shift|alt)\s*\+\s*\w$", key):
            return {"action": "press_key", "args": {"key": re.sub(r"\s", "", key).title().replace("Ctrl", "Control")}}
    m = re.match(r"^(?:wait|pause|sleep)\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(\w+)?$", low)
    if m:
        return {"action": "wait", "args": {"seconds": float(m.group(1)) * _UNIT.get((m.group(2) or "s"), 1)}}
    if re.match(r"^new\s+tab$", low):
        return {"action": "new_tab", "args": {}}
    m = re.match(r"^(?:new\s+tab|open\s+(?:a\s+)?new\s+tab)\s+(?:with\s+|at\s+|to\s+)?(.+)$", c, re.I)
    if m:
        url = site_url(m.group(1))
        return {"action": "new_tab", "args": {"url": url}} if url else None
    if re.match(r"^close\s+(?:this\s+)?tab$", low):
        return {"action": "close_tab", "args": {}}
    if re.match(r"^bookmark(?:\s+this)?(?:\s+page)?$", low):
        return {"action": "bookmark", "args": {}}
    m = re.match(r"^zoom\s+(in|out|reset)$", low)
    if m:
        return {"action": "zoom", "args": {"direction": m.group(1)}}
    if re.match(r"^(?:read|extract|get\s+the\s+text\s+of|show\s+me\s+the\s+text\s+of)(?:\s+(?:this|the))?(?:\s+page)?$", low):
        return {"action": "extract", "args": {}}
    m = re.match(rf"^(?:find|search\s+for|look\s+for)\s+{_Q}(.+?){_Q}\s+(?:on|in)\s+(?:this\s+|the\s+)?page$", c, re.I)
    if m:
        return {"action": "find", "args": {"text": m.group(1)}}
    # type / fill
    submit = False
    body = c
    sm = re.match(r"^(.*?)\s+(?:and\s+)?(?:then\s+)?(?:submit|press\s+enter|hit\s+enter)$", body, re.I)
    if sm:
        body, submit = sm.group(1), True
    m = re.match(rf"^(?:type|enter|write|input)\s+{_Q}(.+?){_Q}\s+(?:in|into|on)\s+(?:the\s+)?{_Q}(.+?){_Q}$", body, re.I)
    if m:
        return {"action": "type", "args": {"target": _clean(m.group(2)), "text": m.group(1).strip("\"“”'‘’"), "submit": submit}}
    m = re.match(rf"^fill(?:\s+in)?\s+(?:the\s+)?{_Q}(.+?){_Q}\s+with\s+{_Q}(.+?){_Q}$", body, re.I)
    if m:
        return {"action": "type", "args": {"target": _clean(m.group(1)), "text": m.group(2).strip("\"“”'‘’"), "submit": submit}}
    m = re.match(rf"^(?:select|choose|pick)\s+{_Q}(.+?){_Q}\s+(?:in|from)\s+(?:the\s+)?{_Q}(.+?){_Q}$", c, re.I)
    if m:
        return {"action": "select", "args": {"target": _clean(m.group(2)), "value": m.group(1).strip("\"“”'‘’")}}
    m = re.match(rf"^(?:click|tap|hit|press)\s+(?:on\s+)?(?:the\s+)?(?:button\s+|link\s+)?{_Q}(.+?){_Q}$", c, re.I)
    if m:
        return {"action": "click", "args": {"target": _clean(m.group(1))}}
    # search (with optional site)
    m = re.match(rf"^(?:search|look\s+up|google|find)\s+(?:for\s+)?{_Q}(.+?){_Q}(?:\s+(?:on|in|at)\s+(.+))?$", c, re.I)
    if m:
        q, site = m.group(1).strip(), (m.group(2) or "").strip().lower()
        if site and site in SEARCH_SITES:
            from urllib.parse import quote
            return {"action": "navigate", "args": {"url": SEARCH_SITES[site] % quote(q)}}
        return {"action": "search", "args": {"query": q if not site else f"{q} {site}"}}
    # open / go to
    m = re.match(r"^(?:open|go\s+to|goto|visit|navigate\s+to|launch|load|take\s+me\s+to)\s+(?:the\s+)?(.+)$", c, re.I)
    if m:
        what = m.group(1).strip().strip("\"“”'‘’")
        url = site_url(what)
        if url:
            return {"action": "navigate", "args": {"url": url}}
        return {"action": "search", "args": {"query": what}}
    if _HOST.match(c.strip()):
        return {"action": "navigate", "args": {"url": site_url(c.strip())}}
    return None


def parse_steps(text: str):
    steps = []
    for part in _split(text):
        s = _clause(part)
        if s is None:
            return None, part
        steps.append(s)
    return steps, ""


def _interval(m) -> float:
    n = float(m.group(1) or 1)
    return n * _UNIT[m.group(2).lower()]


def _parse_condition(after: str, whole: str):
    """Pull a wake-up condition out of the text after 'every N …'."""
    a = after
    # number thresholds
    m = re.search(r"(?:(\w+)\s+)?(?:drops?\s+|goes?\s+|falls?\s+|gets?\s+|is\s+|becomes?\s+)?(?:below|under|less\s+than|lower\s+than|<)\s*\$?(\d+(?:[.,]\d+)?)", a, re.I)
    if m:
        near = m.group(1) if m.group(1) and m.group(1).lower() in ("price", "cost", "score", "count") else None
        return {"type": "number", "op": "<", "num": float(m.group(2).replace(",", "")), **({"near": near} if near else {})}
    m = re.search(r"(?:(\w+)\s+)?(?:rises?\s+|goes?\s+|gets?\s+|is\s+|becomes?\s+)?(?:above|over|more\s+than|greater\s+than|higher\s+than|>)\s*\$?(\d+(?:[.,]\d+)?)", a, re.I)
    if m:
        near = m.group(1) if m.group(1) and m.group(1).lower() in ("price", "cost", "score", "count") else None
        return {"type": "number", "op": ">", "num": float(m.group(2).replace(",", "")), **({"near": near} if near else {})}
    m = re.search(rf"(?:until|when|if|for|once)\s+(?:the\s+page\s+(?:shows|says|contains)\s+)?{_Q}(.+?){_Q}\s+(?:disappears?|is\s+gone|goes\s+away|vanishes)", a, re.I)
    if m:
        return {"type": "gone", "value": m.group(1).strip()}
    if re.search(r"(?:until|when|if|once)\s+(?:the\s+)?(?:page|site|it|something|anything)\s+(?:changes?|updates?|is\s+different)|\bany\s+change\b|\bchanges?\b", a, re.I):
        return {"type": "changed"}
    m = re.search(rf"(?:until|when|if|once)\s+(?:the\s+page\s+(?:shows|says|contains)\s+)?{_Q}(.+?){_Q}\s+(?:appears?|shows?(?:\s+up)?|is\s+(?:there|available|visible|in\s+stock|back)|contains?|exists?|comes?\s+up|loads?)", a, re.I)
    if m:
        return {"type": "text", "value": m.group(1).strip()}
    m = re.search(rf"(?:for|until|when|says)\s+{_Q}([^\"“”'‘’]+?){_Q}(?:\s+(?:and|then|,)\b|$)", a, re.I)
    if m and not re.match(r"^(?:a|an|the|me|us)\b", m.group(1).strip(), re.I):
        return {"type": "text", "value": m.group(1).strip()}
    return None


def _parse_then(after: str) -> list[str]:
    then = []
    if re.search(r"\b(notify|tell|alert|ping|let\s+me\s+know|message|remind)\b", after, re.I):
        then.append("notify")
    if re.search(r"\b(beep|sound|ring)\b", after, re.I):
        then.append("beep")
    if re.search(r"\b(open\s+(?:it|the\s+page|that|the\s+site)|take\s+me\s+there|show\s+me)\b", after, re.I):
        then.append("open")
    if re.search(r"\b(ask\s+(?:the\s+)?ai|summari[sz]e|explain)\b", after, re.I):
        then.append("ask_ai")
    return then


def parse(text: str, current_url: str = "") -> dict:
    t = (text or "").strip()
    if not t or t.lower() in ("help", "?", "commands", "what can you do", "what can you do?"):
        return {"kind": "help"}
    every = _EVERY.search(t)
    if every:
        before, after = t[:every.start()].strip(" ,.-"), t[every.end():].strip(" ,.")
        sec = _interval(every)
        cond = _parse_condition(after, t) or _parse_condition(before, t)
        then = _parse_then(after) or _parse_then(before)
        pre = re.sub(r"^(?:please\s+)?(?:watch|monitor|keep\s+checking|check|keep\s+an\s+eye\s+on|poll)\s*", "", before, flags=re.I).strip()
        pre = re.sub(r"^(?:this\s+page|the\s+page|this\s+site|it)\s*", "", pre, flags=re.I).strip(" ,")
        url = ""
        um = re.match(r"^(?:https?://\S+|[\w-]+(?:\.[\w-]+)+\S*)", pre)
        if um:
            url, pre = site_url(um.group(0)) or "", pre[um.end():].strip(" ,")
        pre = re.sub(r"^(?:and\s+|then\s+)", "", pre, flags=re.I).strip()
        # words that describe the wait condition are not steps
        pre = re.sub(r"\s*(?:until|when|if|for)\b.*$", "", pre, flags=re.I).strip(" ,")
        steps, bad = ([], "") if not pre else parse_steps(pre)
        if steps is None:
            return {"kind": "unknown", "msg": f"I don't understand “{bad}”. Say `help` to see what I can do."}
        if steps and steps[0]["action"] == "navigate" and not url:
            url, steps = steps[0]["args"]["url"], steps[1:]
        steps = [s for s in steps if s["action"] != "reload"]
        reload = not steps   # with steps (e.g. "click Refresh") stay on the page instead of reloading it each time
        if not url:
            url = current_url
        if not re.match(r"^https?://", url or "", re.I):
            return {"kind": "unknown", "msg": "Open the page you want to watch first, or include its address."}
        if cond is None and not steps:
            cond = {"type": "changed"}
        if cond and not then:
            then = ["notify"]
        repeat = bool(re.search(r"\b(every\s+time|each\s+time|keep\s+(?:telling|notifying)|repeatedly)\b", t, re.I))
        return {"kind": "watch", "spec": {"name": f"Watch {re.sub(r'^https?://(www\.)?', '', url)[:30]}", "url": url,
                                           "every": sec, "condition": cond, "steps": steps, "then": then or ["notify"],
                                           "repeat": repeat, "reload": reload}}
    steps, bad = parse_steps(t)
    if steps is None:
        return {"kind": "unknown", "msg": f"I don't understand “{bad}”. Say `help` to see what I can do — "
                                          "or switch to Agent mode for anything open-ended."}
    return {"kind": "steps", "steps": steps}
