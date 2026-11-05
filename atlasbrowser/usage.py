"""Thread-safe token and USD accounting, with persistent task history."""
from __future__ import annotations

import collections
import json
import threading
import time

from .pricing import PRICING_CHECKED, estimate_cost, nonnegative_number


def _count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def format_cost(data: dict, compact: bool = False) -> str:
    """Never display a zero-dollar total when some or all usage is unpriced."""
    cost = nonnegative_number(data.get("cost_usd"))
    missing = _count(data.get("unpriced_calls"))
    if cost is None:
        return "USD unavailable" if compact else "USD cost unavailable (pricing needed)"
    approx = "~" if data.get("cost_estimated") else ""
    if 0 < cost < 0.00000001:
        amount = "<$0.00000001"
    else:
        amount = f"${cost:,.4f}" if cost >= 0.0001 or cost == 0 else f"${cost:.8f}".rstrip("0")
    result = f"{approx}{amount}{'+' if missing else ''} USD"
    if missing and not compact:
        result += f" (partial; {missing} unpriced {'call' if missing == 1 else 'calls'})"
    return result


class Meter:
    """A task meter also contributes each call and its cost to its session parent."""

    def __init__(self, parent: "Meter | None" = None):
        self.parent = parent
        self._lock = threading.Lock()
        self.calls = self.inp = self.out = 0
        self.estimated = False
        self.by: dict[str, list[int]] = {}
        self._cost_usd = 0.0
        self.priced_calls = self.unpriced_calls = 0
        self.cost_estimated = False
        self.by_cost: dict[str, dict] = {}

    def add(self, pid: str, inp: int, out: int, estimated: bool = False, *, model: str = "",
            cached_in: int = 0, cache_write: int = 0, cache_write_long: int = 0,
            reported_cost=None, rates=None):
        inp, out = _count(inp), _count(out)
        cost, approx_cost = estimate_cost(pid, model, inp, out, cached_in, cache_write,
                                         cache_write_long, reported_cost, rates)
        with self._lock:
            self.calls += 1
            self.inp += inp
            self.out += out
            self.estimated |= bool(estimated)
            row = self.by.setdefault(pid, [0, 0, 0])
            row[0] += 1
            row[1] += inp
            row[2] += out
            billing = self.by_cost.setdefault(pid, {"cost_usd": 0.0, "priced_calls": 0,
                                                    "unpriced_calls": 0, "cost_estimated": False})
            if cost is None:
                self.unpriced_calls += 1
                billing["unpriced_calls"] += 1
            else:
                self._cost_usd += cost
                self.priced_calls += 1
                self.cost_estimated |= approx_cost
                billing["cost_usd"] += cost
                billing["priced_calls"] += 1
                billing["cost_estimated"] |= approx_cost
        if self.parent is not None:
            self.parent.add(pid, inp, out, estimated, model=model, cached_in=cached_in,
                            cache_write=cache_write, cache_write_long=cache_write_long,
                            reported_cost=reported_cost, rates=rates)

    def snapshot(self) -> dict:
        """A consistent copy that UI readers can use while Compare calls run."""
        with self._lock:
            by_cost = {pid: dict(row) for pid, row in self.by_cost.items()}
            for row in by_cost.values():
                if not row["priced_calls"] and row["unpriced_calls"]:
                    row["cost_usd"] = None
            return {"calls": self.calls, "in": self.inp, "out": self.out, "total": self.inp + self.out,
                    "estimated": self.estimated, "by": {pid: list(row) for pid, row in self.by.items()},
                    "cost_usd": self._cost_usd if self.priced_calls or not self.calls else None,
                    "priced_calls": self.priced_calls, "unpriced_calls": self.unpriced_calls,
                    "cost_estimated": self.cost_estimated, "by_cost": by_cost}

    @property
    def total(self) -> int:
        return self.snapshot()["total"]

    @property
    def cost_usd(self) -> float | None:
        return self.snapshot()["cost_usd"]

    def cost_summary(self) -> str:
        return format_cost(self.snapshot())

    def cost_short(self) -> str:
        return format_cost(self.snapshot(), compact=True)

    def summary(self) -> str:
        data = self.snapshot()
        approx = "~" if data["estimated"] else ""
        plural = "call" if data["calls"] == 1 else "calls"
        return (f"{data['calls']} {plural} · {approx}{data['in']:,} in + {approx}{data['out']:,} out "
                f"= {approx}{data['total']:,} tokens · {format_cost(data)}")

    def short(self) -> str:
        data = self.snapshot()
        return (f"{'~' if data['estimated'] else ''}{data['total']:,} tokens ({data['calls']} calls)"
                f" · {format_cost(data, compact=True)}")


