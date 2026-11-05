"""Conservative USD token estimates; unknown models never imply a free call.

Standard, direct-provider text/image-input pricing checked 2026-10-05:
https://developers.openai.com/api/docs/models/gpt-4o-mini
https://developers.openai.com/api/docs/models/gpt-4o
https://developers.openai.com/api/docs/models/gpt-4.1
https://developers.openai.com/api/docs/models/gpt-4.1-mini
https://platform.claude.com/docs/en/about-claude/pricing
https://ai.google.dev/gemini-api/docs/pricing

These are token estimates, not invoices: free tiers, negotiated discounts,
taxes, regional premiums, nonstandard service tiers and external tool charges
are not inferred. Rates use USD per million tokens. Custom rates override the
table; reported per-call USD costs override both.
"""
from __future__ import annotations

import datetime as dt
import math

PRICING_CHECKED = "2026-10-05"


def _rate(inp, out, cached=None, write=None, long_write=None):
    return {"input": inp, "output": out, "cache_input": inp if cached is None else cached,
            "cache_write": inp if write is None else write,
            "cache_write_long": inp if long_write is None else long_write}


_OPENAI = {
    "gpt-4o-mini": _rate(0.15, 0.60, 0.075),
    "gpt-4o-mini-2024-07-18": _rate(0.15, 0.60, 0.075),
    "gpt-4o": _rate(2.50, 10, 1.25),
    "gpt-4.1": _rate(2, 8, 0.50),
    "gpt-4.1-2025-04-14": _rate(2, 8, 0.50),
    "gpt-4.1-mini": _rate(0.40, 1.60, 0.10),
    "gpt-4.1-mini-2025-04-14": _rate(0.40, 1.60, 0.10),
}
_ANTHROPIC = {
    "claude-fable-5-1": _rate(10, 50, 0.25, 12.50, 20),
    "claude-fable-5": _rate(10, 50, 1.00, 12.50, 20),
    "claude-opus-5": _rate(5, 25, 0.50, 6.25, 10),
    "claude-opus-4-8": _rate(5, 25, 0.50, 6.25, 10),
    "claude-opus-4-7": _rate(5, 25, 0.50, 6.25, 10),
    "claude-haiku-5-5": _rate(0.10, 0.50, 0.01, 0.125, 0.20),   # prompts up to 100K tokens
    "claude-sonnet-5-5": _rate(2, 10, 0.20, 2.50, 4),
    "claude-sonnet-5": _rate(2, 10, 0.20, 2.50, 4),
    "claude-sonnet-4-6": _rate(3, 15, 0.30, 3.75, 6),
    "claude-sonnet-4-5": _rate(3, 15, 0.30, 3.75, 6),
    "claude-opus-5-5": _rate(4, 20, 0.20, 5, 8),
    "claude-opus-4-6": _rate(5, 25, 0.50, 6.25, 10),
    "claude-opus-4-5": _rate(5, 25, 0.50, 6.25, 10),
    "claude-haiku-4-5": _rate(1, 5, 0.10, 1.25, 2),
    "claude-haiku-4-5-20251001": _rate(1, 5, 0.10, 1.25, 2),
}
_GEMINI = {
    "gemini-3.5-flash": _rate(1.50, 9, 0.15),
    "gemini-3.5-flash-lite": _rate(0.30, 2.50, 0.03),
    "gemini-3.1-flash-lite": _rate(0.25, 1.50, 0.025),
    "gemini-2.5-flash": _rate(0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": _rate(0.10, 0.40, 0.01),
}


def nonnegative_number(value) -> float | None:
    """Reject booleans, NaN, infinity, negatives and malformed billing values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def normalize_rates(rates) -> dict | None:
    """Missing optional cache rates use the explicit ordinary input rate."""
    if not isinstance(rates, dict):
        return None
    inp, out = nonnegative_number(rates.get("input")), nonnegative_number(rates.get("output"))
    if inp is None or out is None:
        return None
    result = {"input": inp, "output": out}
    for key in ("cache_input", "cache_write", "cache_write_long"):
        result[key] = nonnegative_number(rates[key]) if key in rates else inp
        if result[key] is None:
            return None
    return result


def lookup_rates(pid: str, model: str, inp: int = 0, on_date=None) -> dict | None:
    """Exact known IDs only: a gateway or a similarly named model may cost differently."""
    model = (model or "").strip()
    if pid in ("ollama", "lmstudio"):
        return _rate(0, 0, 0, 0, 0)
    if pid == "openai":
        rates = _OPENAI.get(model)
    elif pid == "anthropic":
        rates = _ANTHROPIC.get(model)
    elif pid == "gemini":
        model = model.removeprefix("models/")
        if model == "gemini-2.5-pro":
            return _rate(2.50, 15, 0.25) if inp > 200_000 else _rate(1.25, 10, 0.125)
        if model in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"):
            try:
                day = dt.date.fromisoformat(str(on_date)[:10]) if on_date else dt.date.today()
            except ValueError:
                return None
            return _rate(0.75, 3.75, 0.075) if day < dt.date(2027, 1, 1) else _rate(1.50, 7.50, 0.15)
        rates = _GEMINI.get(model)
    else:
        return None
    return dict(rates) if rates else None


def estimate_cost(pid: str, model: str, inp: int, out: int, cached_in: int = 0,
                  cache_write: int = 0, cache_write_long: int = 0,
                  reported_cost=None, rates=None, on_date=None) -> tuple[float | None, bool]:
    """Return (USD, estimated). Input includes all cache buckets; long writes
    are a subset of all writes. An inconsistent breakdown remains unpriced.
    """
    reported = nonnegative_number(reported_cost)
    if reported is not None:
        return reported, False
    price = normalize_rates(rates) if rates else lookup_rates(pid, model, inp, on_date)
    if price is None:
        return None, False
    counts = tuple(nonnegative_number(n) for n in (inp, out, cached_in, cache_write, cache_write_long))
    if any(n is None for n in counts):
        return None, False
    inp, out, cached_in, cache_write, cache_write_long = counts
    if cached_in + cache_write > inp or cache_write_long > cache_write:
        return None, False
    cost = ((inp - cached_in - cache_write) * price["input"] + out * price["output"]
            + cached_in * price["cache_input"]
            + (cache_write - cache_write_long) * price["cache_write"]
            + cache_write_long * price["cache_write_long"]) / 1_000_000
    if not math.isfinite(cost):
        return None, False
    return cost, not (pid in ("ollama", "lmstudio") and not rates)
