"""High-signal turn triage: ERROR / latency / cost / tool-count outliers.

Phoenix tracing docs prioritize reviewing these before frequency alone. SkillGap
feeds the Decide boards from this queue and boosts Rung 1/2 scores when a
cluster's members sit on outlier turns.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .insights import error_mask
from .turns import turn_root_spans

_OUTLIER_COLUMNS = [
    "trace_id",
    "session_id",
    "span_id",
    "prompt",
    "n_tools",
    "n_errors",
    "latency_ms",
    "cost_usd",
    "tokens_total",
    "is_error",
    "is_latency_outlier",
    "is_cost_outlier",
    "is_tool_outlier",
    "triage_score",
    "reasons",
]


def turn_outliers(
    spans_df: pd.DataFrame,
    *,
    quantile: float = 0.95,
    min_tools_for_heavy: int = 4,
) -> pd.DataFrame:
    """One row per turn/trace that is an ERROR or statistical outlier.

    Thresholds are corpus-relative (quantile of turn latency / cost / tool
    count), with a floor so tiny corpora do not flag everything.
    """
    if spans_df is None or spans_df.empty or "trace_id" not in spans_df.columns:
        return pd.DataFrame(columns=_OUTLIER_COLUMNS)

    profiles = _turn_profiles(spans_df)
    if profiles.empty:
        return pd.DataFrame(columns=_OUTLIER_COLUMNS)

    lat_cut = _quantile_cut(profiles["latency_ms"], quantile)
    cost_cut = _quantile_cut(profiles["cost_usd"], quantile)
    tool_cut = max(
        float(min_tools_for_heavy),
        _quantile_cut(profiles["n_tools"], quantile) or float(min_tools_for_heavy),
    )

    rows: list[dict[str, Any]] = []
    for row in profiles.to_dict("records"):
        is_error = bool(row["n_errors"] > 0)
        is_lat = bool(
            lat_cut is not None
            and row["latency_ms"] is not None
            and float(row["latency_ms"]) >= lat_cut
        )
        is_cost = bool(
            cost_cut is not None
            and row["cost_usd"] is not None
            and float(row["cost_usd"]) >= cost_cut
        )
        is_tools = bool(int(row["n_tools"]) >= tool_cut)
        if not (is_error or is_lat or is_cost or is_tools):
            continue
        reasons: list[str] = []
        if is_error:
            reasons.append(f"errors:{int(row['n_errors'])}")
        if is_lat:
            reasons.append(f"latency>={lat_cut:.0f}ms")
        if is_cost:
            reasons.append(f"cost>=${cost_cut:.4f}")
        if is_tools:
            reasons.append(f"tools>={int(tool_cut)}")
        triage = (
            3 * int(is_error)
            + 2 * int(is_lat)
            + 2 * int(is_cost)
            + int(is_tools)
            + min(2, int(row["n_errors"]))
        )
        rows.append(
            {
                **row,
                "is_error": is_error,
                "is_latency_outlier": is_lat,
                "is_cost_outlier": is_cost,
                "is_tool_outlier": is_tools,
                "triage_score": triage,
                "reasons": "; ".join(reasons),
            }
        )

    if not rows:
        return pd.DataFrame(columns=_OUTLIER_COLUMNS)
    df = pd.DataFrame(rows, columns=_OUTLIER_COLUMNS)
    return df.sort_values(
        ["triage_score", "cost_usd", "latency_ms"], ascending=False
    ).reset_index(drop=True)


def outlier_trace_ids(spans_df: pd.DataFrame, **kwargs: Any) -> frozenset[str]:
    """Trace ids that belong on the outlier triage queue."""
    frame = turn_outliers(spans_df, **kwargs)
    if frame.empty:
        return frozenset()
    return frozenset(frame["trace_id"].astype(str).tolist())


def cluster_outlier_hits(
    span_ids: tuple[str, ...] | list[str],
    *,
    span_to_trace: dict[str, str],
    outlier_traces: frozenset[str],
) -> int:
    """How many of ``span_ids`` sit on an outlier turn."""
    if not span_ids or not outlier_traces:
        return 0
    hits = 0
    seen: set[str] = set()
    for sid in span_ids:
        tid = span_to_trace.get(str(sid), "")
        if tid and tid in outlier_traces and tid not in seen:
            seen.add(tid)
            hits += 1
    return hits


def cluster_friction_score(
    span_ids: tuple[str, ...] | list[str],
    *,
    span_to_session: dict[str, str],
    friction_by_session: dict[str, float],
) -> float:
    """Max session friction among the cluster's member spans."""
    if not span_ids or not friction_by_session:
        return 0.0
    scores = [
        float(friction_by_session.get(span_to_session.get(str(sid), ""), 0.0) or 0.0)
        for sid in span_ids
    ]
    return max(scores) if scores else 0.0


