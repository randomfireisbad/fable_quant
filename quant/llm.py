"""Pluggable LLM provider layer.

Configure via environment variables:
  FQ_LLM_PROVIDER   = anthropic | ollama   (default: anthropic if key set, else ollama)
  ANTHROPIC_API_KEY = sk-ant-...
  FQ_ANTHROPIC_MODEL = claude-sonnet-4-6 (default)
  FQ_OLLAMA_URL     = http://localhost:11434 (default)
  FQ_OLLAMA_MODEL   = qwen2.5:14b (default; any tool-capable model works)

Unified surface:
  provider().chat(system, messages)                  -> str
  provider().research(prompt)                        -> str   (web search if supported)
  provider().tool_loop(system, goal, tools, execute) -> (final_text, transcript)
"""
from __future__ import annotations

import json
import os
import threading

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# UI-supplied config (overrides env vars); persisted locally.
_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CFG_FILE = os.path.join(_DATA, "llm_config.json")
_cfg_lock = threading.Lock()
_CFG_KEYS = ("provider", "anthropicKey", "anthropicModel", "ollamaUrl", "ollamaModel")


def _config() -> dict:
    try:
        with open(_CFG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def set_config(updates: dict) -> dict:
    """Merge UI config; empty-string values clear a key. Returns new status."""
    with _cfg_lock:
        cfg = _config()
        for k in _CFG_KEYS:
            if k in updates and updates[k] is not None:
                v = str(updates[k]).strip()
                if v:
                    cfg[k] = v
                else:
                    cfg.pop(k, None)
        os.makedirs(_DATA, exist_ok=True)
        with open(_CFG_FILE, "w") as f:
            json.dump(cfg, f, indent=1)
    return status()


def get_config_masked() -> dict:
    cfg = _config()
    out = {k: cfg.get(k, "") for k in _CFG_KEYS}
    if out["anthropicKey"]:
        out["anthropicKey"] = out["anthropicKey"][:10] + "…" + out["anthropicKey"][-4:]
    out["envKeyPresent"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return out


def _anthropic_key() -> str:
    return _config().get("anthropicKey") or os.environ.get("ANTHROPIC_API_KEY", "")


def _anthropic_model() -> str:
    return (_config().get("anthropicModel")
            or os.environ.get("FQ_ANTHROPIC_MODEL", "claude-sonnet-4-6"))


def _ollama_model() -> str:
    return _config().get("ollamaModel") or os.environ.get("FQ_OLLAMA_MODEL", "qwen2.5:14b")


def status() -> dict:
    p = _provider_name()
    out = {"provider": p, "webSearch": p == "anthropic",
           "configSource": "ui" if _config() else "env"}
    if p == "anthropic":
        out["model"] = _anthropic_model()
        out["ready"] = bool(_anthropic_key())
        if not out["ready"]:
            out["hint"] = "Add an Anthropic API key via the LLM settings (top bar)."
    else:
        out["model"] = _ollama_model()
        try:
            r = requests.get(_ollama_url() + "/api/tags", timeout=2)
            out["ready"] = r.ok
        except Exception:
            out["ready"] = False
            out["hint"] = "Start Ollama (ollama serve) or set its URL in LLM settings."
    return out


def _provider_name() -> str:
    p = (_config().get("provider") or os.environ.get("FQ_LLM_PROVIDER", "")).lower()
    if p in ("anthropic", "ollama"):
        return p
    return "anthropic" if _anthropic_key() else "ollama"


def _ollama_url() -> str:
    return (_config().get("ollamaUrl")
            or os.environ.get("FQ_OLLAMA_URL", "http://localhost:11434")).rstrip("/")


def provider():
    return Anthropic() if _provider_name() == "anthropic" else Ollama()


# ---------------------------------------------------------------- Anthropic
class Anthropic:
    name = "anthropic"
    supports_web = True

    def __init__(self):
        self.key = _anthropic_key()
        self.model = _anthropic_model()

    def _post(self, body: dict) -> dict:
        r = requests.post(ANTHROPIC_URL, timeout=240, json=body, headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
        if not r.ok:
            raise RuntimeError(f"Anthropic API error {r.status_code}: {r.text[:300]}")
        return r.json()

    @staticmethod
    def _text(resp: dict) -> str:
        return "\n".join(b.get("text", "") for b in resp.get("content", [])
                         if b.get("type") == "text").strip()

    def chat(self, system: str, messages: list[dict], max_tokens: int = 2048) -> str:
        resp = self._post({"model": self.model, "max_tokens": max_tokens,
                           "system": system, "messages": messages})
        return self._text(resp)

    def research(self, prompt: str, max_tokens: int = 4096) -> str:
        """Single call with server-side web search enabled."""
        resp = self._post({
            "model": self.model, "max_tokens": max_tokens,
            "system": "You are a rigorous equity research analyst. Search the web "
                      "for current information and cite sources inline as [title](url).",
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "web_search_20250305", "name": "web_search",
                       "max_uses": 6}],
        })
        return self._text(resp)

    def tool_loop(self, system, goal, tools, execute, max_steps=10):
        """tools: [{name, description, input_schema}]; execute(name, args)->str."""
        msgs = [{"role": "user", "content": goal}]
        transcript = []
        for _ in range(max_steps):
            resp = self._post({"model": self.model, "max_tokens": 3000,
                               "system": system, "messages": msgs,
                               "tools": tools})
            text = self._text(resp)
            calls = [b for b in resp.get("content", []) if b.get("type") == "tool_use"]
            if text:
                transcript.append({"type": "thought", "text": text})
            if not calls:
                return text, transcript
            msgs.append({"role": "assistant", "content": resp["content"]})
            results = []
            for c in calls:
                out = execute(c["name"], c.get("input") or {})
                transcript.append({"type": "tool", "name": c["name"],
                                   "input": c.get("input"), "output": out[:4000]})
                results.append({"type": "tool_result", "tool_use_id": c["id"],
                                "content": out[:8000]})
            msgs.append({"role": "user", "content": results})
        return "(stopped: step limit reached)", transcript


# ------------------------------------------------------------------ Ollama
class Ollama:
    name = "ollama"
    supports_web = False

    def __init__(self):
        self.url = _ollama_url()
        self.model = _ollama_model()

    def _post(self, messages, tools=None) -> dict:
        body = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        r = requests.post(self.url + "/api/chat", json=body, timeout=600)
        if not r.ok:
            raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
        return r.json()

    def chat(self, system: str, messages: list[dict], max_tokens: int = 2048) -> str:
        resp = self._post([{"role": "system", "content": system}] + messages)
        return (resp.get("message") or {}).get("content", "").strip()

    def research(self, prompt: str, max_tokens: int = 4096) -> str:
        note = ("NOTE: you have no live web access. Reason from the data provided "
                "and clearly flag anything that may be out of date.\n\n")
        return self.chat("You are a rigorous equity research analyst.",
                         [{"role": "user", "content": note + prompt}])

    def tool_loop(self, system, goal, tools, execute, max_steps=10):
        # convert anthropic-style schemas to openai/ollama function style
        fns = [{"name": t["name"], "description": t["description"],
                "parameters": t["input_schema"]} for t in tools]
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": goal}]
        transcript = []
        for _ in range(max_steps):
            resp = self._post(msgs, tools=fns)
            m = resp.get("message") or {}
            text = (m.get("content") or "").strip()
            calls = m.get("tool_calls") or []
            if text:
                transcript.append({"type": "thought", "text": text})
            if not calls:
                return text, transcript
            msgs.append(m)
            for c in calls:
                fn = c.get("function") or {}
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                out = execute(fn.get("name", ""), args)
                transcript.append({"type": "tool", "name": fn.get("name"),
                                   "input": args, "output": out[:4000]})
                msgs.append({"role": "tool", "content": out[:8000]})
        return "(stopped: step limit reached)", transcript
