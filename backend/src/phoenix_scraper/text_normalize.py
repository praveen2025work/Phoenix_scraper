"""Normalize short desk prompts for classical matching: stem + synonym expand.

No LLM. Synonym map ships in ``config/fobo_synonyms.yaml`` (FOBO domain).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)
_STOP = frozenset({
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "was", "were", "be", "with", "at", "by", "from", "as", "it", "this", "that",
    "please", "can", "you", "your", "me", "my", "we", "our", "how", "what",
    "when", "which", "why", "do", "does", "did",
})

# Tiny Porter-like suffix stripper for English desk English (no nltk download).
_SUFFIXES = (
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("isation", "ize"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
    ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"),
    ("ization", "ize"), ("ation", "ate"), ("ator", "ate"),
    ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"),
    ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
    ("icate", "ic"), ("ative", ""), ("alize", "al"),
    ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", ""),
    ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"),
    ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
    ("ement", ""), ("ance", ""), ("ence", ""), ("able", ""), ("ible", ""),
    ("ant", ""), ("ement", ""), ("ment", ""), ("ent", ""), ("ism", ""),
    ("ate", ""), ("iti", ""), ("ous", ""), ("ive", ""), ("ize", ""),
    ("ingly", ""), ("edly", ""), ("ally", ""),
    ("ing", ""), ("edly", ""), ("edly", ""), ("edly", ""),
    ("ies", "y"), ("ied", "y"), ("ses", "s"), ("sses", "ss"),
    ("edly", ""), ("ing", ""), ("ly", ""), ("ed", ""), ("s", ""),
)


def stem(token: str) -> str:
    """Aggressive light stemmer for short finance prompts."""
    w = token.casefold()
    if len(w) <= 3:
        return w
    for suffix, repl in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) + len(repl) >= 3:
            return w[: -len(suffix)] + repl
    return w


@lru_cache(maxsize=1)
def _synonym_map() -> dict[str, str]:
    """Map each alias -> canonical term. Missing file => empty map."""
    path = Path(__file__).resolve().parents[2] / "config" / "fobo_synonyms.yaml"
    # Also try repo-root config when installed editable from backend/
    candidates = [
        path,
        Path.cwd() / "config" / "fobo_synonyms.yaml",
        Path.cwd() / "backend" / "config" / "fobo_synonyms.yaml",
    ]
    data: dict = {}
    for candidate in candidates:
        if candidate.is_file():
            loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = loaded
            break
    out: dict[str, str] = {}
    for canonical, aliases in data.items():
        canon = str(canonical).casefold().strip()
        if not canon:
            continue
        out[canon] = canon
        if isinstance(aliases, list):
            for alias in aliases:
                a = str(alias).casefold().strip()
                if a:
                    out[a] = canon
    return out


def tokenize(text: str, *, expand_synonyms: bool = True) -> list[str]:
    """Tokenize → stem → optional synonym canonicalize."""
    syn = _synonym_map() if expand_synonyms else {}
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        t = raw.casefold()
        if t in _STOP or t.isdigit():
            continue
        t = syn.get(t, t)
        t = stem(t)
        t = syn.get(t, t)
        if t and t not in _STOP:
            out.append(t)
    return out


def normalize_text(text: str) -> str:
    """Space-joined stemmed synonym-expanded tokens (for BM25 / TF-IDF docs)."""
    return " ".join(tokenize(text))
