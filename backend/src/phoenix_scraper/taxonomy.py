"""P&L domain taxonomy: keyword maps and level inference for skill gap proposals."""

import re

# Phrases (containing spaces) are matched as substrings; single words match on
# word boundaries so short codes like "fx" cannot hit inside unrelated words.
ASSET_CLASS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fx": (
        "fx",
        "foreign exchange",
        "currency",
        "ccy",
        "eurusd",
        "gbpusd",
        "usdjpy",
        "spot",
        "ndf",
    ),
    "rates": (
        "rates",
        "interest rate",
        "swap",
        "swaption",
        "curve",
        "yield",
        "sofr",
        "libor",
        "basis",
    ),
    "equities": (
        "equities",
        "equity",
        "stock",
        "shares",
        "dividend",
        "index",
        "etf",
    ),
    "credit": (
        "credit",
        "bond",
        "cds",
        "spread",
        "issuer",
        "high yield",
        "investment grade",
    ),
    "commodities": (
        "commodities",
        "commodity",
        "oil",
        "gas",
        "gold",
        "metals",
        "energy",
        "crude",
        "power",
    ),
}

CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fobo_recon": (
        "fobo",
        "recon",
        "reconciliation",
        "front office",
        "back office",
        "unmatched",
        "mismatch",
    ),
    "plex": (
        "plex",
        "attribution",
        "risk factor",
        "carry",
        "greeks",
        "explain pnl",
    ),
    "flash_vs_formal": (
        "flash",
        "formal",
        "variance",
    ),
    "adjustments": (
        "adjustment",
        "adjust",
        "correction",
        "amend",
        "rebook",
        "write off",
    ),
    "commentary_signoff": (
        "commentary",
        "signoff",
        "sign-off",
        "sign off",
        "narrative",
        "attestation",
    ),
    "break_investigation": (
        "investigate",
        "investigation",
        "root cause",
        "why",
        "break",
        "deep dive",
    ),
    "data_retrieval": (
        "show me",
        "fetch",
        "retrieve",
        "pull",
        "list",
        "lookup",
        "query",
        "download",
        "export",
        "get me",
    ),
}


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.casefold()
    hits = 0
    for kw in keywords:
        if " " in kw or "-" in kw:
            if kw in lowered:
                hits += 1
        elif re.search(rf"\b{re.escape(kw)}\b", lowered):
            hits += 1
    return hits


def _best_label(text: str, keyword_map: dict[str, tuple[str, ...]]) -> str | None:
    if not text:
        return None
    scores = {label: _keyword_hits(text, kws) for label, kws in keyword_map.items()}
    best = max(scores, key=lambda label: scores[label])
    return best if scores[best] > 0 else None


def infer_asset_class(text: str) -> str | None:
    """Return the best-matching asset class label, or None if nothing hits."""
    return _best_label(text, ASSET_CLASS_KEYWORDS)


def infer_capability(text: str) -> str | None:
    """Return the best-matching capability label, or None if nothing hits."""
    return _best_label(text, CAPABILITY_KEYWORDS)


def suggest_level(text: str) -> tuple[str, str | None, str | None]:
    """Suggest (level, asset_class, capability) for a proposed new skill.

    Asset-class evidence pins the skill to that desk; capability-only evidence
    makes it a cross-desk workflow skill; otherwise it is global.
    """
    asset_class = infer_asset_class(text)
    capability = infer_capability(text)
    if asset_class is not None:
        return ("asset_class", asset_class, capability)
    if capability is not None:
        return ("capability", None, capability)
    return ("global", None, None)
