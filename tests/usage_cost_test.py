"""USD accounting regressions; no real API requests or browser required.

Run: python tests/usage_cost_test.py
"""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlasbrowser.pricing import estimate_cost, lookup_rates, normalize_rates
from atlasbrowser.usage import Meter, UsageLog, format_cost


class PricingTests(unittest.TestCase):
    def test_openai_cache_discount(self):
        cost, estimated = estimate_cost("openai", "gpt-4o-mini", 10_000, 1_000, cached_in=4_000)
        self.assertAlmostEqual(cost, 0.0018)
        self.assertTrue(estimated)

    def test_anthropic_separate_cache_write_durations(self):
        cost, _ = estimate_cost("anthropic", "claude-sonnet-5-5", 6_000, 1_000,
                                cached_in=2_000, cache_write=3_000, cache_write_long=1_000)
        self.assertAlmostEqual(cost, 0.0214)

    def test_reported_cost_wins_and_zero_is_valid(self):
        self.assertEqual(estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000,
                                      reported_cost="0.027"), (0.027, False))
        self.assertEqual(estimate_cost("gateway", "unknown", 500, 400, reported_cost=0), (0, False))

    def test_bad_reported_cost_cannot_make_unknown_model_free(self):
        for value in (-1, float("nan"), float("inf"), "", "USD 1", True, {}):
            with self.subTest(value=value):
                self.assertEqual(estimate_cost("gateway", "unknown", 50, 40, reported_cost=value),
                                 (None, False))

    def test_unknown_and_gateway_models_are_not_guessed(self):
        for pid, model in (("openai", "gpt-4o-mini-turbo"), ("openai", "gpt-4o-2024-05-13"),
                           ("openrouter", "openai/gpt-4o-mini"), ("custom", "gpt-4o-mini"),
                           ("anthropic", "claude-sonnet-6")):
            with self.subTest(pid=pid, model=model):
                self.assertIsNone(lookup_rates(pid, model))

    def test_supported_snapshot_uses_known_rates(self):
        self.assertEqual(lookup_rates("openai", "gpt-4o-mini-2024-07-18"),
                         lookup_rates("openai", "gpt-4o-mini"))

    def test_local_usage_has_no_api_token_charge(self):
        for pid in ("ollama", "lmstudio"):
            self.assertEqual(estimate_cost(pid, "any-model", 10_000, 10_000), (0, False))

    def test_custom_rates_work_for_unknown_models_and_zero_free_tier(self):
        cost, estimated = estimate_cost("gateway", "new-model", 1_000_000, 1_000_000,
                                        cached_in=500_000, rates={"input": 2, "output": 8,
                                                                 "cache_input": 0.5})
        self.assertEqual(cost, 9.25)
        self.assertTrue(estimated)
        self.assertEqual(estimate_cost("gemini", "gemini-3.8-flash", 1_000, 1_000,
                                      rates={"input": 0, "output": 0}), (0, True))

    def test_invalid_custom_rates_are_rejected(self):
        for rates in ({"input": 1}, {"input": -1, "output": 2}, {"input": 1, "output": float("nan")},
                      {"input": True, "output": 2}, {"input": 1, "output": 2, "cache_input": "bad"}):
            self.assertIsNone(normalize_rates(rates))
            self.assertEqual(estimate_cost("openai", "gpt-4o-mini", 1_000, 1_000, rates=rates),
                             (None, False))

    def test_inconsistent_cache_counts_remain_unpriced(self):
        for extra in ({"cached_in": 1001}, {"cache_write": 100, "cache_write_long": 101},
                      {"cached_in": 900, "cache_write": 101}, {"cached_in": -1}, {"cached_in": []}):
            self.assertEqual(estimate_cost("openai", "gpt-4o-mini", 1000, 100, **extra), (None, False))

    def test_gemini_long_context_boundary_counts_full_prompt(self):
        self.assertAlmostEqual(estimate_cost("gemini", "gemini-2.5-pro", 200_000, 1_000)[0], 0.26)
        self.assertAlmostEqual(estimate_cost("gemini", "models/gemini-2.5-pro", 200_001, 1_000,
                                            cached_in=100_001)[0], 0.29000025)

    def test_gemini_promotional_rate_changes_on_announced_date(self):
        self.assertEqual(lookup_rates("gemini", "gemini-3.8-flash", on_date="2026-12-31")["input"], 0.75)
        self.assertEqual(lookup_rates("gemini", "gemini-3.8-flash", on_date=dt.date(2027, 1, 1))["input"], 1.50)


