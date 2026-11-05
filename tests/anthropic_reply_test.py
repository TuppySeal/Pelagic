"""Claude replies: refusals, thinking-only replies and model fallbacks give a clear message instead of an empty
reply, and current Claude models have prices.

Run:  python tests/anthropic_reply_test.py
"""
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlasbrowser import pricing, providers  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def reply(text="", stop="end_turn", model=None, **extra):
    content = [{"type": "thinking", "thinking": ""}] + ([{"type": "text", "text": text}] if text else [])
    return {"content": content, "stop_reason": stop, "model": model,
            "usage": {"input_tokens": 255, "output_tokens": 0 if not text else 9}, **extra}


def main():
    base = next(p for p in providers.PRESETS if p.id == "anthropic")
    calls = []

    def fake(answers):
        def _http(url, headers, body, timeout, retries=3):
            calls.append((headers, body))
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        providers._http = _http

    def ask(model):
        return providers.chat(replace(base, model=model), "key", [{"role": "user", "content": "hi"}], "")

    fable = "claude-fable-5"
    fake([reply(stop="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None})])
    try:
        ask(fable)
        check("a refusal is reported, not shown as an empty reply", False)
    except providers.ProviderError as e:
        check("a refusal is reported, not shown as an empty reply", "declined" in str(e) and "cyber" in str(e), str(e))
    check("Fable gets room to think and answer", calls[-1][1]["max_tokens"] >= 16000, str(calls[-1][1]["max_tokens"]))
    fake([reply(stop="max_tokens")])
    try:
        ask(fable)
        check("running out of tokens while thinking is explained", False)
    except providers.ProviderError as e:
        check("running out of tokens while thinking is explained", "output limit" in str(e), str(e))
    fake([reply(stop="end_turn"), reply("Here you go")])
    out = ask("claude-sonnet-5")
    h, b = calls[-1]
    check("a thinking-only reply is asked again once", out == "Here you go" and len(b["messages"]) == 3
          and b["messages"][1]["role"] == "assistant" and b["messages"][1]["content"][0]["type"] == "thinking"
          and b["messages"][2]["role"] == "user", str(b["messages"]))
    fake([reply(stop="end_turn"), reply(stop="end_turn")])
    try:
        ask("claude-sonnet-5")
        check("twice empty gives a short, friendly error", False)
    except providers.ProviderError as e:
        check("twice empty gives a short, friendly error", "without writing an answer" in str(e)
              and "Raw response" not in str(e) and len(str(e)) < 200, str(e))
    check("and it doesn't keep asking", not calls or len(calls[-1][1]["messages"]) == 3)
    fake([reply("Hello", model=fable)])
    check("a normal reply still works", ask(fable) == "Hello")
    check("Fable 5 isn't sent the fallback option", "fallbacks" not in calls[-1][1])

    fake([reply("SIGHT", model="claude-opus-5-5")])
    out = ask("claude-opus-5-5")
    h, b = calls[-1]
    check("Opus 5.5 asks for automatic fallback", b.get("fallbacks") == "default"
          and h.get("anthropic-beta") == "server-side-fallback-2026-07-01")
    check("same model: no note", out == "SIGHT")
    fake([reply("SIGHT", model="claude-opus-4-8")])
    out = ask("claude-opus-5-5")
    check("a fallback answer says which model answered", "Answered by claude-opus-4-8" in out, out)
    fake([providers.ProviderError("HTTP 400: fallbacks: not enabled for this organization"), reply("OK")])
    check("if fallbacks aren't allowed it asks again without them", ask("claude-sonnet-5-5") == "OK"
          and "fallbacks" not in calls[-1][1])
    fake([providers.ProviderError("HTTP 401: invalid x-api-key  (check the API key)")])
    try:
        ask("claude-sonnet-5-5")
        check("real API errors come through", False)
    except providers.ProviderError as e:
        check("real API errors come through", "401" in str(e))

    for m in ("claude-fable-5", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5",
              "claude-haiku-5-5", "claude-opus-4-8"):
        r = pricing.lookup_rates("anthropic", m)
        check(f"{m} has a price", r is not None and r["input"] > 0)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