def priority_boost(*, friction: float, outlier_hits: int) -> float:
    """0–0.35 additive boost folded into Rung 1 gap scores."""
    friction_part = min(0.20, max(0.0, friction) / 20.0)
    outlier_part = min(0.15, 0.05 * max(0, outlier_hits))
    return round(friction_part + outlier_part, 4)


def _turn_profiles(spans_df: pd.DataFrame) -> pd.DataFrame:
    roots = turn_root_spans(spans_df)
    root_prompt: dict[str, str] = {}
    root_span: dict[str, str] = {}
    if not roots.empty and "trace_id" in roots.columns:
        for row in roots.to_dict("records"):
            tid = str(row.get("trace_id") or "")
            if not tid:
                continue
            root_span[tid] = str(row.get("span_id") or "")
            root_prompt[tid] = str(row.get("input_text") or "")[:240]

    rows: list[dict[str, Any]] = []
    for trace_id, group in spans_df.groupby("trace_id", sort=False):
        tid = str(trace_id)
        kinds = group["span_kind"].fillna("").astype(str).str.upper()
        n_tools = int((kinds == "TOOL").sum())
        n_errors = int(error_mask(group["status_code"]).sum()) if "status_code" in group else 0
        # Prefer turn-root latency; else sum child latencies / max end-start.
        latency = None
        if tid in root_span and "latency_ms" in group.columns:
            root_rows = group.loc[group["span_id"].astype(str) == root_span[tid]]
            if not root_rows.empty and pd.notna(root_rows.iloc[0].get("latency_ms")):
                latency = float(root_rows.iloc[0]["latency_ms"])
        if latency is None and "latency_ms" in group.columns:
            vals = group["latency_ms"].dropna()
            latency = float(vals.max()) if not vals.empty else None
        cost = float(group["cost_usd"].fillna(0.0).sum()) if "cost_usd" in group.columns else 0.0
        tokens = (
            int(group["tokens_total"].fillna(0).sum())
            if "tokens_total" in group.columns
            else 0
        )
        sessions = group["session_id"].dropna() if "session_id" in group.columns else pd.Series(dtype=object)
        rows.append(
            {
                "trace_id": tid,
                "session_id": str(sessions.iloc[0]) if not sessions.empty else None,
                "span_id": root_span.get(tid) or str(group.iloc[0].get("span_id") or ""),
                "prompt": root_prompt.get(tid, ""),
                "n_tools": n_tools,
                "n_errors": n_errors,
                "latency_ms": latency,
                "cost_usd": cost,
                "tokens_total": tokens,
            }
        )
    return pd.DataFrame(rows)


def _quantile_cut(series: pd.Series, quantile: float) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if len(vals) < 3:
        return None
    cut = float(vals.quantile(quantile))
    # Floor: must also beat ~median so a flat distribution does not flag all.
    median = float(vals.median())
    return max(cut, median * 1.5) if median > 0 else cut
