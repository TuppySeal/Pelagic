import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlasbrowser.store import Store
from atlasbrowser.context import core_system, estimate_context
from atlasbrowser import agent
from atlasbrowser.panel import AIPanel
from PySide6.QtWidgets import QApplication, QProgressBar
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QSpinBox


class CoreContextTests(unittest.TestCase):
    def test_panel_editor_saves_and_new_chat_keeps_core(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            with patch.object(AIPanel, 'auto_refresh_models'):
                panel = AIPanel(SimpleNamespace(private=True), store)
            def edit(dialog):
                dialog.findChild(QPlainTextEdit).setPlainText('Keep my core instructions.')
                dialog.findChild(QSpinBox).setValue(64000)
                return QDialog.Accepted
            with patch.object(QDialog, 'exec', edit):
                panel._edit_core()
            self.assertEqual(store.get('core_instructions'), 'Keep my core instructions.')
            panel._show_context(16000)
            self.assertEqual(panel.context_bar.value(), 25)
            panel.new_chat()
            self.assertEqual(panel.context_bar.value(), 0)
            self.assertIn('Keep my core instructions.', core_system(store))
            panel.close()
            panel._usage_timer.stop()
            panel.deleteLater()
            app.processEvents()
            store._db.close()

    def test_saved_instructions_survive_restart_and_each_compacted_request(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Store(Path(folder))
            first.set('core_instructions', 'Always verify each move.')
            first._db.close()
            second = Store(Path(folder))
            self.assertIn('Always verify each move.', core_system(second))
            state = SimpleNamespace(steps=0, max_steps=100, _token=1,
                provider=None, key='', meter=None, batch=False, bad=0,
                core_instructions=core_system(second),
                _messages=lambda obs: [{'role':'user','content':obs}], _thought=lambda *a: None)
            systems = []
            with patch.object(agent, 'run_in_pool', side_effect=lambda t, fn, cb: fn()), \
                 patch.object(agent.providers, 'chat', side_effect=lambda *a, **k: systems.append(a[3])):
                for turn in range(20):
                    agent.Agent._think(state, f'Compacted turn {turn}', None)
            self.assertTrue(all('Always verify each move.' in system for system in systems))
            self.assertEqual(len(systems), 20)
            second._db.close()

    def test_indicator_percentage_and_overflow_are_honest(self):
        app = QApplication.instance() or QApplication([])
        bar = QProgressBar()
        bar.setRange(0, 100)
        state = SimpleNamespace(store=SimpleNamespace(get=lambda key: 10000), context_bar=bar)
        AIPanel._show_context(state, 2500)
        self.assertEqual(bar.value(), 25)
        self.assertIn('25%', bar.format())
        AIPanel._show_context(state, 12000)
        self.assertEqual(bar.value(), 100)
        self.assertIn('120%', bar.format())
        self.assertGreater(estimate_context([{'content':'abc'}], images=['image']), 1000)


if __name__ == '__main__':
    unittest.main()
