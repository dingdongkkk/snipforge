"""Configuration: provider registry and .env loading (no third-party deps)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
KB_FILES = [DATA_DIR / "kb.jsonl", DATA_DIR / "kb_user.jsonl"]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

# Every provider below speaks the OpenAI-compatible /chat/completions protocol,
# so one tiny HTTP client covers local SLMs and all hosted APIs.
PROVIDERS: dict[str, dict] = {
    "ollama": {
        "label": "Ollama (local SLM)",
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "key_env": None,
        "default_model": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:latest"),
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "default_model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": os.getenv("OPENROUTER_MODEL", "qwen/qwen-2.5-coder-32b-instruct"),
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    },
    "xai": {
        "label": "xAI Grok",
        "base_url": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY",
        "default_model": os.getenv("XAI_MODEL", "grok-3-mini"),
    },
}

DEFAULT_PROVIDER = os.getenv("SNIPFORGE_PROVIDER", "ollama")
# Optional independent test designer: a different provider/model writes the tests (and challenge cases)
# than the one that writes the code, reducing correlated misunderstandings. Empty = same model.
TEST_PROVIDER = os.getenv("SNIPFORGE_TEST_PROVIDER", "")
TEST_MODEL = os.getenv("SNIPFORGE_TEST_MODEL", "")
MAX_REPAIRS = int(os.getenv("SNIPFORGE_MAX_REPAIRS", "1"))
TEST_TIMEOUT_S = float(os.getenv("SNIPFORGE_TEST_TIMEOUT", "10"))
TOP_K_EXAMPLES = int(os.getenv("SNIPFORGE_TOP_K", "2"))
# Consensus check: a second, independent implementation; tests both implementations agree against are disputed.
CONSENSUS = os.getenv("SNIPFORGE_CONSENSUS", "1") != "0"
# Trust policy for tests written by the SAME model as the code. Strong models' own tests are reliable
# (they select candidates and drive repair). Small local models' own tests share their misunderstandings
# (measured: they picked wrong candidates and made repair break correct code), so in small-model mode
# they are evidence only: no repair, and code is chosen by agreement. Independent test designers are always trusted.
TRUST_OWN_TESTS = os.getenv("SNIPFORGE_TRUST_OWN_TESTS", "1") != "0"

# Optional dense retrieval through Ollama's embedding endpoint (gte-large etc.).
EMBED_MODEL = os.getenv("SNIPFORGE_EMBED_MODEL", "")  # e.g. "gte-large"


def provider_available(name: str) -> bool:
    p = PROVIDERS.get(name)
    if not p:
        return False
    return p["key_env"] is None or bool(os.getenv(p["key_env"]))


def public_providers() -> list[dict]:
    return [
        {
            "id": pid,
            "label": p["label"],
            "default_model": p["default_model"],
            "configured": provider_available(pid),
        }
        for pid, p in PROVIDERS.items()
    ]
