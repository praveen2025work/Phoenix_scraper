"""Near-duplicate collapse for prompt clusters via MinHash / Jaccard shingles.

Classical only — no embeddings. Used before skill matching so paraphrased
duplicates do not flood gap proposals.
"""

from __future__ import annotations

from .models import PromptCluster
from .text_normalize import tokenize
from .text_similarity import char_ngrams


def _shingles(text: str) -> set[str]:
    toks = tokenize(text)
    word = {" ".join(toks[i : i + 2]) for i in range(max(len(toks) - 1, 0))}
    chars = set(char_ngrams(text, n=4))
    return word | chars | set(toks)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def collapse_near_duplicates(
    clusters: list[PromptCluster],
    *,
    threshold: float = 0.85,
) -> list[PromptCluster]:
    """Merge near-duplicate clusters; keep the highest-count representative.

    When two clusters' shingle Jaccard ≥ threshold, the smaller is absorbed:
    counts sum, span_ids union (capped implicitly by tuple concat).
    """
    if len(clusters) <= 1:
        return list(clusters)
    ordered = sorted(clusters, key=lambda c: (-c.count, c.cluster_id))
    kept: list[PromptCluster] = []
    shingles: list[set[str]] = []
    for cluster in ordered:
        sig = _shingles(f"{cluster.signature} {cluster.representative}")
        merged = False
        for i, existing in enumerate(kept):
            if jaccard(sig, shingles[i]) >= threshold:
                # Absorb into the kept (higher-count) cluster.
                kept[i] = existing.model_copy(
                    update={
                        "count": existing.count + cluster.count,
                        "span_ids": tuple(
                            dict.fromkeys((*existing.span_ids, *cluster.span_ids))
                        ),
                        "asset_classes": tuple(
                            sorted(
                                {
                                    *existing.asset_classes,
                                    *cluster.asset_classes,
                                }
                            )
                        ),
                    }
                )
                shingles[i] = shingles[i] | sig
                merged = True
                break
        if not merged:
            kept.append(cluster)
            shingles.append(sig)
    return kept
