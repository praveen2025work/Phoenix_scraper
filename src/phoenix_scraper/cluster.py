"""Group spans into prompt clusters by normalized signature with fuzzy merging."""

import hashlib
from collections import Counter
from datetime import UTC, datetime

import pandas as pd
from rapidfuzz import fuzz

from .models import PromptCluster
from .normalize import prompt_signature


def build_clusters(spans_df: pd.DataFrame, fuzz_threshold: int = 90) -> list[PromptCluster]:
    """Cluster spans by prompt signature, merging near-identical signatures.

    Expects the columns produced by Store.spans_frame(): span_id, session_id,
    user_id, input_text, cost_usd, latency_ms, start_time, workflow_stage,
    asset_class. Returns clusters sorted by count descending.
    """
    if spans_df is None or spans_df.empty:
        return []

    work = spans_df.assign(
        _signature=spans_df["input_text"].fillna("").map(prompt_signature)
    )
    work = work[work["_signature"] != ""]
    if work.empty:
        return []

    groups: dict[str, pd.DataFrame] = {
        sig: frame for sig, frame in work.groupby("_signature", sort=True)
    }
    assignment = _merge_signatures(groups, fuzz_threshold)

    members_by_canonical: dict[str, list[pd.DataFrame]] = {}
    for sig in sorted(groups):
        members_by_canonical.setdefault(assignment[sig], []).append(groups[sig])

    clusters = [
        _build_cluster(canonical, pd.concat(frames, ignore_index=True))
        for canonical, frames in members_by_canonical.items()
    ]
    return sorted(clusters, key=lambda c: (-c.count, c.signature))


def _merge_signatures(
    groups: dict[str, pd.DataFrame], fuzz_threshold: int
) -> dict[str, str]:
    """Map each signature to a canonical one, merging fuzzy near-duplicates.

    Signatures are visited largest-group first so the canonical signature of a
    merged cluster is always the most frequent variant (ties broken lexically).
    """
    ordered = sorted(groups, key=lambda sig: (-len(groups[sig]), sig))
    canonicals: list[str] = []
    assignment: dict[str, str] = {}
    for sig in ordered:
        match = next(
            (
                canon
                for canon in canonicals
                if fuzz.token_set_ratio(sig, canon) >= fuzz_threshold
            ),
            None,
        )
        if match is None:
            canonicals.append(sig)
            assignment[sig] = sig
        else:
            assignment[sig] = match
    return assignment


def _build_cluster(signature: str, members: pd.DataFrame) -> PromptCluster:
    ordered = members.sort_values(["start_time", "span_id"], kind="stable")

    text_counts = Counter(ordered["input_text"])
    representative = min(text_counts, key=lambda t: (-text_counts[t], t))

    latencies = ordered["latency_ms"].dropna()
    start_times = ordered["start_time"].dropna()

    return PromptCluster(
        cluster_id=hashlib.sha1(signature.encode()).hexdigest()[:12],
        signature=signature,
        representative=representative,
        count=len(ordered),
        n_sessions=_n_distinct(ordered["session_id"]),
        n_users=_n_distinct(ordered["user_id"]),
        total_cost_usd=float(ordered["cost_usd"].fillna(0.0).sum()),
        avg_latency_ms=float(latencies.mean()) if not latencies.empty else None,
        first_seen=_to_utc(start_times.min()) if not start_times.empty else None,
        last_seen=_to_utc(start_times.max()) if not start_times.empty else None,
        span_ids=tuple(ordered["span_id"]),
        asset_classes=_distinct_sorted(ordered["asset_class"]),
        workflow_stages=_distinct_sorted(ordered["workflow_stage"]),
    )


def _n_distinct(series: pd.Series) -> int:
    return int(series.dropna().astype(str).replace("", pd.NA).dropna().nunique())


def _distinct_sorted(series: pd.Series) -> tuple[str, ...]:
    values = {str(v) for v in series.dropna() if str(v).strip()}
    return tuple(sorted(values))


def _to_utc(value: object) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    dt = value.to_pydatetime() if isinstance(value, pd.Timestamp) else value
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