class MeterTests(unittest.TestCase):
    def test_backward_compatible_add_and_unknown_usd(self):
        meter = Meter()
        meter.add("old-provider", 100, 20, True)
        self.assertEqual((meter.calls, meter.inp, meter.out, meter.total), (1, 100, 20, 120))
        self.assertEqual(meter.by, {"old-provider": [1, 100, 20]})
        self.assertIn("~120 tokens", meter.short())
        self.assertIn("USD unavailable", meter.short())
        self.assertIsNone(meter.cost_usd)

    def test_known_and_unknown_usage_marks_partial_cost(self):
        meter = Meter()
        meter.add("openai", 10_000, 1_000, model="gpt-4o-mini", cached_in=4_000)
        meter.add("gateway", 10_000, 1_000, model="unknown")
        self.assertAlmostEqual(meter.cost_usd, 0.0018)
        self.assertEqual(meter.snapshot()["unpriced_calls"], 1)
        self.assertIn("partial; 1 unpriced call", meter.cost_summary())
        self.assertIn("+ USD", meter.short())
        self.assertIsNone(meter.snapshot()["by_cost"]["gateway"]["cost_usd"])

    def test_parent_receives_exact_usage_and_cost_metadata(self):
        session, task = Meter(), None
        task = Meter(session)
        task.add("anthropic", 6_000, 1_000, model="claude-sonnet-5-5", cached_in=2_000,
                 cache_write=3_000, cache_write_long=1_000)
        task.add("openrouter", 10_000, 1000, reported_cost=0.125)
        self.assertEqual(task.snapshot(), session.snapshot())
        self.assertAlmostEqual(session.cost_usd, 0.1464)

    def test_concurrent_compare_counts_are_consistent(self):
        session = Meter()
        meters = [Meter(session) for _ in range(6)]
        def add_calls(meter):
            for _ in range(200):
                meter.add("openrouter", 100, 50, reported_cost=0.0001)
        workers = [threading.Thread(target=add_calls, args=(meter,)) for meter in meters]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        data = session.snapshot()
        self.assertEqual((data["calls"], data["in"], data["out"], data["priced_calls"]),
                         (1200, 120_000, 60_000, 1200))
        self.assertAlmostEqual(data["cost_usd"], 0.12)

    def test_snapshot_cannot_mutate_meter(self):
        meter = Meter()
        meter.add("ollama", 10, 20)
        data = meter.snapshot()
        data["by"]["ollama"][0] = 999
        data["by_cost"]["ollama"]["cost_usd"] = 999
        self.assertEqual(meter.by["ollama"][0], 1)
        self.assertEqual(meter.cost_usd, 0)

    def test_tiny_positive_cost_is_never_displayed_as_zero(self):
        self.assertIn("<$0.00000001", format_cost({"cost_usd": 1e-12}))


class LogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "usage.log"
        self.log = UsageLog(self.path)

    def test_saved_cost_survives_future_model_and_rate_changes(self):
        meter = Meter()
        meter.add("custom", 1_000_000, 1_000_000, model="private", rates={"input": 1, "output": 4})
        self.log.record("chat", "custom", "private", "Test", meter)
        reopened = UsageLog(self.path)
        entry = reopened.recent()[0]
        self.assertEqual(entry["usage_version"], 2)
        self.assertEqual(entry["cost_usd"], 5)
        self.assertEqual(reopened.totals()["cost_usd"], 5)

    def test_all_time_total_includes_more_than_recent_history(self):
        with self.path.open("w", encoding="utf-8") as stream:
            for index in range(250):
                stream.write(json.dumps({"calls": 1, "in": 10, "out": 20, "cost_usd": 0.01,
                                         "priced_calls": 1, "task": str(index)}) + "\n")
        self.assertEqual(len(self.log.recent(200)), 200)
        total = self.log.totals()
        self.assertEqual((total["tasks"], total["calls"], total["total"]), (250, 250, 7500))
        self.assertAlmostEqual(total["cost_usd"], 2.50)

    def test_legacy_model_history_estimated_without_rewriting(self):
        legacy = {"calls": 2, "in": 10_000, "out": 1_000, "provider": "openai", "model": "gpt-4o-mini"}
        self.path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        total = self.log.totals()
        self.assertAlmostEqual(total["cost_usd"], 0.0021)
        self.assertTrue(total["cost_estimated"])
        self.assertNotIn("cost_usd", json.loads(self.path.read_text()))

    def test_unknown_legacy_history_remains_unavailable_and_corrupt_lines_ignored(self):
        entry = {"calls": 2, "in": 100, "out": 20, "provider": "unknown", "model": "private"}
        self.path.write_text("{broken\n[]\n{}\n" + json.dumps(entry) + "\n", encoding="utf-8")
        total = self.log.totals()
        self.assertIsNone(total["cost_usd"])
        self.assertEqual((total["tasks"], total["unpriced_calls"]), (1, 2))
        self.assertIn("unavailable", self.log.cost_summary(entry))

    def test_mixed_history_reports_partial_not_fabricated_zero(self):
        meter = Meter()
        meter.add("openrouter", 100, 50, reported_cost=0.005)
        self.log.record("chat", "openrouter", "model", "Known", meter)
        meter = Meter()
        meter.add("custom", 100, 50, model="unpriced")
        self.log.record("chat", "custom", "unpriced", "Unknown", meter)
        total = self.log.totals()
        self.assertEqual((total["cost_usd"], total["priced_calls"], total["unpriced_calls"]), (0.005, 1, 1))
        self.assertIn("partial", format_cost(total))

    def test_invalid_saved_amount_cannot_be_counted_as_priced(self):
        self.assertEqual(UsageLog.cost_data({"calls": 2, "cost_usd": "NaN", "priced_calls": 2})["unpriced_calls"], 2)

    def test_legacy_gemini_multiple_call_context_tier_unknown(self):
        entry = {"calls": 2, "in": 300_000, "out": 2_000, "provider": "gemini", "model": "gemini-2.5-pro"}
        self.assertIsNone(UsageLog.cost_data(entry)["cost_usd"])

    def test_empty_history_is_zero_and_recent_zero_is_empty(self):
        self.assertEqual(self.log.totals()["cost_usd"], 0)
        self.assertEqual(self.log.recent(0), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
