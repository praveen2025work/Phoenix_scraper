"""Prompt normalization: mask volatile tokens so near-identical prompts share a signature."""

import re

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
)
_ORDINAL = r"(?:st|nd|rd|th)?"

# Order matters: dates must be masked before bare numbers eat their digits.
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),  # 2026-07-29
    re.compile(r"\b\d{4}/\d{1,2}/\d{1,2}\b"),  # 2026/07/29
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),  # 29/07/2026
    re.compile(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}{_ORDINAL}(?:,?\s+\d{{4}})?\b"),  # july 29[, 2026]
    re.compile(rf"\b\d{{1,2}}{_ORDINAL}\s+(?:{_MONTHS})(?:,?\s+\d{{4}})?\b"),  # 29 july [2026]
)

# ADJ-1234, TRD_998877 and similar reference codes.
_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]{1,11}[-_]\d{2,}\b")

# Book/portfolio codes like EQ_DELTA1_NY or BUNDS_FFT — matched on the RAW text
# before casefolding (uppercase is the signal). Every underscore segment must
# contain a letter so numeric reference ids (TRD_998877) still become <id>.
_BOOK_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]*[A-Z][A-Z0-9]*)+\b")

# Desk mentions ("the rates desk") collapse so per-desk phrasings share a signature;
# the cluster still reports per-desk coverage via span asset_class metadata.
_DESK_PATTERN = re.compile(r"\b(?:fx|rates?|equit(?:y|ies)|credit|commodit(?:y|ies))\s+desk\b")

_CCY_CODES = (
    "usd", "eur", "gbp", "jpy", "chf", "aud", "cad", "nzd", "sek", "nok", "dkk",
    "cny", "cnh", "hkd", "sgd", "inr", "krw", "mxn", "brl", "zar", "pln", "thb",
    "huf", "czk", "ils", "twd", "myr", "idr", "rub", "try",
)
# Codes that are also common English words; masked only inside pairs, never standalone.
_AMBIGUOUS_STANDALONE = frozenset({"try"})

_CCY_ALT = "|".join(_CCY_CODES)
_CCY_PAIR_PATTERN = re.compile(
    rf"\b(?:{_CCY_ALT})\s*[/-]\s*(?:{_CCY_ALT})\b|\b(?:{_CCY_ALT})(?:{_CCY_ALT})\b"
)
_CCY_SINGLE_PATTERN = re.compile(
    r"\b(?:" + "|".join(c for c in _CCY_CODES if c not in _AMBIGUOUS_STANDALONE) + r")\b"
)

# Amounts: optional currency symbol, digits with separators, optional magnitude/ordinal suffix.
_NUMBER_PATTERN = re.compile(r"[$€£¥]?\b\d+(?:[.,]\d+)*\s?(?:k|mm|m|bn|b|st|nd|rd|th)?\b")
_LEADING_SYMBOL_NUMBER = re.compile(r"[$€£¥]\s?\d+(?:[.,]\d+)*\s?(?:k|mm|m|bn|b)?\b")

_WHITESPACE = re.compile(r"\s+")
_SIGNATURE_PUNCT = re.compile(r"[^\w<>\s]|_")


def normalize_prompt(text: str) -> str:
    """Casefold, collapse whitespace, and mask volatile tokens with placeholders."""
    result = _BOOK_PATTERN.sub("<book>", text)
    result = result.casefold()
    result = _DESK_PATTERN.sub("<desk> desk", result)
    for pattern in _DATE_PATTERNS:
        result = pattern.sub("<date>", result)
    result = _ID_PATTERN.sub("<id>", result)
    result = _CCY_PAIR_PATTERN.sub("<ccy>", result)
    result = _CCY_SINGLE_PATTERN.sub("<ccy>", result)
    result = _LEADING_SYMBOL_NUMBER.sub("<num>", result)
    result = _NUMBER_PATTERN.sub("<num>", result)
    return _WHITESPACE.sub(" ", result).strip()


def prompt_signature(text: str) -> str:
    """Cluster grouping key: normalized prompt with punctuation removed. '' for empty input."""
    normalized = normalize_prompt(text)
    if not normalized:
        return ""
    stripped = _SIGNATURE_PUNCT.sub(" ", normalized)
    return _WHITESPACE.sub(" ", stripped).strip()