class UsageLog:
    """Append-only JSONL. Stored dollar amounts survive model/rate changes."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def record(self, mode: str, provider: str, model: str, task: str, meter: Meter, status: str = "done"):
        data = meter.snapshot()
        entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode, "provider": provider,
                 "model": model, "task": task[:80], "status": status, "usage_version": 2,
                 "pricing_checked": PRICING_CHECKED,
                 **{k: v for k, v in data.items() if k != "total"}}
        try:
            with self._lock, open(self.path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
        except OSError:
            pass

    def _entries(self, n=None) -> list[dict]:
        try:
            with self._lock, open(self.path, encoding="utf-8") as stream:
                lines = collections.deque(stream, maxlen=n) if n is not None else list(stream)
        except (OSError, UnicodeError):
            return []
        entries = []
        for line in lines:
            try:
                entry = json.loads(line)
                if isinstance(entry, dict) and all(k in entry for k in ("calls", "in", "out")):
                    entries.append(entry)
            except ValueError:
                pass
        return entries

    @staticmethod
    def cost_data(entry: dict) -> dict:
        """Legacy history can only be estimated from its model's listed token rates."""
        calls = _count(entry.get("calls"))
        if "cost_usd" in entry:
            cost = nonnegative_number(entry.get("cost_usd"))
            priced = min(calls, _count(entry.get("priced_calls", calls if cost is not None else 0)))
            if cost is None:
                priced = 0
            missing = max(calls - priced, _count(entry.get("unpriced_calls")))
            return {"cost_usd": cost, "priced_calls": priced, "unpriced_calls": missing,
                    "cost_estimated": bool(entry.get("cost_estimated"))}
        if not calls:
            return {"cost_usd": 0.0, "priced_calls": 0, "unpriced_calls": 0, "cost_estimated": False}
        inp, out = _count(entry.get("in")), _count(entry.get("out"))
        # With multiple calls, a large aggregate cannot reveal per-request context tiers.
        tier_unknown = (entry.get("provider") == "gemini" and
                        (entry.get("model") or "").removeprefix("models/") == "gemini-2.5-pro"
                        and calls > 1 and inp > 200_000)
        cost, estimated = ((None, False) if tier_unknown else estimate_cost(
            entry.get("provider", ""), entry.get("model", ""), inp, out, on_date=entry.get("time")))
        return {"cost_usd": cost, "priced_calls": calls if cost is not None else 0,
                "unpriced_calls": calls if cost is None else 0, "cost_estimated": estimated}

    @staticmethod
    def cost_summary(entry: dict) -> str:
        return format_cost(UsageLog.cost_data(entry))

    def recent(self, n: int = 100) -> list[dict]:
        if n <= 0:
            return []
        return self._entries(n)[::-1]

    def totals(self) -> dict:
        entries = self._entries()
        result = {"tasks": len(entries), "calls": 0, "in": 0, "out": 0, "total": 0,
                  "cost_usd": 0.0, "priced_calls": 0, "unpriced_calls": 0,
                  "cost_estimated": False, "estimated": False}
        for entry in entries:
            billing = self.cost_data(entry)
            for key in ("calls", "in", "out"):
                result[key] += _count(entry.get(key))
            result["priced_calls"] += billing["priced_calls"]
            result["unpriced_calls"] += billing["unpriced_calls"]
            result["cost_usd"] += billing["cost_usd"] or 0
            result["cost_estimated"] |= billing["cost_estimated"]
            result["estimated"] |= bool(entry.get("estimated"))
        if result["calls"] and not result["priced_calls"]:
            result["cost_usd"] = None
        result["total"] = result["in"] + result["out"]
        return result
