"""Optional local semantic similarity (MiniLM) — no generative LLM, no cloud API.

Enabled when match_mode=semantic and sentence-transformers is installed.
Falls back gracefully when the extra is missing or the model cannot load.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_model: Any | None = None
_load_error: str | None = None


def semantic_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _get_model(model_name: str):
    global _model, _load_error
    with _lock:
        if _model is not None:
            return _model
        if _load_error is not None:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(model_name)
            return _model
        except Exception as exc:  # noqa: BLE001
            _load_error = f"{type(exc).__name__}: {exc}"
            logger.warning("semantic model unavailable: %s", _load_error)
            return None


def semantic_similarity(
    query: str,
    references: list[str],
    *,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> float:
    """Best cosine similarity of query vs references using a local MiniLM model.

    Returns 0.0 when semantic extras are unavailable.
    """
    refs = [r for r in references if r and str(r).strip()]
    if not query.strip() or not refs:
        return 0.0
    model = _get_model(model_name)
    if model is None:
        return 0.0
    try:
        import numpy as np

        vectors = model.encode([query, *refs], normalize_embeddings=True)
        qv, rvs = vectors[0], vectors[1:]
        sims = rvs @ qv
        return float(max(0.0, min(1.0, float(np.max(sims)))))
    except Exception as exc:  # noqa: BLE001
        logger.warning("semantic encode failed: %s", exc)
        return 0.0


def last_load_error() -> str | None:
    return _load_error
