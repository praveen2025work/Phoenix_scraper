"""Per-turn latency breakdown: thinking vs tool/query time.

Each Phoenix session turn is one trace. Child spans under the ``agent_request``
root show where wall time went — ``agent.thinking`` / LLM vs ``agent.tool`` /
TOOL/RETRIEVER — so operators can see why a FOBO ask took 20 minutes.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .prompt_shape import extract_user_prompt
from .turns import turn_root_spans

_THINKING_NAME_HINTS = ("thinking", "llm", "sdk_call", "model")
_TOOL_NAME_HINTS = ("tool", "retriev", "mcp", "query", "sql")


def span_role(name: object, span_kind: object, *, is_root: bool = False) -> str:
    """Classify a span as root | thinking | tool | other for latency rollups."""
    if is_root:
        return "root"
    kind = str(span_kind or "").strip().upper()
    n = str(name or "").casefold()
    if kind in {"TOOL", "RETRIEVER"} or any(h in n for h in _TOOL_NAME_HINTS):
        return "tool"
    if kind == "LLM" or any(h in n for h in _THINKING_NAME_HINTS):
        return "thinking"
    if kind in {"CHAIN", "AGENT"}:
        return "thinking"
    return "other"


def turn_latency_frame(spans_df: pd.DataFrame) -> pd.DataFrame:
    """One row per turn/trace with thinking vs tool latency totals (ms)."""
    if spans_df is None or spans_df.empty or "trace_id" not in spans_df.columns:
        return pd.DataFrame(
            columns=[
                "trace_id",
                "session_id",
                "ask",
                "turn_ms",
                "thinking_ms",
                "tool_ms",
                "other_ms",
                "bottleneck",
                "n_thinking",
                "n_tools",
                "root_span_id",
            ]
        )

    roots = turn_root_spans(spans_df)
    root_by_trace: dict[str, pd.Series] = {}
    if not roots.empty:
        for _, row in roots.iterrows():
            root_by_trace[str(row["trace_id"])] = row

    rows: list[dict[str, Any]] = []
    work = spans_df.copy()
    if "latency_ms" not in work.columns:
        work["latency_ms"] = None

    for trace_id, group in work.groupby("trace_id", sort=False):
        tid = str(trace_id)
        root = root_by_trace.get(tid)
        root_id = str(root["span_id"]) if root is not None and "span_id" in root else ""
        thinking = tool = other = 0.0
        n_thinking = n_tools = 0
        for _, span in group.iterrows():
            sid = str(span.get("span_id") or "")
            is_root = bool(root_id and sid == root_id)
            role = span_role(span.get("name"), span.get("span_kind"), is_root=is_root)
            if role == "root":
                continue
            try:
                ms = float(span["latency_ms"]) if pd.notna(span.get("latency_ms")) else 0.0
            except (TypeError, ValueError):
                ms = 0.0
            if role == "thinking":
                thinking += ms
                n_thinking += 1
            elif role == "tool":
                tool += ms
                n_tools += 1
            else:
                other += ms

        turn_ms = None
        ask = ""
        session_id = None
        if root is not None:
            if pd.notna(root.get("latency_ms")):
                try:
                    turn_ms = float(root["latency_ms"])
                except (TypeError, ValueError):
                    turn_ms = None
            ask = extract_user_prompt(str(root.get("input_text") or ""))
            session_id = root.get("session_id")
        if turn_ms is None:
            turn_ms = thinking + tool + other

        parts = {"thinking": thinking, "tool": tool, "other": other}
        bottleneck = max(parts, key=parts.get) if any(parts.values()) else "unknown"
        if turn_ms and turn_ms > 0 and max(parts.values()) < turn_ms * 0.15:
            # Children don't explain wall time (overlap / uninstrumented) —
            # keep unknown rather than mis-blame a tiny tool.
            if max(parts.values()) < 1000:
                bottleneck = "unknown"

        rows.append(
            {
                "trace_id": tid,
                "session_id": session_id,
                "ask": ask,
                "turn_ms": round(turn_ms, 1) if turn_ms is not None else None,
                "thinking_ms": round(thinking, 1),
                "tool_ms": round(tool, 1),
                "other_ms": round(other, 1),
                "bottleneck": bottleneck,
                "n_thinking": n_thinking,
                "n_tools": n_tools,
                "root_span_id": root_id or None,
            }
        )

    return pd.DataFrame(rows)


def summarize_turn_latency(spans_df: pd.DataFrame, *, top_n: int = 5) -> dict[str, Any]:
    """Aggregate turn timing for job WIP stats and run notes."""
    frame = turn_latency_frame(spans_df)
    empty = {
        "n_turns": 0,
        "avg_turn_ms": None,
        "avg_thinking_ms": None,
        "avg_tool_ms": None,
        "pct_bottleneck_thinking": None,
        "pct_bottleneck_tool": None,
        "slowest_turns": [],
    }
    if frame.empty:
        return empty

    def _mean(col: str) -> float | None:
        s = frame[col].dropna()
        return round(float(s.mean()), 1) if not s.empty else None

    n = int(len(frame))
    bottlenecks = frame["bottleneck"].fillna("unknown")
    pct_thinking = round(100.0 * float((bottlenecks == "thinking").mean()), 1)
    pct_tool = round(100.0 * float((bottlenecks == "tool").mean()), 1)

    slow = frame.sort_values("turn_ms", ascending=False, na_position="last").head(top_n)
    slowest = []
    for _, row in slow.iterrows():
        ask = str(row.get("ask") or "")
        if len(ask) > 120:
            ask = ask[:119].rstrip() + "…"
        slowest.append(
            {
                "trace_id": row["trace_id"],
                "ask": ask,
                "turn_ms": row.get("turn_ms"),
                "thinking_ms": row.get("thinking_ms"),
                "tool_ms": row.get("tool_ms"),
                "bottleneck": row.get("bottleneck"),
                "n_tools": int(row.get("n_tools") or 0),
                "n_thinking": int(row.get("n_thinking") or 0),
            }
        )

    return {
        "n_turns": n,
        "avg_turn_ms": _mean("turn_ms"),
        "avg_thinking_ms": _mean("thinking_ms"),
        "avg_tool_ms": _mean("tool_ms"),
        "pct_bottleneck_thinking": pct_thinking,
        "pct_bottleneck_tool": pct_tool,
        "slowest_turns": slowest,
    }


def format_turn_latency_notes(summary: dict[str, Any]) -> list[str]:
    """Human-readable notes for capability run output."""
    n = int(summary.get("n_turns") or 0)
    if n <= 0:
        return []
    notes = [
        (
            f"turn latency: {n} turns · avg "
            f"{_fmt_ms(summary.get('avg_turn_ms'))} "
            f"(thinking {_fmt_ms(summary.get('avg_thinking_ms'))} / "
            f"tools {_fmt_ms(summary.get('avg_tool_ms'))})"
        )
    ]
    pt = summary.get("pct_bottleneck_thinking")
    pq = summary.get("pct_bottleneck_tool")
    if pt is not None and pq is not None:
        notes.append(
            f"turn bottlenecks: {pt}% thinking · {pq}% tools/queries"
        )
    for item in summary.get("slowest_turns") or []:
        ask = item.get("ask") or "(no ask text)"
        notes.append(
            f"slow turn [{item.get('bottleneck')}]: "
            f"{_fmt_ms(item.get('turn_ms'))} "
            f"(think {_fmt_ms(item.get('thinking_ms'))}, "
            f"tools {_fmt_ms(item.get('tool_ms'))}) — {ask}"
        )
    return notes


def _fmt_ms(value: object) -> str:
    if value is None:
        return "—"
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return "—"
    if ms >= 60_000:
        return f"{ms / 60_000:.1f}m"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms:.0f}ms"
