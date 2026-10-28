"""Hybrid retrieval over the requirement->code knowledge base.

BM25 (pure Python) always runs; if SNIPFORGE_EMBED_MODEL is set and Ollama is
reachable, dense cosine similarity (e.g. gte-large) is blended in.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .config import DATA_DIR, EMBED_MODEL, KB_FILES

_STOP = set(
    "a an the of to and or in on for with that this is be it as by from at into which "
    "write create implement function python returns return given should take takes "
    "using use make build code snippet".split()
)


def normalize_text(text: str) -> str:
    """Preprocessing: lowercase, collapse whitespace, strip markdown noise."""
    text = re.sub(r"[`*_#>]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", normalize_text(text))
    out = []
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        for suffix in ("ing", "ies", "es", "ed", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        out.append(w)
    return out


def load_kb(files: list[Path] = KB_FILES) -> list[dict]:
    items = []
    for f in files:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


class Retriever:
    def __init__(self, items: list[dict] | None = None, k1: float = 1.5, b: float = 0.75):
        self.items = items if items is not None else load_kb()
        self.k1, self.b = k1, b
        self.dense_enabled = False
        self._build()

    def _doc_text(self, it: dict) -> str:
        return " ".join([it["requirement"], " ".join(it.get("tags", [])), it.get("code", "")[:200]])

    def _build(self) -> None:
        self.docs = [tokenize(self._doc_text(it)) for it in self.items]
        self.avgdl = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tfs = [Counter(d) for d in self.docs]
        self.vectors = None
        if EMBED_MODEL and self.items:
            try:
                self.vectors = self._load_or_embed()
                self.dense_enabled = True
            except Exception:
                self.vectors = None

    def _load_or_embed(self) -> list[list[float]]:
        from .llm import embed

        texts = [it["requirement"] for it in self.items]
        digest = hashlib.sha1((EMBED_MODEL + "".join(texts)).encode()).hexdigest()[:12]
        cache = DATA_DIR / f".emb_{digest}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        vecs = embed(texts, EMBED_MODEL)
        cache.write_text(json.dumps(vecs))
        return vecs

    def reload(self) -> None:
        self.items = load_kb()
        self._build()

    def _bm25(self, q: list[str]) -> list[float]:
        scores = []
        for d, tf in zip(self.docs, self.tfs):
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            scores.append(s)
        return scores

    def search(self, query: str, k: int = 3) -> list[dict]:
        if not self.items:
            return []
        lex = self._bm25(tokenize(query))
        top = max(lex) or 1.0
        scores = [s / top for s in lex]
        if self.dense_enabled and self.vectors:
            try:
                from .llm import embed

                qv = embed([query], EMBED_MODEL)[0]
                dense = [_cos(qv, v) for v in self.vectors]
                scores = [0.5 * s + 0.5 * d for s, d in zip(scores, dense)]
            except Exception:
                pass
        ranked = sorted(range(len(self.items)), key=lambda i: scores[i], reverse=True)[:k]
        return [dict(self.items[i], score=round(scores[i], 3)) for i in ranked if scores[i] > 0]

    def add(self, item: dict, path: Path = KB_FILES[1]) -> None:
        with path.open("a") as fh:
            fh.write(json.dumps(item) + "\n")
        self.reload()


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
