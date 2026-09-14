"""Classical text similarity: TF-IDF cosine (no LLM, no embeddings service).

Used to strengthen skill↔cluster matching alongside rapidfuzz token ratios.
Pure Python / stdlib — no scikit-learn dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
_STOP = frozenset({
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "was", "were", "be", "with", "at", "by", "from", "as", "it", "this", "that",
    "please", "can", "you", "your", "me", "my", "we", "our", "how", "what",
    "when", "which", "why", "do", "does", "did",
})


def tokenize(text: str) -> list[str]:
    return [
        t.casefold()
        for t in _TOKEN_RE.findall(text or "")
        if t.casefold() not in _STOP and not t.isdigit()
    ]


def _tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    n = float(len(tokens))
    return {t: c / n for t, c in counts.items()}


def tfidf_vectors(documents: list[str]) -> list[dict[str, float]]:
    """TF-IDF sparse vectors for each document (keys = terms)."""
    tokenized = [tokenize(doc) for doc in documents]
    dfs: Counter[str] = Counter()
    for toks in tokenized:
        dfs.update(set(toks))
    n_docs = max(len(documents), 1)
    idf = {
        term: math.log((1.0 + n_docs) / (1.0 + df)) + 1.0
        for term, df in dfs.items()
    }
    vectors: list[dict[str, float]] = []
    for toks in tokenized:
        tf = _tf(toks)
        vectors.append({t: tf[t] * idf[t] for t in tf if t in idf})
    return vectors


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def tfidf_similarity(query: str, references: list[str]) -> float:
    """Best TF-IDF cosine of query against any reference string."""
    refs = [r for r in references if r and str(r).strip()]
    if not query.strip() or not refs:
        return 0.0
    vectors = tfidf_vectors([query, *refs])
    qv, *rvs = vectors
    return max((cosine(qv, rv) for rv in rvs), default=0.0)
