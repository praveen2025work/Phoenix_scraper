"""Per-trace tool-path signatures for Rung 2 (stable agent routes).

Phoenix tracing docs rebuild a turn's decision path as ordered TOOL names
(``tool_path``). Clustering those paths — not only raw TOOL payloads — finds
deterministic skills where the agent repeatedly takes the same route.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .normalize import mask_volatile

_MAX_PATH_STEPS = 16


def tool_name(row: dict[str, Any] | pd.Series) -> str:
    """OpenInference ``tool.name``, else span ``name``, else ``tool``."""
    attrs = parse_attributes(row.get("attributes") if hasattr(row, "get") else None)
    if not attrs and isinstance(row, pd.Series):
        attrs = parse_attributes(row.get("attributes"))
    name = (
        attrs.get("tool.name")
        or attrs.get("tool_name")
        or (row.get("name") if hasattr(row, "get") else None)
        or ""
    )
    text = str(name).strip()
    return text or "tool"


def tool_path_signature(group: pd.DataFrame) -> str:
    """Ordered TOOL labels for one trace: ``a → b → c``.

    Names only (args vary too much to stabilize clusters). Consecutive identical
    tools collapse with a count, matching Phoenix flow-style readability.
    """
    if group is None or group.empty:
        return ""
    work = group
    if "span_kind" in work.columns:
        kinds = work["span_kind"].fillna("").astype(str).str.upper()
        tools = work.loc[kinds == "TOOL"]
    else:
        tools = work.iloc[0:0]
    if tools.empty:
        return ""
    if "start_time" in tools.columns:
        tools = tools.sort_values("start_time", kind="mergesort")

    names = [tool_name(row) for row in tools.to_dict("records")]
    collapsed: list[tuple[str, int]] = []
    for name in names:
        if collapsed and collapsed[-1][0] == name:
            collapsed[-1] = (name, collapsed[-1][1] + 1)
        else:
            collapsed.append((name, 1))
    parts = [
        name if n == 1 else f"{name} ×{n}"
        for name, n in collapsed[:_MAX_PATH_STEPS]
    ]
    if len(collapsed) > _MAX_PATH_STEPS:
        parts.append("…")
    return " → ".join(parts)


def tool_path_cluster_frame(spans_df: pd.DataFrame) -> pd.DataFrame:
    """One clustering row per trace that has TOOL spans.

    ``input_text`` is the path signature so :func:`build_clusters` groups stable
    routes. ``span_id`` is the first TOOL span so member→trace expansion still
    reaches sibling LLM outputs for determinism scoring.
    """
    if spans_df is None or spans_df.empty:
        return spans_df if spans_df is not None else pd.DataFrame()
    if "trace_id" not in spans_df.columns or "span_kind" not in spans_df.columns:
        return spans_df.iloc[0:0].copy()

    kinds = spans_df["span_kind"].fillna("").astype(str).str.upper()
    tool_traces = set(
        spans_df.loc[kinds == "TOOL", "trace_id"].dropna().astype(str).tolist()
    )
    if not tool_traces:
        return spans_df.iloc[0:0].copy()

    rows: list[dict[str, Any]] = []
    work = spans_df.copy()
    if "start_time" in work.columns:
        work = work.sort_values("start_time", kind="mergesort")

    for trace_id, group in work.groupby("trace_id", sort=False):
        tid = str(trace_id)
        if tid not in tool_traces:
            continue
        path = tool_path_signature(group)
        if not path:
            continue
        tool_rows = group.loc[
            group["span_kind"].fillna("").astype(str).str.upper() == "TOOL"
        ]
        first = tool_rows.iloc[0]
        rows.append(_path_row(first, group, path))

    if not rows:
        return spans_df.iloc[0:0].copy()
    return pd.DataFrame(rows).reset_index(drop=True)


def merge_deterministic_sources(
    spans_df: pd.DataFrame, payload_frame: pd.DataFrame
) -> pd.DataFrame:
    """Path rows plus payload spans whose traces have no TOOL path yet.

    TOOL spans already represented by a path are dropped from the payload lane
    so the same call is not clustered twice (once as path, once as select:mcp…).
    """
    paths = tool_path_cluster_frame(spans_df)
    if paths.empty:
        return payload_frame.copy() if payload_frame is not None else paths
    if payload_frame is None or payload_frame.empty:
        return paths

    path_traces = set(paths["trace_id"].astype(str))
    keep: list[bool] = []
    for i in range(len(payload_frame)):
        row = payload_frame.iloc[i]
        tid = str(row.get("trace_id") or "")
        kind = str(row.get("span_kind") or "").upper()
        if tid in path_traces and kind in {"TOOL", "RETRIEVER"}:
            keep.append(False)
        else:
            keep.append(True)
    leftover = payload_frame.loc[keep]
    if leftover.empty:
        return paths
    return pd.concat([paths, leftover], ignore_index=True)


def parse_attributes(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _path_row(first: pd.Series, group: pd.DataFrame, path: str) -> dict[str, Any]:
    """Cluster-member row shaped like Store.spans_frame columns."""
    cost = float(group["cost_usd"].fillna(0.0).sum()) if "cost_usd" in group.columns else 0.0
    lat = group["latency_ms"].dropna() if "latency_ms" in group.columns else pd.Series(dtype=float)
    start = first.get("start_time")
    if "start_time" in group.columns and group["start_time"].notna().any():
        start = group["start_time"].min()

    return {
        "span_id": str(first.get("span_id") or ""),
        "trace_id": str(first.get("trace_id") or ""),
        "session_id": first.get("session_id"),
        "project": first.get("project"),
        "name": "tool_path",
        "span_kind": "TOOL",
        "start_time": start,
        "end_time": first.get("end_time"),
        "latency_ms": float(lat.sum()) if not lat.empty else first.get("latency_ms"),
        "status_code": first.get("status_code") or "OK",
        "model_name": first.get("model_name"),
        "user_id": first.get("user_id"),
        "workflow_stage": first.get("workflow_stage"),
        "asset_class": first.get("asset_class"),
        "input_text": path,
        "output_text": mask_volatile(path)[:200],
        "tokens_prompt": None,
        "tokens_completion": None,
        "tokens_total": (
            int(group["tokens_total"].fillna(0).sum())
            if "tokens_total" in group.columns
            else None
        ),
        "cost_usd": cost,
        "attributes": {"pheonix.tool_path": path},
        "parent_id": first.get("parent_id"),
    }
