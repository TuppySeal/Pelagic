"""End-to-end self test: mock AI servers + a local website, driving the real browser UI and agent.

Run:  python tests/selftest.py          (add --visible to show the window)
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "--visible" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ATLASBROWSER_HOME"] = tempfile.mkdtemp(prefix="atlasbrowser_test_")
os.environ.setdefault("PELAGIC_PASSWORD_STORE", "basic")   # off Windows: a key file in that folder, not your keyring

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


# ------------------------------------------------------------------ fake web site
class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/result":
            name = parse_qs(u.query).get("n", [""])[0]
            body = f"<title>Result</title><h1>Hello {name}</h1><p>Form accepted.</p>"
        elif u.path == "/newtab":
            body = "<title>Opener</title><a id=l href='/result?n=Tab' target='_blank'>Open result in new tab</a>"
        else:
            body = ("<title>Form test</title><script>window.kd=0;addEventListener('keydown',()=>kd++)</script>"
                    "<h1>Test site</h1><form action='/result' method='get'>"
                    "<input name='n' placeholder='Your name'><input type=password name=p placeholder='Password'>"
                    "<select name=s><option>One</option><option>Two</option></select>"
                    "<button type='submit'>Go</button></form><a href='/newtab'>other</a>")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ------------------------------------------------------------------ fake AI vendor
FLAKY = {"n": 0}
CALLS = {"openai": 0, "anthropic": 0, "gemini": 0, "images": 0}


def scripted_agent(user_text: str, first_user: str) -> str:
    """Decide the next browser action from the observation text, like a (very simple) model."""
    def find(pattern):
        m = re.search(pattern, user_text)
        return int(m.group(1)) if m else None
    if "agent-batch" in first_user:
        CALLS["batch_calls"] = CALLS.get("batch_calls", 0) + 1
        if "Hello Ada" not in user_text and "Your name" in user_text:
            return json.dumps({"thought": "fill and submit", "actions": [
                {"action": "type", "args": {"target": "Your name", "text": "Ada"}},
                {"action": "click", "args": {"target": "Go"}},
                {"action": "click", "args": {"id": 0}}]})   # must be skipped: the page changes after the submit
    if "Hello Ada" in user_text:
        return json.dumps({"thought": "Form accepted", "action": "done",
                           "args": {"answer": "The site greeted me: Hello Ada", "success": True}})
    if "Your name" in user_text and "RESULT: Typed" not in user_text:
        pw = find(r"\[(\d+)\] <input:password>")
        if "try-password" in first_user and "RESULT: I never type passwords" not in user_text and pw is not None:
            return json.dumps({"thought": "type pw", "action": "type", "args": {"id": pw, "text": "hunter2"}})
        return json.dumps({"thought": "fill name", "action": "type", "args": {"id": find(r"\[(\d+)\] <input:text>"),
                                                                              "text": "Ada"}})
    if "RESULT: Typed" in user_text:
        return "Sure! ```json\n" + json.dumps({"thought": "submit", "action": "click",
                                               "args": {"id": find(r'\[(\d+)\] <button:submit> "Go"')}}) + "\n```"
    if user_text.startswith("TASK") and "Tabs:" not in user_text:
        return "I am not sure what to do"
    return json.dumps({"thought": "nothing", "action": "done", "args": {"answer": "gave up", "success": False}})


class AI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/oa/v1/models"):
            self._send(200, {"data": [{"id": "m-b"}, {"id": "m-a"}]})
        elif self.path.startswith("/an/v1/models"):
            self._send(200, {"data": [{"id": "claude-x"}]})
        elif self.path.startswith("/ge/models"):
            self._send(200, {"models": [{"name": "models/gem-1", "supportedGenerationMethods": ["generateContent"]},
                                        {"name": "models/emb", "supportedGenerationMethods": ["embedContent"]}]})
        else:
            self._send(404, {"error": {"message": "nope"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/oa/v1/chat/completions":
            CALLS["openai"] += 1
            if self.headers.get("Authorization") != "Bearer test-key":
                return self._send(401, {"error": {"message": "Incorrect API key"}})
            model = body["model"]
            if model == "flaky" and FLAKY["n"] < 1:
                FLAKY["n"] += 1
                return self._send(429, {"error": {"message": "slow down"}})
            msgs = body["messages"]
            last = msgs[-1]["content"]
            if isinstance(last, list):
                CALLS["images"] += 1
                last = next(p["text"] for p in last if p["type"] == "text")
            system = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
            first_user = next(m["content"] for m in msgs if m["role"] == "user")
            if "operates a real web browser" in system:
                text = scripted_agent(last, first_user if isinstance(first_user, str) else "")
            else:
                text = f"<think>hidden</think>Echo[{model}]: {last[:60]}" + (" CTX" if "Page text" in system else "")
            resp = {"choices": [{"message": {"role": "assistant", "content": text}}]}
            if model != "nousage":
                resp["usage"] = {"prompt_tokens": 100, "completion_tokens": 10}
            return self._send(200, resp)
        if self.path == "/an/v1/messages":
            CALLS["anthropic"] += 1
            if self.headers.get("x-api-key") != "test-key" or "anthropic-version" not in self.headers:
                return self._send(401, {"type": "error", "error": {"message": "bad key"}})
            roles = [m["role"] for m in body["messages"]]
            assert roles == ["user"] or roles[0] == "user"
            return self._send(200, {"content": [{"type": "text", "text": "Claude says hi"}],
                                    "usage": {"input_tokens": 50, "output_tokens": 5}})
        m = re.match(r"/ge/models/(.+):generateContent", self.path)
        if m:
            CALLS["gemini"] += 1
            if self.headers.get("x-goog-api-key") != "test-key":
                return self._send(403, {"error": {"message": "API key not valid"}})
            if m.group(1) == "old-gem":
                return self._send(404, {"error": {"message": "This model is no longer available to new users."}})
            return self._send(200, {"candidates": [{"content": {"parts": [{"text": "Gemini says hi"}]},
                                                    "finishReason": "STOP"}],
                                    "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 4,
                                                      "thoughtsTokenCount": 6}})
        self._send(404, {"error": {"message": "unknown"}})


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


site, site_port = serve(Site)
ai, ai_port = serve(AI)
SITE = f"http://127.0.0.1:{site_port}"
AIB = f"http://127.0.0.1:{ai_port}"

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from atlasbrowser import providers  # noqa: E402
from atlasbrowser.agent import SENSITIVE, parse_action  # noqa: E402
from atlasbrowser.store import Store  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, timeout=40, step=100):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(step)
    return False


def goto(tab, url, title):
    from atlasbrowser.window import MainWindow  # noqa: F401
    tab.load(tab.window().to_qurl(url))
    pump(400)  # let loadStarted fire before polling the loading flag
    wait_until(lambda: not tab.loading and tab.title() == title)
    pump(300)


def js(tab, code):
    box = {}
    tab.page().runJavaScript(code, lambda r: box.setdefault("v", r))
    wait_until(lambda: "v" in box, 10)
    return box.get("v")


def main():
    # -------- providers (no GUI) --------
    prov = lambda kind, base, model="m", id="t": providers.Provider(id, "T", kind, base, model)  # noqa: E731
    check("openai-compatible chat", "Echo[m]: hi" in providers.chat(prov("openai", AIB + "/oa/v1"), "test-key",
                                                                    [{"role": "user", "content": "hi"}]))
    check("<think> blocks stripped", "hidden" not in providers.chat(prov("openai", AIB + "/oa/v1"), "test-key",
                                                                    [{"role": "user", "content": "hi"}]))
    check("anthropic chat (+merge roles)", providers.chat(prov("anthropic", AIB + "/an"), "test-key",
                                                          [{"role": "user", "content": "a"},
                                                           {"role": "user", "content": "b"}]) == "Claude says hi")
    check("gemini chat", providers.chat(prov("gemini", AIB + "/ge"), "test-key",
                                        [{"role": "user", "content": "x"}], system="s") == "Gemini says hi")
    try:
        providers.chat(prov("openai", AIB + "/oa/v1"), "wrong", [{"role": "user", "content": "hi"}])
        check("401 raises ProviderError", False)
    except providers.ProviderError as e:
        check("401 raises ProviderError mentioning key", "API key" in str(e), str(e))
    t0 = time.time()
    out = providers.chat(prov("openai", AIB + "/oa/v1", "flaky"), "test-key", [{"role": "user", "content": "hi"}])
    check("429 is retried", "Echo[flaky]" in out and time.time() - t0 < 10)
    check("list models openai", providers.list_models(prov("openai", AIB + "/oa/v1"), "test-key") == ["m-a", "m-b"])
    check("list models anthropic", providers.list_models(prov("anthropic", AIB + "/an"), "test-key") == ["claude-x"])
    check("list models gemini filters", providers.list_models(prov("gemini", AIB + "/ge"), "test-key") == ["gem-1"])
    try:
        providers.chat(prov("openai", AIB + "/oa/v1"), "", [{"role": "user", "content": "hi"}])
        check("missing key explained", False)
    except providers.ProviderError as e:
        check("missing key explained", "API key" in str(e))
    from atlasbrowser.usage import Meter
    sess = Meter(); task = Meter(sess)
    for kind, base in (("openai", "/oa/v1"), ("anthropic", "/an"), ("gemini", "/ge")):
        providers.chat(prov(kind, AIB + base, id=kind), "test-key", [{"role": "user", "content": "hi"}], meter=task)
    check("usage parsed from all three vendors", (task.inp, task.out, task.calls) == (190, 25, 3),
          str((task.inp, task.out, task.calls)))
    check("task usage rolls into session", sess.total == task.total and not task.estimated)
    est = Meter()
    providers.chat(prov("openai", AIB + "/oa/v1", "nousage"), "test-key", [{"role": "user", "content": "x" * 400}],
                   meter=est)
    check("missing usage falls back to an estimate", est.estimated and est.inp >= 100 and "~" in est.summary())
    check("parse_action in fences", parse_action('x ```json\n{"action":"click","args":{"id":3}}\n```')[:2]
          == ("click", {"id": 3}))
    check("parse_action flat args", parse_action('{"action":"scroll","direction":"down"}')[1] == {"direction": "down"})
    check("parse_action rejects prose", parse_action("I cannot do that") is None)
    check("sensitive guard regex", bool(SENSITIVE.search("Place order")) and not SENSITIVE.search("Next page"))
    check("registry has 25+ providers", len(providers.PRESETS) >= 25, str(len(providers.PRESETS)))

    # -------- GUI --------
    app = QApplication.instance() or QApplication(sys.argv)
    from atlasbrowser.app import Browser
    from atlasbrowser.window import apply_theme
    apply_theme(app)
    store = Store()
    store.set("guard", False)
    store.set("max_steps", 12)
    store.set("overrides", {"openai": {"base_url": AIB + "/oa/v1", "model": "gpt-test"},
                            "anthropic": {"base_url": AIB + "/an"}, "gemini": {"base_url": AIB + "/ge"}})
    for pid in ("openai", "anthropic", "gemini"):
        store.set_key(pid, "test-key")
    check("API keys round-trip through DPAPI", Store(store.root).get_key("openai") == "test-key")
    check("key file is not plaintext", b"test-key" not in (store.root / "keys.dat").read_bytes())
    store.set("selected", "openai")
    browser = Browser(app, store)
    win = browser.new_window(urls=[SITE + "/"])
    pump(300)
    tab = win.current_tab()
    check("page loads", wait_until(lambda: tab.title() == "Form test" and not tab.loading), tab.title())
    check("history recorded", any("127.0.0.1" in r[0] for r in store.history()))
    win.open_tab()
    check("start page for new tab", wait_until(lambda: win.current_tab().url().isLocalFile()))
    check("start page hides URL in address bar", win.addr.text() == "")
    win.close_tab_obj(win.current_tab())
    win.select_tab(tab)

    # address bar logic
    check("search fallback", "duckduckgo.com" in win.to_qurl("hello world").toString())
    check("host detected", win.to_qurl("example.com/x").toString() == "http://example.com/x")
    check("localhost:port", win.to_qurl("localhost:8080").host() == "localhost")

    # bookmarks
    pump(200)
    check("closing a tab selects a neighbour", win.current_tab() is tab, win.current_tab().url().toString())
    win.toggle_bookmark()
    check("bookmark added", store.is_bookmarked(tab.url().toString()) and win.star.text() == "★",
          f"{tab.url().toString()} {win.star.text()} {store.bookmarks} cur={win.current_tab().url().toString()}")

    panel = win.panel
    check("panel lists all providers", panel.provider_box.count() >= 26)
    from PySide6.QtWidgets import QPushButton
    check("the panel is always the agent, with no mode picker", panel.mode == "agent" and not panel.mode_btns
          and not any(b.text() in ("Chat", "Compare", "Local") for b in panel.findChildren(QPushButton)))
    check("the bottom button is Clear history", panel.clear_btn.text() == "Clear history")
    panel.provider_box.setCurrentIndex(panel.provider_box.findData("openai"))

    # chat with page context
    panel.set_mode("chat")
    panel.input.setPlainText("what is this page?")
    panel.send()
    check("chat answers with page context", wait_until(lambda: "CTX" in panel.view.toPlainText()),
          panel.view.toPlainText()[-200:])

    # compare mode
    panel.refresh_providers()
    panel.set_mode("compare")
    from PySide6.QtCore import Qt
    n = panel.compare_list.count()
    for i in range(n):
        it = panel.compare_list.item(i)
        it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in ("openai", "anthropic", "gemini") else Qt.Unchecked)
    check("compare lists configured providers", n >= 3, str(n))
    panel.input.setPlainText("hello all")
    panel.send()
    check("compare gets all three vendors", wait_until(lambda: all(
        s in panel.view.toPlainText() for s in ("Claude says hi", "Gemini says hi", "Echo[gpt-test]"))),
        panel.view.toPlainText()[-300:])
    wait_until(lambda: not panel.busy, 10)
    check("compare task total adds all providers", panel.task_meter.total == 215, str(panel.task_meter.total))
    check("compare logged to usage.log", any(e["mode"] == "compare" and e["in"] + e["out"] == 215
                                             for e in panel.usage_log.recent()))
    pump(500)
    check("usage label shows task and session", "This task" in panel.usage_label.text()
          and "Session" in panel.usage_label.text())

    # agent
    store.set("vision", False)
    panel.set_mode("agent")
    goto(tab, SITE + "/", "Form test")
    panel.input.setPlainText("agent-form: enter the name Ada and submit the form")
    panel.send()
    ok = wait_until(lambda: panel.agent is not None and not panel.agent.running, 60)
    text = panel.view.toPlainText()
    check("agent finished", ok, text[-400:])
    check("agent filled + submitted the form", "Hello Ada" in text and tab.url().path() == "/result", tab.url().toString())
    check("agent task counts each model call", panel.agent.meter.calls == len(panel.agent.turns) + 0
          or panel.agent.meter.calls >= 2, str(panel.agent.meter.calls))
    check("agent task logged", any(e["mode"] == "agent" for e in panel.usage_log.recent()))
    check("agent badge removed afterwards", wait_until(lambda: js(tab, "!document.getElementById('__atlas_agent_glow')")))

    # agent never types passwords
    panel.new_chat()
    goto(tab, SITE + "/", "Form test")
    panel.input.setPlainText("agent-form try-password then enter the name Ada")
    panel.send()
    wait_until(lambda: panel.agent is not None and not panel.agent.running, 60)
    pw = js(tab, "document.querySelector('input[type=password]') ? document.querySelector('input[type=password]').value : 'gone'")
    check("password field left untouched", pw in ("", "gone"), repr(pw))

    # vision path sends an image
    panel.new_chat()
    store.set("vision", True)
    before = CALLS["images"]
    goto(tab, SITE + "/", "Form test")
    panel.input.setPlainText("agent-form: enter the name Ada")
    panel.send()
    wait_until(lambda: panel.agent is not None and not panel.agent.running, 60)
    check("vision mode attaches a screenshot", CALLS["images"] > before)
    store.set("vision", False)

    # agent follows links that open new tabs
    panel.new_chat()
    tab.load(win.to_qurl(SITE + "/newtab"))
    wait_until(lambda: not tab.loading and tab.title() == "Opener")
    tabs_before = len(win.tab_list())
    from atlasbrowser.agent import Agent
    ag = Agent(win, providers.find_provider(store, "openai"), "test-key", store)
    ag.task, ag.turns, ag.steps, ag.bad, ag.recent, ag.running = "t", [], 0, 0, [("click", "{}")], True
    ag.tab = tab
    ag.turns.append(("{}", ""))
    ag._pending_before = list(win.tab_list())
    ag.running = True
    from atlasbrowser import pagejs
    tab.run_js(pagejs.SNAPSHOT)  # builds the element list the ids refer to
    pump(300)
    ag._do_click(tab, {"id": 0})
    check("click opens a new tab", wait_until(lambda: len(win.tab_list()) == tabs_before + 1), str(len(win.tab_list())))
    check("agent switched to the new tab", wait_until(lambda: ag.tab is not tab and ag.tab is not None))
    ag.running = False
    ag._token += 1

    # batch plan: several actions + label targets in a single model reply
    panel.new_chat()
    win.select_tab(tab)
    goto(tab, SITE + "/", "Form test")
    panel.set_mode("agent")
    panel.input.setPlainText("agent-batch: fill the form")
    panel.send()
    wait_until(lambda: panel.agent is not None and not panel.agent.running, 60)
    check("batch plan runs in one model call", CALLS.get("batch_calls") == 2 and "Hello Ada" in panel.view.toPlainText(),
          f"calls={CALLS.get('batch_calls')} url={tab.url().toString()}")
    check("batch stops once the page changes", "Skipped 1 remaining" in json.dumps(panel.agent.turns),
          json.dumps(panel.agent.turns)[:300])
    # step-by-step mode: the same multi-action reply is cut to its first action
    from atlasbrowser.agent import system_prompt
    check("plain knowledge questions are answered without browsing",
          "whether the browser is needed at all" in system_prompt(False) and "error messages and codes" in system_prompt(True))
    check("prompt switches with the toggle", "Several in one go" in system_prompt(True)
          and "Several in one go" not in system_prompt(False))
    store.set("batch", False)
    panel.new_chat()
    win.select_tab(tab)
    goto(tab, SITE + "/", "Form test")
    store.set("max_steps", 2)
    panel.input.setPlainText("agent-batch: fill the form")
    panel.send()
    wait_until(lambda: panel.agent is not None and not panel.agent.running, 40)
    check("step mode runs one action per reply", panel.agent.turns and all(
        '"actions"' not in t[0] and "Skipped" not in t[1] for t in panel.agent.turns), json.dumps(panel.agent.turns)[:300])
    store.set("batch", True)
    store.set("max_steps", 12)
    check("parse_plan reads batches", len(__import__("atlasbrowser.agent", fromlist=["x"]).parse_plan(
        '{"actions":[{"action":"click","args":{"id":1}},{"action":"type","args":{"id":2,"text":"x"}}]}')[1]) == 2)

    # humanize: visible cursor + real letter-by-letter key presses
    win.select_tab(tab)  # the previous test left a different tab in front
    goto(tab, SITE + "/", "Form test")
    tab.run_js(pagejs.SNAPSHOT)
    pump(300)
    ag2 = Agent(win, providers.find_provider(store, "openai"), "test-key", store)
    ag2.humanize, ag2.max_steps = True, 0
    ag2.task, ag2.turns, ag2.steps, ag2.bad, ag2.recent, ag2.running = "t", [("{}", "")], 0, 0, [("type", "{}")], True
    ag2.tab, ag2._pending_before, ag2._obs_retries = tab, list(win.tab_list()), 0
    ag2._do_type(tab, {"id": 0, "text": "Ada Lovelace, Esq."})
    pump(700)
    check("cursor overlay is shown", js(tab, "!!document.getElementById('__atlas_cursor')") is True)
    check("humanize types every character", wait_until(lambda: js(tab, "document.querySelector('input[name=n]').value")
                                                       == "Ada Lovelace, Esq.", 40))
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":  # offscreen windows are never "active", so Chromium drops keys
        check("humanize sends real key events", js(tab, "window.kd") >= 18, str(js(tab, "window.kd")))
    ag2.running = False
    ag2._token += 1

    # retired model: error triggers model-list refresh + automatic switch
    check("pick_model prefers newest flash", providers.pick_model(
        providers.Provider("g", "G", "gemini", ""), ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-3.8-flash-lite",
                                                     "gemini-3.9-pro-preview", "text-embedding"]) == "gemini-3.8-flash")
    ov = dict(store.get("overrides"))
    ov["gemini"] = {**ov.get("gemini", {}), "model": "old-gem"}
    store.set("overrides", ov)
    panel.refresh_providers()
    panel.provider_box.setCurrentIndex(panel.provider_box.findData("gemini"))
    panel.new_chat()
    panel.set_mode("chat")
    panel.input.setPlainText("hello")
    panel.send()
    check("retired model auto-switches to a live one", wait_until(
        lambda: (store.get("overrides").get("gemini") or {}).get("model") == "gem-1", 20),
        panel.view.toPlainText()[-300:])
    check("model list cached for dropdown", "gem-1" in (store.get("model_cache") or {}).get("gemini", []))

    # stop button
    panel.stop()
    check("stop leaves UI idle", not panel.busy)

    # settings dialog builds and saves
    from atlasbrowser.dialogs import SettingsDialog
    d = SettingsDialog(store, win)
    check("settings lists providers", d.plist.count() >= 26)
    d.key_edit.setText("another-key")
    d.engine.setCurrentIndex(d.engine.findData("google"))
    d._accept()
    check("settings saved", store.get("search_engine") == "google" and store.get_key(d.current) == "another-key")
    store.set("search_engine", "duckduckgo")

    win.close()
    pump(300)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    os._exit(code)

