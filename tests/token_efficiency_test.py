"""Token savings and evidence/safety retention; local tests never call an AI provider."""
import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

from atlasbrowser import pagejs
from atlasbrowser.agent import Agent, _compact_action, parse_plan


class ContextTests(unittest.TestCase):
    def agent(self, turns=(), saver=True):
        # Build only the state used by the pure context builder, without creating a GUI agent.
        state = type("Context", (), {})()
        state.token_saver = saver
        state.task = "Compare sources. Ask before publishing. Keep prices in USD."
        state.turns = list(turns)
        state._compact_messages = lambda obs: Agent._compact_messages(state, obs)
        return state

    def messages(self, state, obs="CURRENT PAGE\nInteractive elements:\n[37] <button> Buy"):
        return Agent._messages(state, obs)

    def test_task_decisions_and_fresh_ids_survive_long_run(self):
        turns = [(json.dumps({"action": "ask_user", "args": {"question": "Publish?"}}),
                  "The user replied: Save a draft only; use 2026 prices."),
                 (json.dumps({"action": "click", "args": {"target": "Publish"}}),
                  "The user declined this click. Ask them how to proceed.")]
        turns += [(json.dumps({"thought": "working", "action": "scroll", "args": {"pages": 1}}),
                   f"Scrolled to {i}.") for i in range(100)]
        msgs = self.messages(self.agent(turns))
        text = "\n".join(m["content"] for m in msgs)
        self.assertIn("TASK: Compare sources. Ask before publishing. Keep prices in USD.", msgs[0]["content"])
        self.assertIn("Save a draft only; use 2026 prices.", msgs[0]["content"])
        self.assertIn('"question":"Publish?"', msgs[0]["content"])
        self.assertIn("The user declined this click.", msgs[0]["content"])
        self.assertIn('"target":"Publish"', msgs[0]["content"])
        self.assertIn("[37] <button> Buy", msgs[-1]["content"])
        self.assertLess(len(text), 5000)

    def test_savings_strip_old_thoughts_not_executed_arguments(self):
        thought = "This repeats planning that has already been acted on. " * 20
        turns = [(json.dumps({"thought": thought, "action": "type", "args": {"id": i, "text": "Ada"}}),
                  f"Typed into [{i}].") for i in range(30)]
        saver = self.messages(self.agent(turns))
        original = self.messages(self.agent(turns, saver=False))
        self.assertLess(sum(len(m["content"]) for m in saver),
                        sum(len(m["content"]) for m in original) * 0.65)
        self.assertNotIn("planning that has already", str(saver))
        self.assertEqual(parse_plan(saver[-3]["content"])[1], [("type", {"id": 29, "text": "Ada"})])

    def test_fresh_extract_appears_once_and_keeps_source(self):
        excerpt = "Exact article facts and the current conclusion."
        extract = "Page text:\nSource: Report (https://example.test/report)\n" + excerpt
        turns = [(json.dumps({"action": "extract", "args": {}}), extract)]
        obs = "CURRENT PAGE\nURL: https://example.test/report\n[9] <button> Continue\nPage text excerpt:\n" + excerpt
        msgs = self.messages(self.agent(turns), obs)
        text = "\n".join(m["content"] for m in msgs)
        self.assertEqual(text.count(excerpt), 1)
        self.assertIn("https://example.test/report", msgs[0]["content"])
        self.assertIn("[9] <button> Continue", msgs[-1]["content"])

    def test_extracts_and_long_history_are_bounded_with_honest_omission(self):
        turns = []
        for i in range(20):
            extract = f"Page text:\nSource: {i} (https://example.test/{i})\n" + "long finding " * 1200
            turns.append((json.dumps({"action": "extract", "args": {}}), extract))
        turns += [(json.dumps({"action": "wait", "args": {}}), "Waited.")] * 4
        msgs = self.messages(self.agent(turns))
        text = "\n".join(m["content"] for m in msgs)
        self.assertLess(len(text), 10000)
        self.assertIn("older text shortened; extract again for exact details", text)
        for i in range(20):
            self.assertIn(f"https://example.test/{i})", text)

    def test_repeated_extract_uses_most_recent_source_in_full(self):
        source_a = "Page text:\nSource: A (https://example.test/a)\n" + "Evidence A " * 900
        source_b = "Page text:\nSource: B (https://example.test/b)\n" + "Evidence B " * 900
        record = json.dumps({"action": "extract", "args": {}})
        msgs = self.messages(self.agent([(record, source_a), (record, source_b), (record, source_a)]))
        self.assertIn(source_a, msgs[0]["content"])
        self.assertEqual(msgs[0]["content"].count("Source: A"), 1)

    def test_latest_failures_and_invalid_replies_are_retained(self):
        turns = [("not JSON", 'Invalid reply. Respond with exactly one JSON object: {"action":"wait"}'),
                 (json.dumps({"action": "click", "args": {"id": 2}}),
                  "Element 2 is gone. WARNING: repeated action; try something different.")]
        msgs = self.messages(self.agent(turns))
        self.assertIn("Invalid reply", str(msgs))
        self.assertIn("Element 2 is gone", str(msgs))
        self.assertIn("WARNING", str(msgs))

    def test_action_batches_keep_all_arguments(self):
        record = json.dumps({"thought": "fill and submit", "actions": [
            {"action": "type", "args": {"target": "Email", "text": "test@example.test"}},
            {"action": "click", "args": {"target": "Submit"}}]})
        self.assertEqual(parse_plan(record)[1], parse_plan(_compact_action(record))[1])

    def test_snapshot_keeps_unique_controls_and_safety_state(self):
        tab = type("Tab", (), {"title": lambda _: "Form"})()
        state = self.agent()
        state.win = type("Win", (), {"tab_list": lambda _: [tab]})()
        snap = {"url": "https://example.test", "title": "Form", "scrollY": 0, "scrollMax": 0,
                "text": "Form", "items": [
                    {"i": 0, "tag": "input:text", "text": "Email", "placeholder": "Email", "inView": True},
                    {"i": 1, "tag": "input:password", "text": "Password", "inView": True},
                    {"i": 2, "tag": "input:checkbox", "text": "Agree", "checked": False, "inView": True},
                    {"i": 3, "tag": "button", "text": "Publish", "disabled": True, "inView": True},
                    {"i": 4, "tag": "button", "text": "Publish", "inView": False}]}
        text = Agent._format(state, snap, tab)
        for i in range(5):
            self.assertIn(f"[{i}]", text)
        self.assertIn("checked=false", text)
        self.assertIn("disabled=true", text)
        self.assertIn("input:password", text)
        self.assertIn("(offscreen)", text)
        self.assertNotIn("placeholder=", text)


