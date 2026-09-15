"""Classical text similarity: TF-IDF, char n-grams, BM25 (no LLM).

Used by skill↔cluster matching with rapidfuzz. Pure Python / stdlib + optional
scikit-learn for denser n-gram TF-IDF when installed.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .text_normalize import normalize_text  # noqa: F401 — re-exported


def tokenize(text: str) -> list[str]:
    """Simple casefolded tokens without synonym expand (stable for tests/callers)."""
    return [
        t.casefold()
        for t in _TOKEN_RE.findall(text or "")
        if t.casefold() not in _STOP and not t.isdigit()
    ]

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
_STOP = frozenset({
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "was", "were", "be", "with", "at", "by", "from", "as", "it", "this", "that",
    "please", "can", "you", "your", "me", "my", "we", "our", "how", "what",
    "when", "which", "why", "do", "does", "did",
})


def _legacy_tokenize(text: str) -> list[str]:
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


def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Character n-grams over the compact casefolded string (no spaces)."""
    s = re.sub(r"\s+", "", (text or "").casefold())
    if len(s) < n:
        return [s] if s else []
    return [s[i : i + n] for i in range(len(s) - n + 1)]


def tfidf_vectors(documents: list[str], *, normalized: bool = True) -> list[dict[str, float]]:
    """TF-IDF sparse vectors for each document (keys = terms)."""
    tokenized = [
        tokenize(doc) if normalized else _legacy_tokenize(doc) for doc in documents
    ]
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


def char_tfidf_vectors(documents: list[str], n: int = 3) -> list[dict[str, float]]:
    """TF-IDF over character n-grams — robust to typos and short desk prompts."""
    tokenized = [char_ngrams(doc, n=n) for doc in documents]
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
    """Best word TF-IDF cosine of query against any reference string."""
    refs = [r for r in references if r and str(r).strip()]
    if not query.strip() or not refs:
        return 0.0
    vectors = tfidf_vectors([query, *refs])
    qv, *rvs = vectors
    return max((cosine(qv, rv) for rv in rvs), default=0.0)


def char_tfidf_similarity(query: str, references: list[str], n: int = 3) -> float:
    """Best character n-gram TF-IDF cosine of query against any reference."""
    refs = [r for r in references if r and str(r).strip()]
    if not query.strip() or not refs:
        return 0.0
    vectors = char_tfidf_vectors([query, *refs], n=n)
    qv, *rvs = vectors
    return max((cosine(qv, rv) for rv in rvs), default=0.0)


def bm25_scores(query: str, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 scores of query against each document (normalized tokens)."""
    if not query.strip() or not documents:
        return [0.0] * len(documents)
    q_toks = tokenize(query)
    docs = [tokenize(d) for d in documents]
    if not q_toks or not any(docs):
        return [0.0] * len(documents)
    n_docs = len(docs)
    avgdl = sum(len(d) for d in docs) / max(n_docs, 1)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    scores: list[float] = []
    for doc in docs:
        tf = Counter(doc)
        dl = len(doc) or 1
        score = 0.0
        for term in set(q_toks):
            f = tf.get(term, 0)
            if f == 0:
                continue
            n_q = df.get(term, 0)
            idf = math.log(1.0 + (n_docs - n_q + 0.5) / (n_q + 0.5))
            score += idf * (f * (k1 + 1.0)) / (f + k1 * (1.0 - b + b * dl / max(avgdl, 1e-9)))
        scores.append(score)
    return scores


def bm25_similarity(query: str, references: list[str]) -> float:
    """Best BM25 score vs references, scaled to ~[0,1] via 1 - 1/(1+score)."""
    refs = [r for r in references if r and str(r).strip()]
    if not query.strip() or not refs:
        return 0.0
    raw = max(bm25_scores(query, refs), default=0.0)
    return max(0.0, min(1.0, 1.0 - 1.0 / (1.0 + raw)))


def combined_lexical_similarity(query: str, references: list[str]) -> float:
    """Blend word TF-IDF, char TF-IDF, and BM25 for short-prompt robustness."""
    refs = [r for r in references if r and str(r).strip()]
    if not query.strip() or not refs:
        return 0.0
    return (
        0.40 * tfidf_similarity(query, refs)
        + 0.30 * char_tfidf_similarity(query, refs)
        + 0.30 * bm25_similarity(query, refs)
    )


__all__ = [
    "bm25_scores",
    "bm25_similarity",
    "char_ngrams",
    "char_tfidf_similarity",
    "combined_lexical_similarity",
    "cosine",
    "normalize_text",
    "tfidf_similarity",
    "tfidf_vectors",
    "tokenize",
]
