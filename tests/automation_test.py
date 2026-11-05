"""Automation tests: local conditions, the no-AI command interpreter, watchers that wake only on a match,
and the AI's `watch` action. Run: python tests/automation_test.py [--visible]"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlas_auto_")

RESULTS = []
HITS = {"stock": 0, "price": 0}


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/stock":
            HITS["stock"] += 1
            body = ("<title>Shop</title><h1>Console</h1><p>Status: " +
                    ("IN STOCK now!" if HITS["stock"] >= 3 else "Out of stock") + "</p>")
        elif path == "/price":
            HITS["price"] += 1
            body = f"<title>Deal</title><p>Price: ${120 - HITS['price'] * 30}.00</p>"
        else:
            body = ("<title>Form</title><input name=n placeholder='Your name'><button onclick=\"document.title='clicked'\">"
                    "Refresh</button>")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class AI(BaseHTTPRequestHandler):
    calls = 0
    last_user = ""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        AI.calls += 1
        msgs = body["messages"]
        user = next(m["content"] for m in reversed(msgs) if m["role"] == "user")
        user = user if isinstance(user, str) else str(user)
        AI.last_user = user
        system = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
        if "operates a real web browser" in system and "watch-task" in msgs[1]["content"] + user:
            if "RESULT" in user and "Watcher" in user:
                text = json.dumps({"thought": "armed", "action": "done", "args": {"answer": "I'll tell you when it's in stock."}})
            else:
                text = json.dumps({"thought": "set up a watcher", "action": "watch", "args": {
                    "name": "Stock check", "every": 15, "url": SITE + "/stock",
                    "when": {"type": "text", "value": "IN STOCK"}, "then": ["notify"]}})
        else:
            text = "Looks like it is back in stock - buy it."
        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}],
                           "usage": {"prompt_tokens": 50, "completion_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(h):
    s = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]


SITE = f"http://127.0.0.1:{serve(Site)}"
AI_BASE = f"http://127.0.0.1:{serve(AI)}/v1"

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atlasbrowser import automation as A  # noqa: E402
from atlasbrowser import localai  # noqa: E402
from atlasbrowser.store import Store  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(100)
    return False


def main():
    # ---- conditions (pure logic)
    snap = {"url": "https://x.test/p", "title": "Deal", "text": "Console\nPrice: $1,249.99 today\nStatus: Out of stock",
            "items": [{"text": "Add to cart", "tag": "button"}]}
    st = {}
    check("text condition", A.check_condition({"type": "text", "value": "out of stock"}, snap, st)[0])
    check("gone condition", A.check_condition({"type": "gone", "value": "in stock"}, snap, st)[0])
    check("number below (comma + decimals)", A.check_condition(
        {"type": "number", "op": "<", "num": 1300, "near": "Price"}, snap, st)[0])
    check("number above fails", not A.check_condition({"type": "number", "op": ">", "num": 1300, "near": "Price"}, snap, st)[0])
    check("element condition", A.check_condition({"type": "element", "value": "add to cart"}, snap, st)[0])
    st = {}
    first = A.check_condition({"type": "changed"}, snap, st)
    same = A.check_condition({"type": "changed"}, snap, st)
    changed = A.check_condition({"type": "changed"}, {**snap, "text": "different"}, st)
    check("change detection (baseline, same, changed)", (first[0], same[0], changed[0]) == (False, False, True))
    check("all/any combine", A.check_condition({"all": [{"type": "text", "value": "console"},
                                                         {"type": "text", "value": "nope"}]}, snap, {})[0] is False
          and A.check_condition({"any": [{"type": "text", "value": "console"}, {"type": "text", "value": "nope"}]},
                                snap, {})[0])
    for bad in ({"type": "bogus"}, {"type": "number", "op": "~", "num": 1}, {"type": "text"}):
        try:
            A.normalize_condition(bad)
            check(f"rejects {bad}", False)
        except ValueError:
            check(f"rejects {bad}", True)
    try:
        A.new_spec("x", "file:///etc/passwd", 60)
        check("watcher refuses non-http URLs", False)
    except ValueError:
        check("watcher refuses non-http URLs", True)
    try:
        A.new_spec("x", "https://a.test", 3, source="ai")
        check("AI watcher interval floor", False)
    except ValueError:
        check("AI watcher interval floor", True)
    try:
        A.new_spec("x", "https://a.test", 60, steps=[{"action": "extract"}])
        check("watcher steps are whitelisted", False)
    except ValueError:
        check("watcher steps are whitelisted", True)

    # ---- local interpreter
    p = localai.parse('refresh every 30 seconds until "in stock" appears and notify me', "https://s.test/x")
    check("local: repeat-until parsed", p["kind"] == "watch" and p["spec"]["every"] == 30
          and p["spec"]["condition"] == {"type": "text", "value": "in stock"} and p["spec"]["then"] == ["notify"], str(p))
    p = localai.parse("check https://s.test/a every 10 minutes when price drops below 50", "")
    check("local: number watch parsed", p["spec"]["every"] == 600 and p["spec"]["condition"]["num"] == 50
          and p["spec"]["condition"]["near"] == "price", str(p))
    check("local: steps chain", [s["action"] for s in localai.parse("open youtube then search cats then scroll down 2")["steps"]]
          == ["navigate", "search", "scroll"])
    check("local: unknown text is refused politely", localai.parse("do my homework")["kind"] == "unknown")
    check("local: watch without a page is refused", localai.parse("watch this page every 1 minute for sale", "")["kind"] == "unknown")

    # ---- GUI: watchers wake only on a match; local runner; AI watch action
    A.MIN_INTERVAL_USER = 1   # let the test poll quickly (the real floor is 5 s)
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    store.set("confirm_watch", False)
    store.set("guard", False)
    store.set("overrides", {"openai": {"base_url": AI_BASE, "model": "m"}})
    store.set_key("openai", "k")
    store.set("selected", "openai")
    browser = Browser(app, store)
    win = browser.new_window(urls=[SITE + "/"])
    pump(800)
    tab = win.current_tab()
    panel = win.panel
    watches = browser.watches

    # local runner on the visible tab: typing, clicking by label
    runner = A.LocalRunner(win, tab)
    out = {}
    runner.run(localai.parse("type Ada in Your name then click Refresh")["steps"], lambda ok, m: out.update(ok=ok, m=m))
    check("local runner types and clicks by label", wait_until(lambda: "ok" in out, 30) and out["ok"]
          and wait_until(lambda: tab.title() == "clicked", 10), str(out))
    out.clear()
    runner.run([{"action": "type", "args": {"target": "Nope", "text": "x"}}], lambda ok, m: out.update(ok=ok, m=m))
    check("local runner reports a missing control", wait_until(lambda: "ok" in out, 20) and out["ok"] is False
          and "Nope" in out["m"], str(out))

    # the watcher: out of stock twice, then in stock; AI must not be called before the match
    AI.calls = 0
    spec = A.new_spec("Stock", SITE + "/stock", 1, {"type": "text", "value": "IN STOCK"}, then=["notify", "ask_ai"],
                      ask="Should I buy?")
    w = watches.create(spec)
    before_match = {}
    watches.notified.connect(lambda t, m: before_match.setdefault("n", []).append((t, m, AI.calls)))
    check("watcher fires once the page says IN STOCK", wait_until(lambda: any("Stock" in t for t, _, _ in before_match.get("n", [])), 60),
          f"hits={HITS} status={w.status}")
    check("watcher made several checks before matching", w.runs >= 3, str(w.runs))
    check("no AI call while waiting", before_match["n"][0][2] == 0, str(before_match))
    check("then the AI is asked exactly once", wait_until(lambda: AI.calls == 1, 20), str(AI.calls))
    check("AI saw the page text and the user's question", "IN STOCK" in AI.last_user and "Should I buy?" in AI.last_user)
    check("answer shown in the panel", wait_until(lambda: "buy it" in panel.view.toPlainText(), 15))
    check("one-shot watcher stopped itself", not w.enabled and w.status.startswith("done"), w.status)
    check("AI wake-up was metered as a task", panel.session.calls == 1)
    check("watcher background tab was released", w._tab is None)

    # edge-triggered numbers: price drops 90, 60, 30 ...
    wp = watches.create(A.new_spec("Price", SITE + "/price", 1, {"type": "number", "op": "<", "num": 50, "near": "Price"}))
    check("number watcher fires when price < 50", wait_until(lambda: wp.matches == 1, 60), f"{wp.status} {HITS}")

    # persistence + limits
    keep = Store(store.root).get("watchers")
    check("finished watchers are not restored", all(s["name"] not in ("Stock", "Price") for s in keep), str(keep))
    live = watches.create(A.new_spec("Idle", SITE + "/stock", 3600, {"type": "text", "value": "never-appears"}), start=False)
    watches.save()
    check("live watchers are saved for the next launch", any(s["name"] == "Idle" for s in Store(store.root).get("watchers")))
    watches.delete(live.id)
    check("delete removes it", live.id not in watches.items)

    # the AI's `watch` action (always confirmed first)
    store.set("confirm_watch", True)
    from atlasbrowser import agent as agent_mod
    asked = []
    orig = agent_mod.QMessageBox.question
    agent_mod.QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2]), agent_mod.QMessageBox.StandardButton.No)[1])
    panel.set_mode("agent")
    n_before = len(watches.items)
    panel.input.setPlainText("watch-task: tell me when it is back in stock")
    panel.send()
    wait_until(lambda: panel.agent is not None and not panel.agent.running, 40)
    check("AI watcher asks the user first", bool(asked) and "IN STOCK" in asked[0], str(asked))
    check("declined watcher is not created", len(watches.items) == n_before)
    agent_mod.QMessageBox.question = staticmethod(lambda *a, **k: agent_mod.QMessageBox.StandardButton.Yes)
    panel.new_chat()
    panel.set_mode("agent")
    panel.input.setPlainText("watch-task: tell me when it is back in stock")
    panel.send()
    wait_until(lambda: panel.agent is not None and not panel.agent.running, 40)
    created = [x for x in watches.items.values() if x.name == "Stock check"]
    check("AI watcher created after approval", len(created) == 1 and created[0].spec["source"] == "ai"
          and created[0].spec["every"] == 15 and "until" in created[0].spec, str(list(watches.items)))
    agent_mod.QMessageBox.question = orig
    for x in list(watches.items.values()):
        watches.delete(x.id)

    # Local mode in the panel (zero tokens)
    panel.new_chat()
    panel.set_mode("local")
    calls = AI.calls
    panel.input.setPlainText("go to " + SITE.replace("http://", "") + "/stock")
    panel.send()
    check("local mode navigates without any AI call", wait_until(lambda: tab.url().path() == "/stock", 30)
          and AI.calls == calls, tab.url().toString())
    wait_until(lambda: not panel.busy, 20)
    panel.input.setPlainText("refresh every 30 seconds until \"never\" appears and notify me")
    panel.send()
    check("local mode creates an automation", wait_until(lambda: len(watches.items) == 1, 10)
          and "Automation started" in panel.view.toPlainText())
    from atlasbrowser.automation_ui import AutomationsDialog
    d = AutomationsDialog(win, win)
    check("automations window lists it", d.list.count() == 1 and "every 30s" in d.list.item(0).text(), d.list.item(0).text())
    for x in list(watches.items.values()):
        watches.delete(x.id)
    win.close()
    pump(300)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    os._exit(main())
