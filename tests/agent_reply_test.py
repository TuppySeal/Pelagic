"""Agent completion budgeting and malformed-response recovery; no paid calls."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlasbrowser import agent


class ReplyTests(unittest.TestCase):
    def test_retries_increase_budget_and_request_short_action(self):
        budgets = []
        state = SimpleNamespace(steps=0, max_steps=30, _token=1, provider=None,
            key='', meter=None, batch=False, _messages=lambda obs: [{'role':'user','content':obs}],
            _thought=lambda *args: None)
        def chat(*args, **kwargs):
            budgets.append(kwargs['max_tokens'])
            if state.bad:
                self.assertIn('one short action', args[2][-1]['content'])
            return '{"action":"wait","args":{"seconds":1}}'
        with patch.object(agent, 'run_in_pool', side_effect=lambda token, fn, cb: fn()), \
             patch.object(agent.providers, 'chat', side_effect=chat):
            for bad in range(3):
                state.bad = bad
                agent.Agent._think(state, 'CURRENT PAGE', None)
        self.assertEqual(budgets, [4096, 8192, 16384])

    def test_invalid_reply_is_not_replayed_and_does_not_act(self):
        events = []
        state = SimpleNamespace(_token=1, running=True, bad=0, turns=[],
            log=SimpleNamespace(emit=lambda text: events.append(text)),
            _observe=lambda: events.append('observe'),
            _end=lambda status, text: events.append(text))
        malformed = '{"thought":"long unfinished analysis'
        agent.Agent._thought(state, 1, malformed)
        self.assertEqual(state.turns[0][0], '{}')
        self.assertNotIn(malformed, str(state.turns))
        agent.Agent._thought(state, 1, '')
        agent.Agent._thought(state, 1, '')
        self.assertIn('empty answer', events[-1])
        self.assertEqual(events.count('observe'), 2)


if __name__ == '__main__':
    unittest.main()
