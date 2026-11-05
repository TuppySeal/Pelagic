"""The agent can tick checkboxes, radios and switches, and knows when it has.

Regression: clicks on checkboxes worked, but the agent saw "on" as every checkbox's name, no state for custom
(hidden-input or ARIA) checkboxes, and nothing at all for hidden inputs, so it decided the click failed, clicked
again (unticking it) and gave up. Local only: a real Qt WebEngine page, no AI provider.
"""
import json
import time
import types
import unittest
from types import SimpleNamespace

from token_efficiency_test import PageTextTests
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from atlasbrowser import pagejs
from atlasbrowser.agent import Agent, SYSTEM_PROMPT
from atlasbrowser.webview import BrowserTab

WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld

PAGE = """<style>
body{margin:20px;font:16px sans-serif} div,label{margin:6px 0;display:block}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.op{opacity:0;position:absolute} .gone{display:none}
.box{display:inline-block;width:16px;height:16px;border:1px solid #333}
</style>
<label><input type=checkbox name=terms id=terms> I agree to the terms</label>
<div><input type=checkbox id=news><label for=news>Send me news</label></div>
<label><input type=checkbox class=vh id=remember><span class=box></span> Remember me</label>
<label><input type=checkbox class=op id=faded><span class=box></span> Faded checkbox</label>
<div><input type=checkbox class=gone id=toggle><label for=toggle><span class=box></span> CSS toggle</label></div>
<div role=checkbox aria-checked=false tabindex=0 id=aria
     onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked') !== 'true')">ARIA checkbox</div>
<button role=switch aria-checked=true id=dark
     onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked') !== 'true')">Dark mode</button>
<label><input type=radio name=size value=s id=small> Small</label>
<label><input type=radio name=size value=l id=large> Large</label>
<label><input type=checkbox id=locked onclick="return false"> Locked</label>
"""


class Tab(QWebEngineView):
    """Just what the agent's click path needs from a Pelagic tab."""
    real_click = BrowserTab.real_click

    def _target(self):
        return self.focusProxy() or self

    def run_js(self, code, cb=None):
        if cb is None:
            self.page().runJavaScript(code, WORLD)
        else:
            self.page().runJavaScript(code, WORLD, cb)


class CheckboxTests(PageTextTests):
    def setUp(self):
        self.tab = Tab()
        self.tab.resize(800, 700)
        self.tab.show()
        page = self.tab.page()
        self.await_result(lambda cb: (page.loadFinished.connect(cb), page.setHtml(PAGE, QUrl("https://example.test/"))))

    def tearDown(self):
        self.tab.close()
        self.tab.deleteLater()

    def js(self, code):
        return self.await_result(lambda cb: self.tab.run_js(code, cb))

    def snapshot(self):
        return {it["text"]: it for it in json.loads(self.js(pagejs.SNAPSHOT))["items"]}

    def pump(self, ms):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def agent(self, results):
        state = SimpleNamespace(_token=1, running=True, guard=False,
                                _int=lambda args, key="id": Agent._int(None, args, key),
                                _result=lambda text, **kw: results.append(text),
                                _allowed=lambda *a, **kw: True,
                                _cursor_to=lambda tab, x, y, cb: cb(),
                                _finish_nav=lambda tab, text: results.append(text))
        state._confirm_toggle = types.MethodType(Agent._confirm_toggle, state)
        return state

    def click(self, args):
        results = []
        Agent._do_click(self.agent(results), self.tab, args)
        deadline = time.monotonic() + 5
        while not results and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(results, "click never reported back")
        self.pump(100)
        return results

    def checked(self, el_id):
        return self.js(f"document.getElementById('{el_id}').checked")

    def test_every_kind_of_checkbox_is_listed_with_its_label_and_state(self):
        items = self.snapshot()
        for name in ("I agree to the terms", "Send me news", "Remember me", "Faded checkbox", "CSS toggle",
                     "ARIA checkbox", "Small", "Large"):
            self.assertIn(name, items, f"{name} missing from {list(items)}")
            self.assertIs(items[name]["checked"], False, name)
        self.assertIs(items["Dark mode"]["checked"], True)
        self.assertNotIn("on", items)   # a checkbox's value is not its name
        self.assertEqual(items["ARIA checkbox"]["tag"], "div[checkbox]")

    def test_agent_clicks_tick_each_checkbox_once_and_say_so(self):
        items = self.snapshot()
        for name, el_id in (("I agree to the terms", "terms"), ("Send me news", "news"),
                            ("Remember me", "remember"), ("Faded checkbox", "faded"), ("CSS toggle", "toggle")):
            results = self.click({"id": items[name]["i"]})
            self.assertTrue(self.checked(el_id), name)
            self.assertIn("It is now checked (was unchecked)", results[-1], name)
            self.assertIn("The click worked", results[-1])
        after = self.snapshot()
        self.assertTrue(all(after[n]["checked"] for n in ("I agree to the terms", "Remember me", "CSS toggle")))

    def test_aria_checkbox_switch_and_radio(self):
        items = self.snapshot()
        self.assertIn("It is now checked", self.click({"id": items["ARIA checkbox"]["i"]})[-1])
        self.assertEqual(self.js("document.getElementById('aria').getAttribute('aria-checked')"), "true")
        self.assertIn("It is now unchecked (was checked)", self.click({"id": items["Dark mode"]["i"]})[-1])
        self.assertIn("now checked", self.click({"id": items["Large"]["i"]})[-1])
        self.assertTrue(self.checked("large"))
        # clicking a radio that is already chosen keeps it chosen, which is still success
        self.assertIn("It is selected. The click worked.", self.click({"id": self.snapshot()["Large"]["i"]})[-1])

    def test_coordinate_click_on_a_label_reports_the_checkbox(self):
        rect = json.loads(self.js("JSON.stringify(document.querySelector('label[for=toggle]').getBoundingClientRect())"))
        results = self.click({"x": rect["left"] + 30, "y": rect["top"] + rect["height"] / 2})
        self.assertTrue(self.checked("toggle"))
        self.assertIn('"CSS toggle"', results[-1])
        self.assertIn("It is now checked", results[-1])

    def test_page_that_refuses_the_change_is_reported_without_double_toggling(self):
        results = self.click({"id": self.snapshot()["Locked"]["i"]})
        self.assertFalse(self.checked("locked"))
        self.assertIn("It is still unchecked", results[-1])

    def test_slow_page_is_not_toggled_twice(self):
        # The page flips the box 300 ms after the click, after the first read-back.
        self.js("""(() => { const b = document.getElementById('terms'); b.onclick = (e) => { e.preventDefault();
                   setTimeout(() => { b.checked = !b.checked; }, 300); }; return 1; })()""")
        results = self.click({"id": self.snapshot()["I agree to the terms"]["i"]})
        self.pump(800)   # a second, unneeded click would flip it back by now
        self.assertTrue(self.checked("terms"))
        self.assertIn("It is now checked", results[-1])

    def test_prompt_tells_the_model_to_trust_the_result(self):
        self.assertIn("never click it again", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
