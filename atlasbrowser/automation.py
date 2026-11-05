"""Local automation: run browser actions with no AI, repeat them on a timer, and wake the user (or the AI)
only when a condition is met.

* LocalRunner   executes action dicts ({"action": "click", "args": {"target": "Go"}}) on a tab.
* check_condition   decides locally (text / number / change / element / url) whether to wake anyone.
* Watcher / WatchManager   the repeat-until-criteria loop. Zero tokens are spent until it fires.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from . import pagejs
from .webview import BrowserTab

MIN_INTERVAL_USER = 5        # seconds
MIN_INTERVAL_AI = 15         # an AI-created watcher may not hammer a site
MAX_WATCHERS = 10
DEFAULT_MAX_RUNS = 2000
AI_MAX_HOURS = 24
THEN_ACTIONS = ("notify", "beep", "open", "ask_ai", "agent")
COND_TYPES = ("text", "gone", "changed", "number", "element", "url", "title")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
_NUM = re.compile(r"(?<![\w.])[$€£]?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


# ------------------------------------------------------------------ conditions
def normalize_condition(cond):
    """Validate a user/AI-supplied condition. Returns a clean dict (or None for 'no condition')."""
    if cond in (None, "", {}, [], False):
        return None
    if isinstance(cond, str):
        return {"type": "text", "value": cond}
    if not isinstance(cond, dict):
        raise ValueError("condition must be an object")
    for key in ("all", "any"):
        if key in cond:
            subs = [normalize_condition(c) for c in cond[key]][:6]
            return {key: [s for s in subs if s]}
    t = str(cond.get("type", "text")).lower()
    aliases = {"contains": "text", "appears": "text", "missing": "gone", "disappears": "gone", "change": "changed",
               "price": "number", "num": "number", "button": "element", "link": "element"}
    t = aliases.get(t, t)
    if t not in COND_TYPES:
        raise ValueError(f"unknown condition type '{t}' (use {', '.join(COND_TYPES)})")
    out = {"type": t}
    if t in ("text", "gone", "element", "url", "title"):
        value = str(cond.get("value", "")).strip()
        if not value:
            raise ValueError(f"condition '{t}' needs a value")
        out["value"] = value[:200]
        if cond.get("regex"):
            re.compile(value)
            out["regex"] = True
    if t == "number":
        op = str(cond.get("op", "<")).strip()
        if op not in OPS:
            raise ValueError(f"unknown comparison '{op}'")
        try:
            out["num"] = float(cond.get("num", cond.get("value")))
        except (TypeError, ValueError):
            raise ValueError("number condition needs a numeric 'num'") from None
        out["op"] = op
    if cond.get("near"):
        out["near"] = str(cond["near"])[:80]
    return out


def describe_condition(cond) -> str:
    if not cond:
        return "(repeat only)"
    for key, joiner in (("all", " AND "), ("any", " OR ")):
        if key in cond:
            return joiner.join(describe_condition(c) for c in cond[key])
    t = cond["type"]
    near = f" near “{cond['near']}”" if cond.get("near") else ""
    if t == "text":
        return f"page shows “{cond['value']}”"
    if t == "gone":
        return f"“{cond['value']}” disappears"
    if t == "changed":
        return f"page changes{near}"
    if t == "number":
        return f"number{near} {cond['op']} {cond['num']:g}"
    if t == "element":
        return f"a “{cond['value']}” control appears"
    return f"{t} contains “{cond['value']}”"


def _numbers_near(text: str, near: str | None, span: int = 90) -> list[float]:
    chunks = [text]
    if near:
        chunks = []
        for m in re.finditer(re.escape(near), text, re.I):
            chunks.append(text[m.end(): m.end() + span])
    out = []
    for chunk in chunks:
        for m in _NUM.finditer(chunk):
            out.append(float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else "")))
            break   # first number after each mention
    return out


def _contains(hay: str, cond: dict) -> bool:
    if cond.get("regex"):
        return re.search(cond["value"], hay, re.I) is not None
    return cond["value"].lower() in hay.lower()


def check_condition(cond, snap: dict, state: dict) -> tuple[bool, str]:
    """Evaluate locally. snap = {url, title, text, items:[{text,tag,...}]}; state persists between checks."""
    if not cond:
        return False, "no condition"
    for key, combine in (("all", all), ("any", any)):
        if key in cond:
            results = [check_condition(c, snap, state) for c in cond[key]]
            return combine(r[0] for r in results), "; ".join(r[1] for r in results if r[0]) or "not met"
    t, text = cond["type"], snap.get("text", "")
    if t == "text":
        hit = _contains(text, cond)
        return hit, f"found “{cond['value']}”" if hit else f"“{cond['value']}” not on page"
    if t == "gone":
        gone = not _contains(text, cond)
        return gone, f"“{cond['value']}” is gone" if gone else f"“{cond['value']}” still there"
    if t == "url":
        hit = cond["value"].lower() in snap.get("url", "").lower()
        return hit, "URL matches" if hit else "URL does not match"
    if t == "title":
        hit = cond["value"].lower() in snap.get("title", "").lower()
        return hit, "title matches" if hit else "title does not match"
    if t == "element":
        want = cond["value"].lower()
        hit = any(want in (it.get("text", "") + " " + it.get("placeholder", "")).lower() for it in snap.get("items", []))
        return hit, f"“{cond['value']}” is available" if hit else f"no “{cond['value']}” control"
    if t == "number":
        nums = _numbers_near(text, cond.get("near"))
        if not nums:
            return False, "number not found"
        ok = [n for n in nums if OPS[cond["op"]](n, cond["num"])]
        shown = ok[0] if ok else nums[0]
        return bool(ok), f"{cond.get('near') or 'value'} is {shown:g}"
    if t == "changed":
        region = text
        if cond.get("near"):
            m = re.search(re.escape(cond["near"]) + r".{0,300}", text, re.I | re.S)
            region = m.group(0) if m else ""
        digest = hashlib.sha1(re.sub(r"\s+", " ", region).strip().encode("utf-8", "ignore")).hexdigest()
        key = "last:" + json.dumps(cond, sort_keys=True)
        prev = state.get(key)
        state[key] = digest
        if prev is None:
            return False, "baseline recorded"
        return prev != digest, "the page changed" if prev != digest else "no change"
    return False, "unsupported condition"


# ------------------------------------------------------------------ runner
class LocalRunner(QObject):
    """Executes action dicts one after another on a tab, without any AI."""

    step = Signal(str)

    def __init__(self, win, tab: BrowserTab, real_input: bool = True, cursor: bool = True, parent=None):
        super().__init__(parent)
        self.win, self.tab, self.real, self.cursor = win, tab, real_input, cursor
        self.cancelled = False
        self.text = ""          # last 'extract' result

    def cancel(self):
        self.cancelled = True

    # -- sequencing
    def run(self, steps: list[dict], done):
        """done(ok: bool, message: str) is called once, after the last step or the first failure."""
        queue, log = list(steps), []

        def nxt(ok=True, msg=""):
            if msg:
                log.append(msg)
                self.step.emit(msg)
            if self.cancelled:
                return done(False, "Stopped.")
            if not ok:
                return done(False, msg or "A step failed.")
            if not queue:
                return done(True, "; ".join(log))
            s = queue.pop(0)
            fn = getattr(self, "_s_" + str(s.get("action", "")), None)
            if fn is None:
                return nxt(False, f"I can't do “{s.get('action')}”.")
            try:
                fn(s.get("args") or {}, nxt)
            except Exception as e:  # noqa: BLE001 - a bad step must not take the app down
                nxt(False, f"{s.get('action')} failed: {e}")
        nxt()

    # -- helpers
    def wait_ready(self, cb, timeout: float = 15.0, grace_ms: int = 450):
        start = time.monotonic()

        def poll():
            if self.cancelled:
                return cb(False)
            if time.monotonic() - start > timeout:
                return cb(False)
            if self.tab.loading:
                return QTimer.singleShot(200, poll)
            self.tab.run_js("document.readyState", lambda st: cb(True) if st == "complete" else QTimer.singleShot(200, poll))
        QTimer.singleShot(grace_ms, poll)

    def _settle(self, cb):
        self.wait_ready(lambda _ok: QTimer.singleShot(250, cb), timeout=12.0, grace_ms=500)

    def _resolve(self, args, cb):
        """Refresh the element list, then turn id/target into an index. cb(idx|None, err)."""
        def snapshot_done(_raw):
            if (args.get("id") is not None):
                try:
                    return cb(int(args["id"]), "")
                except (TypeError, ValueError):
                    return cb(None, "bad element id")
            target = args.get("target") or args.get("label")
            if not target:
                return cb(None, "needs a target label")

            def got(idx):
                if isinstance(idx, (int, float)) and idx >= 0:
                    cb(int(idx), "")
                else:
                    cb(None, f"no visible element matches “{target}”")
            self.tab.run_js(pagejs.call(pagejs.RESOLVE_TARGET, str(target)), got)
        self.wait_ready(lambda _ok: self.tab.run_js(pagejs.SNAPSHOT, snapshot_done), timeout=10.0, grace_ms=100)

    def _glide(self, x, y, then):
        if not self.cursor:
            return then()
        ms = 380
        self.tab.run_js(pagejs.call(pagejs.CURSOR_MOVE, x, y, ms))
        QTimer.singleShot(ms + 60, then)

    # -- steps
    def _s_navigate(self, args, nxt):
        url = str(args.get("url", "")).strip()
        if not url:
            return nxt(False, "navigate needs a URL")
        self.tab.load(self.win.to_qurl(url))
        self._settle(lambda: nxt(True, f"Opened {url}"))

    def _s_search(self, args, nxt):
        q = str(args.get("query", "")).strip()
        if not q:
            return nxt(False, "search needs a query")
        self.tab.load(self.win.to_qurl(self.win.search_url(q)))
        self._settle(lambda: nxt(True, f"Searched for “{q}”"))

    def _s_reload(self, args, nxt):
        self.tab.reload()
        self._settle(lambda: nxt(True, "Reloaded"))

    def _s_back(self, args, nxt):
        self.tab.back()
        self._settle(lambda: nxt(True, "Went back"))

    def _s_forward(self, args, nxt):
        self.tab.forward()
        self._settle(lambda: nxt(True, "Went forward"))

    def _s_wait(self, args, nxt):
        try:
            secs = max(0.0, min(float(args.get("seconds", 2)), 60))
        except (TypeError, ValueError):
            secs = 2.0
        QTimer.singleShot(int(secs * 1000), lambda: nxt(True, f"Waited {secs:g}s"))

    def _s_scroll(self, args, nxt):
        direction = "up" if str(args.get("direction", "down")).lower() == "up" else "down"
        try:
            pages = max(0.1, min(float(args.get("pages", 1)), 60))
        except (TypeError, ValueError):
            pages = 1.0
        self.tab.run_js(pagejs.call(pagejs.SCROLL, direction, pages), lambda _r: nxt(True, f"Scrolled {direction}"))

    def _s_press_key(self, args, nxt):
        key = str(args.get("key", ""))
        if self.tab.press_key(key):
            self._settle(lambda: nxt(True, f"Pressed {key}"))
        else:
            nxt(False, f"unsupported key “{key}”")

    def _s_click(self, args, nxt):
        def resolved(idx, err):
            if idx is None:
                return nxt(False, err)

            def got(raw):
                try:
                    info = json.loads(raw)
                except (TypeError, ValueError):
                    return nxt(False, "the page did not respond")
                if not info.get("ok"):
                    return nxt(False, info.get("err", "click failed"))
                if info["kind"].startswith("select"):
                    return nxt(False, "that is a dropdown; use “select”")

                def click():
                    self.tab.run_js(pagejs.CURSOR_CLICK) if self.cursor else None
                    if info["good"] and self.real:
                        self.tab.real_click(info["x"], info["y"])
                    else:
                        self.tab.run_js(pagejs.call(pagejs.FALLBACK_CLICK, idx))
                    self._settle(lambda: nxt(True, f"Clicked “{info.get('label', '')[:50]}”"))
                self._glide(info["x"], info["y"], click)
            self.tab.run_js(pagejs.call(pagejs.PREPARE_CLICK, idx), got)
        self._resolve(args, resolved)

    def _s_type(self, args, nxt):
        text = "" if args.get("text") is None else str(args.get("text"))
        submit = args.get("submit") in (True, "true", "True", 1)

        def resolved(idx, err):
            if idx is None:
                return nxt(False, err)

            def got(raw):
                try:
                    info = json.loads(raw)
                except (TypeError, ValueError):
                    return nxt(False, "the page did not respond")
                if not info.get("ok"):
                    if info.get("err") == "password":
                        return nxt(False, "I never type into password fields")
                    return nxt(False, info.get("err", "typing failed"))
                if submit:
                    self.tab.press_key("Enter")
                self._settle(lambda: nxt(True, f"Typed into the field" + (" and pressed Enter" if submit else "")))
            self.tab.run_js(pagejs.call(pagejs.TYPE_TEXT, idx, text, True), got)
        self._resolve(args, resolved)

    def _s_select(self, args, nxt):
        def resolved(idx, err):
            if idx is None:
                return nxt(False, err)

            def got(raw):
                try:
                    info = json.loads(raw)
                except (TypeError, ValueError):
                    info = {"ok": False, "err": "the page did not respond"}
                nxt(bool(info.get("ok")), f"Selected “{info.get('chosen')}”" if info.get("ok") else info.get("err", "select failed"))
            self.tab.run_js(pagejs.call(pagejs.SELECT_OPTION, idx, str(args.get("value", ""))), got)
        self._resolve(args, resolved)

    def _s_extract(self, args, nxt):
        def got(raw):
            try:
                self.text = json.loads(raw)["text"]
            except (TypeError, ValueError, KeyError):
                return nxt(False, "could not read the page")
            nxt(True, f"Read the page ({len(self.text):,} characters)")
        self.tab.run_js(pagejs.FULL_TEXT, got)

    def _s_new_tab(self, args, nxt):
        url = str(args.get("url", "")).strip()
        self.tab = self.win.open_tab(url or None)
        self._settle(lambda: nxt(True, "Opened a new tab"))

    def _s_close_tab(self, args, nxt):
        if len(self.win.tab_list()) <= 1:
            return nxt(False, "that is the only tab")
        self.win.close_tab_obj(self.tab)
        self.tab = self.win.current_tab()
        nxt(True, "Closed the tab")

    def _s_bookmark(self, args, nxt):
        self.win.toggle_bookmark()
        nxt(True, "Toggled the bookmark")

    def _s_find(self, args, nxt):
        self.win.show_find()
        self.win.find_edit.setText(str(args.get("text", "")))
        nxt(True, f"Searching this page for “{args.get('text', '')}”")

    def _s_zoom(self, args, nxt):
        self.win._zoom({"in": 0.1, "out": -0.1}.get(str(args.get("direction", "in")), 0))
        nxt(True, "Zoomed")


def collect_snapshot(tab: BrowserTab, cb):
    """Full page text + visible controls, for condition checks. cb(dict | None)."""
    def with_text(raw):
        try:
            base = json.loads(raw)
        except (TypeError, ValueError):
            return cb(None)

        def with_items(raw2):
            try:
                base["items"] = json.loads(raw2).get("items", [])
            except (TypeError, ValueError, AttributeError):
                base["items"] = []
            cb(base)
        tab.run_js(pagejs.SNAPSHOT, with_items)
    tab.run_js(pagejs.FULL_TEXT, with_text)


# ------------------------------------------------------------------ watchers
class Watcher(QObject):
    """Checks a page on a timer; fires `fired` when the condition becomes true. Costs no tokens."""

    fired = Signal(object, str, object)   # watcher, reason, snapshot
    changed = Signal()
    ended = Signal()                      # stopped for good (finished, removed, limit reached)

    def __init__(self, ctx, spec: dict, parent=None):
        super().__init__(parent)
        self.ctx, self.spec = ctx, spec
        self.id, self.name = spec["id"], spec["name"]
        self.enabled = True
        self.runs = self.matches = self.errors = 0
        self.status = "waiting for first check"
        self.last_check = 0.0
        self.state: dict = {}
        self._was_met = False
        self._busy = False
        self._tab: BrowserTab | None = None
        self._runner: LocalRunner | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._cycle)
        self._started = time.time()

    # -- lifecycle
    def start(self, delay_ms: int = 800):
        self.enabled = True
        self._timer.start(delay_ms)
        self.changed.emit()

    def pause(self):
        self.enabled = False
        self._timer.stop()
        self.status = "paused"
        self.changed.emit()

    def resume(self):
        self.status = "resumed"
        self.start(500)

    def run_now(self):
        if not self._busy:
            self._timer.stop()
            self._cycle(force=True)

    def stop(self, reason: str = "stopped"):
        self.enabled = False
        self._timer.stop()
        if self._runner:
            self._runner.cancel()
        self.status = reason
        self.close_tab()
        self.changed.emit()
        self.ended.emit()

    def close_tab(self):
        if self._tab is not None:
            try:
                self._tab.stop()
                self._tab.deleteLater()
            except RuntimeError:
                pass
            self._tab = None

    # -- one check
    def _ensure_tab(self) -> BrowserTab:
        if self._tab is None:
            self._tab = self.ctx.background_tab()
        return self._tab

    def _schedule(self):
        if self.enabled:
            self._timer.start(int(self.spec["every"] * 1000))

    def _finish_cycle(self, status: str):
        self._busy = False
        self.status = status
        self.last_check = time.time()
        self.changed.emit()
        self._schedule()

    def _cycle(self, force: bool = False):
        if (not self.enabled and not force) or self._busy:
            return
        spec = self.spec
        if self.runs >= spec.get("max_runs", DEFAULT_MAX_RUNS) or time.time() > spec.get("until", float("inf")):
            self.ctx.watch_ended(self, "reached its run/time limit")
            return self.stop("finished (limit reached)")
        self._busy = True
        self.runs += 1
        self.status = "checking…"
        self.changed.emit()
        tab = self._ensure_tab()
        steps = list(spec.get("steps") or [])
        reload_each = spec.get("reload", True) or self.runs == 1

        def after_load(ok):
            if not ok and reload_each:
                return self._error("the page did not finish loading")
            self._runner = LocalRunner(self.ctx.window(), tab, real_input=True, cursor=False)
            self._runner.run(steps, after_steps) if steps else after_steps(True, "")

        def after_steps(ok, msg):
            if not ok:
                return self._error(msg or "a step failed")
            collect_snapshot(tab, evaluate)

        def evaluate(snap):
            if snap is None:
                return self._error("could not read the page")
            self.errors = 0
            cond = spec.get("condition")
            if not cond:
                return self._finish_cycle(f"ran at {time.strftime('%H:%M:%S')}")
            met, reason = check_condition(cond, snap, self.state)
            fire = met and (spec.get("repeat") or not self._was_met)
            self._was_met = met
            if fire:
                self.matches += 1
                self._busy = False
                self.status = f"MATCHED: {reason}"
                self.last_check = time.time()
                self.fired.emit(self, reason, snap)
                if not spec.get("repeat", False):
                    self.stop(f"done — {reason}")
                    return
                self.changed.emit()
                return self._schedule()
            self._finish_cycle(f"{time.strftime('%H:%M:%S')} — not met ({reason})")

        if reload_each:
            tab.load(self.ctx.window().to_qurl(spec["url"]))
            self._runner = LocalRunner(self.ctx.window(), tab, real_input=True, cursor=False)
            self._runner.wait_ready(after_load, timeout=25.0, grace_ms=600)
        else:
            after_load(True)

    def _error(self, why: str):
        self.errors += 1
        self._busy = False
        if self.errors >= 4:
            self.ctx.watch_ended(self, f"paused after repeated errors ({why})")
            return self.pause_with(f"paused: {why}")
        self._finish_cycle(f"error: {why} (retrying)")

    def pause_with(self, status: str):
        self.enabled = False
        self._timer.stop()
        self.status = status
        self.changed.emit()


def new_spec(name: str, url: str, every: float, condition=None, steps=None, then=None, ask: str = "",
             task: str = "", repeat: bool = False, reload: bool = True, source: str = "user",
             max_runs: int = DEFAULT_MAX_RUNS, until_hours: float | None = None) -> dict:
    """Validate and normalise a watcher definition (raises ValueError with a readable reason)."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("a watcher needs an http(s) URL")
    lo = MIN_INTERVAL_AI if source == "ai" else MIN_INTERVAL_USER
    try:
        every = float(every)
    except (TypeError, ValueError):
        raise ValueError("'every' must be a number of seconds") from None
    if every < lo:
        raise ValueError(f"'every' must be at least {lo} seconds")
    then = [t for t in (then or ["notify"]) if t in THEN_ACTIONS] or ["notify"]
    clean_steps = []
    for s in (steps or [])[:12]:
        if not isinstance(s, dict) or not isinstance(s.get("action"), str):
            raise ValueError("each step needs an 'action'")
        a = s["action"].lower()
        if a not in ("click", "type", "select", "press_key", "scroll", "wait", "navigate", "search", "reload",
                     "back", "forward"):
            raise ValueError(f"step '{a}' is not allowed in a watcher")
        clean_steps.append({"action": a, "args": dict(s.get("args") or {})})
    spec = {"id": "w" + str(int(time.time() * 1000))[-9:] + str(random.randint(10, 99)),
            "name": (name or "Watcher").strip()[:60], "url": url, "every": every,
            "condition": normalize_condition(condition), "steps": clean_steps, "then": then,
            "ask": (ask or "")[:400], "task": (task or "")[:400], "repeat": bool(repeat), "reload": bool(reload),
            "source": source, "max_runs": int(max(1, min(max_runs, 20000))), "created": time.time()}
    hours = until_hours if until_hours is not None else (AI_MAX_HOURS if source == "ai" else None)
    if hours:
        spec["until"] = time.time() + float(hours) * 3600
    if "agent" in then and not spec["task"]:
        spec["then"] = [t for t in then if t != "agent"] or ["notify"]
    return spec


def describe_spec(spec: dict) -> str:
    steps = ", ".join(f"{s['action']} {json.dumps(s['args'], ensure_ascii=False)[:60]}" for s in spec.get("steps", []))
    return (f"“{spec['name']}”: every {spec['every']:g}s on {spec['url']}\n"
            f"  when: {describe_condition(spec.get('condition'))}\n"
            f"  then: {', '.join(spec['then'])}" + (f"\n  each time first: {steps}" if steps else "")
            + (f"\n  AI question: {spec['ask']}" if "ask_ai" in spec["then"] and spec.get("ask") else "")
            + (f"\n  AI task: {spec['task']}" if "agent" in spec["then"] else ""))