class AdaptiveVisionTests(unittest.TestCase):
    def setUp(self):
        self.tab = object()
        self.snap = {"url": "https://example.test/form", "scrollY": 0,
                     "text": "A readable form", "items": [{"i": 1}], "visual": False}
        self.agent = type("VisionState", (), {})()
        self.agent.token_saver = True
        self.agent.vision_every_step = False
        self.agent.bad = 0
        self.agent._last_ok = True
        self.agent._obs_retries = 0
        self.agent._last_vision_state = None
        self.agent._vision_state = lambda snap, tab: Agent._vision_state(self.agent, snap, tab)

    def capture(self, snap=None, tab=None):
        return Agent._needs_screenshot(self.agent, self.snap if snap is None else snap,
                                       self.tab if tab is None else tab)

    def test_first_new_url_scroll_and_tab_capture_then_textual_progress_skips(self):
        self.assertTrue(self.capture())
        self.agent._last_vision_state = self.agent._vision_state(self.snap, self.tab)
        self.assertFalse(self.capture())
        self.assertFalse(self.capture({**self.snap, "text": "Form typed", "items": [{"i": 19}]}))
        self.assertTrue(self.capture({**self.snap, "url": "https://example.test/other"}))
        self.assertTrue(self.capture({**self.snap, "scrollY": 500}))
        self.assertTrue(self.capture(tab=object()))

    def test_visual_content_empty_dom_and_failures_always_capture(self):
        self.agent._last_vision_state = self.agent._vision_state(self.snap, self.tab)
        for snap in ({**self.snap, "visual": True}, {**self.snap, "text": ""}, {**self.snap, "items": []}):
            self.assertTrue(self.capture(snap))
        self.agent.bad = 1
        self.assertTrue(self.capture())
        self.agent.bad = 0
        self.agent._last_ok = False
        self.assertTrue(self.capture())
        self.agent._last_ok = True
        self.agent._obs_retries = 1
        self.assertTrue(self.capture())

    def test_explicit_full_mode_and_saver_off_always_capture(self):
        self.agent._last_vision_state = self.agent._vision_state(self.snap, self.tab)
        self.agent.vision_every_step = True
        self.assertTrue(self.capture())
        self.agent.vision_every_step = False
        self.agent.token_saver = False
        self.assertTrue(self.capture())

    def test_skipped_image_observation_explicitly_relies_on_fresh_dom(self):
        state = self.agent
        state.vision = True
        state.provider = type("Provider", (), {"vision": True})()
        state.running, state._token = True, 4
        state._live_tab = lambda: self.tab
        state._last_vision_state = state._vision_state(self.snap, self.tab)
        state._needs_screenshot = lambda snap, tab: Agent._needs_screenshot(state, snap, tab)
        state._format = lambda snap, tab: "CURRENT PAGE\n[19] <button> Continue\nPage text excerpt:\nA readable form"
        calls = []
        state._think = lambda obs, images: calls.append((obs, images))
        Agent._observed(state, 4, json.dumps({**self.snap, "ready": "complete"}))
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][1])
        self.assertIn("No screenshot attached this turn; rely on current DOM, not earlier visuals.", calls[0][0])
        self.assertIn("[19] <button> Continue", calls[0][0])
        self.assertTrue(calls[0][0].endswith("A readable form"))


class PageTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def await_result(self, call):
        results = []
        call(results.append)
        deadline = time.monotonic() + 8
        while not results and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(results, "local page callback timed out")
        return results[0]

    def test_javascript_compacts_repetition_without_losing_duplicate_buttons(self):
        view = QWebEngineView()
        view.resize(800, 600)
        view.show()
        page = view.page()
        html = "<title>Token test</title><p>  Repeated   line </p>"
        html += "<p>Repeated line</p><p>Repeated line</p><p>Distinct final fact.</p>"
        html += "<button>Delete</button><button>Delete</button><input type=password placeholder=Password>"
        self.await_result(lambda cb: (page.loadFinished.connect(cb), page.setHtml(html, QUrl("https://example.test/"))))
        snap = json.loads(self.await_result(lambda cb: page.runJavaScript(pagejs.SNAPSHOT, cb)))
        self.assertIn("Repeated line [repeated x3]", snap["text"])
        self.assertIn("Distinct final fact.", snap["text"])
        self.assertEqual(len([i for i in snap["items"] if i["text"] == "Delete"]), 2)
        refs = self.await_result(lambda cb: page.runJavaScript("window.__atlasRefs.length", cb))
        self.assertEqual(refs, len(snap["items"]))
        self.assertEqual(len({i["i"] for i in snap["items"]}), len(snap["items"]))
        full = json.loads(self.await_result(lambda cb: page.runJavaScript(pagejs.FULL_TEXT, cb)))
        self.assertIn("Repeated line [repeated x3]", full["text"])
        self.assertIn("Distinct final fact.", full["text"])
        self.assertFalse(snap["visual"], "ordinary buttons do not force paid vision every turn")
        self.await_result(lambda cb: page.runJavaScript(
            "const c=document.createElement('canvas');c.width=320;c.height=200;document.body.prepend(c);true", cb))
        visual_snap = json.loads(self.await_result(lambda cb: page.runJavaScript(pagejs.SNAPSHOT, cb)))
        self.assertTrue(visual_snap["visual"], "visible canvas must retain screenshots even alongside readable text")
        view.close()
        view.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
