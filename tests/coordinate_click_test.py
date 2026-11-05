"""Local regression coverage for visual controls absent from the element list."""
import json
from types import SimpleNamespace
import unittest
from token_efficiency_test import PageTextTests
from atlasbrowser.agent import Agent
from atlasbrowser import pagejs
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView


class CoordinateTests(PageTextTests):
    def test_canvas_coordinates_and_viewport_validation(self):
        view = QWebEngineView()
        view.resize(800, 600)
        view.show()
        page = view.page()
        self.await_result(lambda cb: (page.loadFinished.connect(cb), page.setHtml(
            '<style>body{margin:0}</style><canvas width=400 height=400></canvas>'
            '<button style="position:absolute;left:500px;top:20px">Delete</button>', QUrl('https://example.test'))))
        def evaluate(script):
            return json.loads(self.await_result(lambda cb: page.runJavaScript(script, cb)))
        snap = evaluate(pagejs.SNAPSHOT)
        self.assertEqual(snap['vw'], 800)
        self.assertFalse(any(i['tag'] == 'canvas' for i in snap['items']))
        point = evaluate(pagejs.call(pagejs.PREPARE_COORDINATE_CLICK, 200, 200))
        self.assertTrue(point['ok'])
        self.assertEqual(point['kind'], 'canvas')
        for x, y in [(-1, 20), (800, 20), (20, 600)]:
            self.assertFalse(evaluate(pagejs.call(pagejs.PREPARE_COORDINATE_CLICK, x, y))['ok'])
        self.assertEqual(evaluate(pagejs.call(pagejs.PREPARE_COORDINATE_CLICK, 510, 25))['label'], 'Delete')
        view.close()
        view.deleteLater()

    def test_agent_executes_native_click_and_preserves_guard(self):
        for label, allowed in [('canvas', True), ('Delete', False)]:
            results, clicks = [], []
            state = SimpleNamespace(_token=7, running=True, guard=True,
                _int=lambda args: Agent._int(None, args),
                _result=lambda text, **kw: results.append(text),
                _allowed=lambda *a, **kw: allowed,
                _cursor_to=lambda tab, x, y, cb: cb(),
                _finish_nav=lambda tab, text: results.append(text))
            def run_js(script, cb=None):
                if cb:
                    cb(json.dumps(dict(ok=True, x=200, y=200, good=True, kind='canvas', label=label)))
            tab = SimpleNamespace(run_js=run_js, real_click=lambda x,y: clicks.append((x,y)))
            Agent._do_click(state, tab, dict(x=200, y=200))
            self.assertEqual(clicks, [(200,200)] if allowed else [])
        for args in [dict(x='bad', y=2), dict(x=float('inf'), y=2), dict(x=True,y=2), dict(x=2)]:
            Agent._do_click(state, tab, args)
        self.assertTrue(all('finite' in r for r in results[-4:]))


if __name__ == '__main__':
    unittest.main()
