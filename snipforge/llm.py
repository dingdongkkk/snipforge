"""Provider-agnostic chat client over the OpenAI-compatible HTTP API (stdlib only)."""
from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request

from .config import PROVIDERS


class LLMError(RuntimeError):
    pass


def _retry_after(err: urllib.error.HTTPError, body: str) -> float | None:
    """Seconds to wait from a Retry-After header or a 'try again in 1m2.5s' style message."""
    try:
        return float(err.headers.get("retry-after")) + 0.5
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", body)
    if not m:
        return None
    secs = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
    return int(m.group(1) or 0) * 60 + secs + 0.5


class LLMClient:
    def __init__(self, provider: str, model: str | None = None, timeout: float = 180):
        if provider not in PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")
        cfg = PROVIDERS[provider]
        self.provider = provider
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = model or cfg["default_model"]
        # Comma-separated keys are allowed; on a rate limit (429) the client rotates to the next one.
        self.api_keys = [k.strip() for k in (os.getenv(cfg["key_env"]) or "").split(",") if k.strip()] \
            if cfg["key_env"] else []
        if cfg["key_env"] and not self.api_keys:
            raise LLMError(f"Set {cfg['key_env']} in .env to use {cfg['label']}")
        self._key_idx = 0
        self.timeout = timeout
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode()
        last_err = None
        for attempt in range(8):
            # A real User-Agent: some providers' CDNs (e.g. Groq's) reject the default Python-urllib one.
            headers = {"Content-Type": "application/json", "User-Agent": "SnipForge/2.0"}
            if self.api_keys:
                headers["Authorization"] = f"Bearer {self.api_keys[self._key_idx]}"
            if self.provider == "openrouter":
                headers["X-Title"] = "SnipForge"
            req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:500]
                last_err = f"HTTP {e.code}: {body}"
                if e.code == 429:
                    # Rotate keys first; once every key has been tried, wait as long as the provider asks.
                    if len(self.api_keys) > 1:
                        self._key_idx = (self._key_idx + 1) % len(self.api_keys)
                        if attempt % len(self.api_keys) != len(self.api_keys) - 1:
                            continue
                    time.sleep(min(_retry_after(e, body) or 2 ** min(attempt, 4), 60))
                    continue
                if e.code in (500, 502, 503, 504):
                    time.sleep(2 ** min(attempt, 4))
                    continue
                raise LLMError(last_err) from e
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as e:
                last_err = str(e)
                time.sleep(1 + attempt)
        raise LLMError(f"{self.provider} unreachable: {last_err}")

    def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 2048) -> str:
        data = self._post(
            "/chat/completions",
            {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
        )
        self.usage["calls"] += 1
        usage = data.get("usage") or {}
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0) or 0
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected response: {str(data)[:300]}") from e


def embed(texts: list[str], model: str) -> list[list[float]]:
    """Embeddings via Ollama's OpenAI-compatible endpoint (e.g. gte-large)."""
    base = PROVIDERS["ollama"]["base_url"].rstrip("/")
    req = urllib.request.Request(
        base + "/embeddings",
        data=json.dumps({"model": model, "input": texts}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "SnipForge/2.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
