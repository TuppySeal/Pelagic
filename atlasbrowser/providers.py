"""AI provider registry and clients (stdlib only).

Three wire formats cover everything: OpenAI-compatible chat/completions (the large majority of
vendors and local servers), Anthropic Messages, and Google Gemini generateContent.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass, field

USER_AGENT = "Pelagic/1.0"


class ProviderError(Exception):
    pass


@dataclass
class Provider:
    id: str
    name: str
    kind: str                # "openai" | "anthropic" | "gemini"
    base_url: str
    model: str = ""
    env: tuple = ()          # environment variables that may hold the key
    needs_key: bool = True
    custom: bool = False
    vision: bool = True
    token_saver: bool = True
    rates: dict | None = None


def _p(id, name, base, model, env=(), kind="openai", needs_key=True):
    return Provider(id, name, kind, base, model, tuple(env), needs_key)


PRESETS: list[Provider] = [
    _p("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta", "gemini-3.8-flash",
       ("GEMINI_API_KEY", "GOOGLE_API_KEY"), kind="gemini"),
    _p("anthropic", "Anthropic Claude", "https://api.anthropic.com", "claude-sonnet-5-5",
       ("ANTHROPIC_API_KEY",), kind="anthropic"),
    _p("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini", ("OPENAI_API_KEY",)),
    _p("openrouter", "OpenRouter (hundreds of models)", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini",
       ("OPENROUTER_API_KEY",)),
    _p("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", ("GROQ_API_KEY",)),
    _p("mistral", "Mistral AI", "https://api.mistral.ai/v1", "mistral-small-latest", ("MISTRAL_API_KEY",)),
    _p("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat", ("DEEPSEEK_API_KEY",)),
    _p("xai", "xAI Grok", "https://api.x.ai/v1", "grok-3-mini", ("XAI_API_KEY",)),
    _p("together", "Together AI", "https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo",
       ("TOGETHER_API_KEY",)),
    _p("fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1",
       "accounts/fireworks/models/llama-v3p3-70b-instruct", ("FIREWORKS_API_KEY",)),
    _p("cerebras", "Cerebras", "https://api.cerebras.ai/v1", "llama-3.3-70b", ("CEREBRAS_API_KEY",)),
    _p("sambanova", "SambaNova", "https://api.sambanova.ai/v1", "Meta-Llama-3.3-70B-Instruct", ("SAMBANOVA_API_KEY",)),
    _p("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct",
       ("NVIDIA_API_KEY",)),
    _p("perplexity", "Perplexity", "https://api.perplexity.ai", "sonar", ("PERPLEXITY_API_KEY",)),
    _p("cohere", "Cohere", "https://api.cohere.ai/compatibility/v1", "command-r-plus", ("COHERE_API_KEY",)),
    _p("huggingface", "Hugging Face Router", "https://router.huggingface.co/v1", "meta-llama/Llama-3.3-70B-Instruct",
       ("HF_TOKEN", "HUGGINGFACE_API_KEY")),
    _p("github", "GitHub Models", "https://models.github.ai/inference", "openai/gpt-4o-mini", ("GITHUB_TOKEN",)),
    _p("hyperbolic", "Hyperbolic", "https://api.hyperbolic.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct",
       ("HYPERBOLIC_API_KEY",)),
    _p("nebius", "Nebius AI Studio", "https://api.studio.nebius.com/v1", "meta-llama/Llama-3.3-70B-Instruct",
       ("NEBIUS_API_KEY",)),
    _p("siliconflow", "SiliconFlow", "https://api.siliconflow.com/v1", "Qwen/Qwen2.5-72B-Instruct",
       ("SILICONFLOW_API_KEY",)),
    _p("novita", "Novita AI", "https://api.novita.ai/v3/openai", "meta-llama/llama-3.3-70b-instruct",
       ("NOVITA_API_KEY",)),
    _p("moonshot", "Moonshot (Kimi)", "https://api.moonshot.ai/v1", "kimi-latest", ("MOONSHOT_API_KEY",)),
    _p("zhipu", "Zhipu GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash", ("ZHIPUAI_API_KEY",)),
    _p("dashscope", "Alibaba Qwen (DashScope)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus",
       ("DASHSCOPE_API_KEY",)),
    _p("ollama", "Ollama (local)", "http://localhost:11434/v1", "llama3.2", needs_key=False),
    _p("lmstudio", "LM Studio (local)", "http://localhost:1234/v1", "local-model", needs_key=False),
]


def all_providers(store) -> list[Provider]:
    """Presets with user overrides applied, followed by custom providers."""
    overrides = store.get("overrides") or {}
    out = []
    for preset in PRESETS:
        p = Provider(**{**preset.__dict__})
        ov = overrides.get(p.id, {})
        p.model = ov.get("model") or p.model
        p.base_url = ov.get("base_url") or p.base_url
        out.append(p)
    for c in store.get("custom") or []:
        out.append(Provider(id=c["id"], name=c.get("name", c["id"]), kind=c.get("kind", "openai"),
                            base_url=c.get("base_url", ""), model=c.get("model", ""),
                            needs_key=c.get("needs_key", True), custom=True))
    for p in out:
        p.token_saver = store.get("token_saver") is not False
        p.rates = (store.get("price_overrides") or {}).get(f"{p.id}:{p.model}")
        direct_hosts = {"openai": "api.openai.com", "anthropic": "api.anthropic.com",
                        "gemini": "generativelanguage.googleapis.com"}
        hostname = urlparse(p.base_url).hostname
        if p.rates is None and ((p.id in direct_hosts and hostname != direct_hosts[p.id]) or
                               (p.id in ("ollama", "lmstudio") and hostname not in ("localhost", "127.0.0.1", "::1"))):
            p.rates = {"unavailable": True}  # A different endpoint may have different billing.
    return out


def find_provider(store, pid: str) -> Provider | None:
    return next((p for p in all_providers(store) if p.id == pid), None)


def resolve_key(store, p: Provider) -> str:
    key = store.get_key(p.id)
    if key:
        return key
    for var in p.env:
        if os.environ.get(var):
            return os.environ[var]
    return ""


def is_configured(store, p: Provider) -> bool:
    return bool(resolve_key(store, p)) or not p.needs_key


# ---------------------------------------------------------------- HTTP
_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def _http(url: str, headers: dict, body: dict | None, timeout: float, retries: int = 3):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers}
    last = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}: {_extract_error(raw)}"
            if e.code in _RETRY_STATUS and attempt < retries:
                try:
                    wait = min(float(e.headers.get("Retry-After", "")), 20)
                except (TypeError, ValueError):
                    wait = 1.5 * (2 ** attempt)
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                last += "  (check the API key)"
            raise ProviderError(last) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = f"Network error: {getattr(e, 'reason', e)}"
            if data is not None:
                raise ProviderError(last + " (not retried: the server may already have processed this paid request)") from None
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise ProviderError(last) from None
        except ValueError:
            raise ProviderError("The server returned a response that is not JSON.") from None
    raise ProviderError(last or "Request failed")


def _extract_error(raw: str) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        return raw[:300].strip() or "(empty response)"
    err = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(err, dict):
        return str(err.get("message") or err.get("detail") or err)[:400]
    if isinstance(err, list) and err:
        return str(err[0])[:400]
    return str(err)[:400]


# ---------------------------------------------------------------- chat
def chat(p: Provider, key: str, messages: list[dict], system: str = "", images: list[str] | None = None,
         timeout: float = 120.0, max_tokens: int = 4096, meter=None) -> str:
    """messages: [{"role": "user"|"assistant", "content": str}]; images (base64 PNG) attach to the last user turn.

    meter (usage.Meter) records provider-reported token usage, or a chars/4 estimate when none is reported.
    """
    if not p.base_url:
        raise ProviderError("No base URL configured for this provider.")
    if p.needs_key and not key:
        raise ProviderError(f"No API key set for {p.name}. Add one in Settings → AI providers.")
    if not (p.model or "").strip():
        raise ProviderError(f"No model selected for {p.name}.")
    messages = _merge_roles(messages)
    started = time.time()
    try:
        if p.kind == "anthropic":
            text, usage = _chat_anthropic(p, key, messages, system, images, timeout, max_tokens)
        elif p.kind == "gemini":
            text, usage = _chat_gemini(p, key, messages, system, images, timeout, max_tokens)
        else:
            text, usage = _chat_openai(p, key, messages, system, images, timeout, max_tokens)
    except Exception as e:
        _report(p, system, messages, images, None, e, started)
        raise
    _report(p, system, messages, images, text, None, started)
    if meter is not None:
        if usage is None:
            sent = len(system) + sum(len(m["content"]) for m in messages) + 800 * len(images or [])
            meter.add(p.id, max(1, sent // 4), len(text) // 4, True, model=p.model, rates=p.rates)
        else:
            meter.add(p.id, usage["inp"], usage["out"], False, model=p.model, rates=p.rates,
                      cached_in=usage.get("cached_in", 0), cache_write=usage.get("cache_write", 0),
                      cache_write_long=usage.get("cache_write_long", 0), reported_cost=usage.get("reported_cost"))
    return text


# Listeners for every request and raw reply (the AI panel's Raw view). Called on worker threads.
CALL_LISTENERS: list = []

# Claude models that support Anthropic's automatic hand-off to another model when their safety filter declines
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


def _report(p, system, messages, images, text, error, started):
    if not CALL_LISTENERS:
        return
    entry = {"time": started, "seconds": time.time() - started, "provider": p.name, "model": p.model,
             "system": system, "messages": [dict(m) for m in messages], "images": len(images or []),
             "reply": text, "error": str(error) if error is not None else None}
    for fn in list(CALL_LISTENERS):
        try:
            fn(entry)
        except Exception:   # a closed window's listener
            pass


def _merge_roles(messages):
    out: list[dict] = []
    for m in messages:
        role = "assistant" if m["role"] == "assistant" else "user"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + m["content"]
        else:
            out.append({"role": role, "content": m["content"]})
    if out and out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "(start)"})
    return out


def _chat_openai(p, key, messages, system, images, timeout, max_tokens=4096):
    msgs = [{"role": "system", "content": system}] if system else []
    for i, m in enumerate(messages):
        if images and i == len(messages) - 1 and m["role"] == "user":
            parts = [{"type": "text", "text": m["content"]}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in images]
            msgs.append({"role": "user", "content": parts})
        else:
            msgs.append(m)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if p.id == "openrouter":
        headers.update({"X-Title": "Pelagic"})
    url = p.base_url.rstrip("/") + "/chat/completions"
    body = {"model": p.model, "messages": msgs}
    native = urlparse(p.base_url).hostname == "api.openai.com"
    body["max_completion_tokens" if native else "max_tokens"] = max_tokens
    data = _http(url, headers, body, timeout)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError(f"Unexpected response: {str(data)[:300]}") from None
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    u = data.get("usage") or {}
    usage = {"inp": int(u["prompt_tokens"]), "out": int(u.get("completion_tokens") or 0),
             "cached_in": int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
             "reported_cost": u.get("cost")} if u.get("prompt_tokens") is not None else None
    return _strip_think(content or ""), usage


def _chat_anthropic(p, key, messages, system, images, timeout, max_tokens=4096):
    msgs = []
    for i, m in enumerate(messages):
        if images and i == len(messages) - 1 and m["role"] == "user":
            parts = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}}
                     for b in images]
            parts.append({"type": "text", "text": m["content"]})
            msgs.append({"role": "user", "content": parts})
        else:
            msgs.append(m)
    body = {"model": p.model, "max_tokens": max_tokens, "messages": msgs}
    if system:
        body["system"] = system
    if p.token_saver and urlparse(p.base_url).hostname == "api.anthropic.com":
        # Keep the stable system/page prefix reusable even when the newest observation changes.
        if system:
            body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if len(messages) > 1:
            body["cache_control"] = {"type": "ephemeral"}
    if p.model.startswith("claude-fable"):
        # thinking is always on for Fable models and counts toward max_tokens; leave room for the answer too
        body["max_tokens"] = max(max_tokens, 16000)
    base = p.base_url.rstrip("/")
    url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    use_fallback = p.model in FALLBACK_MODELS and urlparse(p.base_url).hostname == "api.anthropic.com"

    def ask(body):
        nonlocal use_fallback
        if use_fallback:
            # if this model's safety filter declines, Anthropic answers with a suitable other model instead
            try:
                return _http(url, {**headers, "anthropic-beta": "server-side-fallback-2026-07-01"},
                             {**body, "fallbacks": "default"}, timeout)
            except ProviderError as e:
                if "fallback" not in str(e).lower():
                    raise
                use_fallback = False   # not available for this account: ask without it
        return _http(url, headers, body, timeout)

    def text_of(data):
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError):
            raise ProviderError(f"Unexpected response: {str(data)[:300]}") from None

    data = ask(body)
    text = text_of(data)
    stop = data.get("stop_reason")
    if not text.strip() and stop == "end_turn" and data.get("content"):
        # Newer Claude models think first (hidden, so the thinking block is empty) and occasionally stop there
        # without writing anything. Hand the turn back once and ask for the answer.
        retry = {**body, "messages": msgs + [
            {"role": "assistant", "content": data["content"]},
            {"role": "user", "content": "Your last reply had no visible text. Please write your answer now."}]}
        first = data.get("usage") or {}
        data = ask(retry)
        text = text_of(data)
        u = data.setdefault("usage", {})
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            if first.get(k) is not None and u.get(k) is not None:
                u[k] = int(u[k]) + int(first[k])    # both requests are billed
        stop = data.get("stop_reason")
    if stop == "refusal":
        d = data.get("stop_details") or {}
        why = f" ({d['category']})" if d.get("category") else ""
        raise ProviderError(f"{p.model} declined to answer: its safety filter stopped this request{why}. "
                            + (f"{d['explanation']} " if d.get("explanation") else "")
                            + "Try rephrasing, or pick another model (Claude Opus 5.5 or Fable 5.1 automatically "
                              "hand a declined request to another model).")
    if not text.strip():
        if stop == "max_tokens":
            raise ProviderError(f"{p.model} used its whole output limit ({body['max_tokens']} tokens) thinking and "
                                "didn't get to write an answer. Ask again, or ask for something shorter.")
        raise ProviderError(f"{p.model} finished without writing an answer, even when asked again. Send your "
                            "message again, or pick another model.")
    answered = data.get("model") or p.model
    if answered != p.model and not answered.startswith(p.model):
        text += f"\n\n_(Answered by {answered}: {p.model} declined this request.)_"
    u = data.get("usage") or {}
    if u.get("input_tokens") is None:
        return text, None
    # cached input is billed/counted separately by Anthropic; include it so the total reflects the full prompt
    inp = int(u["input_tokens"]) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
    creation = u.get("cache_creation") or {}
    return text, {"inp": inp, "out": int(u.get("output_tokens") or 0),
                  "cached_in": int(u.get("cache_read_input_tokens") or 0),
                  "cache_write": int(u.get("cache_creation_input_tokens") or 0),
                  "cache_write_long": int(creation.get("ephemeral_1h_input_tokens") or 0)}


def _chat_gemini(p, key, messages, system, images, timeout, max_tokens=4096):
    contents = []
    for i, m in enumerate(messages):
        parts = [{"text": m["content"]}]
        if images and i == len(messages) - 1 and m["role"] == "user":
            parts = [{"inline_data": {"mime_type": "image/png", "data": b}} for b in images] + parts
        contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
    body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
    if p.token_saver and urlparse(p.base_url).hostname == "generativelanguage.googleapis.com" \
            and re.match(r"^(models/)?gemini-[3-9]", p.model):
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "low"}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    model = p.model[len("models/"):] if p.model.startswith("models/") else p.model
    url = f"{p.base_url.rstrip('/')}/models/{model}:generateContent"
    data = _http(url, {"x-goog-api-key": key}, body, timeout)
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
        raise ProviderError(f"Gemini returned no answer ({reason}).")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(x.get("text", "") for x in parts if not x.get("thought"))
    if not text and cands[0].get("finishReason") not in (None, "STOP"):
        raise ProviderError(f"Gemini stopped: {cands[0].get('finishReason')}")
    u = data.get("usageMetadata") or {}
    if u.get("promptTokenCount") is None:
        return text, None
    out = int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)   # thinking is billed
    return text, {"inp": int(u["promptTokenCount"]), "out": out,
                  "cached_in": int(u.get("cachedContentTokenCount") or 0)}


def _strip_think(text: str) -> str:
    """Reasoning models sometimes inline <think>…</think>; hide it from answers and JSON parsing."""
    while "<think>" in text and "</think>" in text:
        a, b = text.index("<think>"), text.index("</think>") + len("</think>")
        if b <= a:
            break
        text = text[:a] + text[b:]
    return text.strip()


MODEL_GONE = re.compile(r"no longer available|not found|does not exist|decommission|deprecat|unknown model|"
                        r"invalid model|not supported|HTTP 404", re.I)
_NOT_CHAT = re.compile(r"embed|tts|image|imagen|veo|live|audio|vision-only|aqa|whisper|moderation|guard|rerank|"
                       r"transcribe|realtime|lite|8b|preview|exp|latest", re.I)


def pick_model(p: Provider, names: list[str]) -> str:
    """Best current chat model from a provider's own list (used when the saved model was retired)."""
    def version(n):
        return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", n)) or (0.0,)
    pool = [n for n in names if not _NOT_CHAT.search(n)] or list(names)
    if not pool:
        return ""
    prefer = {"gemini": r"flash", "anthropic": r"sonnet", "openai": r"mini"}.get(p.kind if p.kind != "openai" else p.id, r"mini|flash|small|haiku")
    cands = [n for n in pool if re.search(prefer, n, re.I)] or pool
    return sorted(cands, key=version, reverse=True)[0]


# ---------------------------------------------------------------- model listing
def list_models(p: Provider, key: str, timeout: float = 30.0) -> list[str]:
    if p.needs_key and not key:
        raise ProviderError("Add an API key first.")
    base = p.base_url.rstrip("/")
    if p.kind == "anthropic":
        url = base + ("/models" if base.endswith("/v1") else "/v1/models") + "?limit=1000"
        data = _http(url, {"x-api-key": key, "anthropic-version": "2023-06-01"}, None, timeout, retries=1)
        return sorted(m["id"] for m in data.get("data", []))
    if p.kind == "gemini":
        out, token = [], ""
        for _ in range(5):
            url = f"{base}/models?pageSize=1000" + (f"&pageToken={token}" if token else "")
            data = _http(url, {"x-goog-api-key": key}, None, timeout, retries=1)
            for m in data.get("models", []):
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    out.append(m["name"].removeprefix("models/"))
            token = data.get("nextPageToken", "")
            if not token:
                break
        return sorted(out)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = _http(base + "/models", headers, None, timeout, retries=1)
    items = data.get("data", data if isinstance(data, list) else [])
    ids = [m["id"] if isinstance(m, dict) else str(m) for m in items]
    return sorted(i for i in ids if i)
