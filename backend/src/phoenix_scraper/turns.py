"""Phoenix session turns = traces: one user ask per agent_request root.

The Phoenix Sessions UI (Turns / Traces tabs) lists one turn per trace. Each
turn's root span is typically ``agent_request``; its ``input.value`` is the
operator prompt shown in the UI, and nested thinking/tool/LLM spans are *not*
separate user asks.

SkillGap Rung 1 (prompt→skill) must cluster these turn roots — not every LLM
span inside the trace.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .llm_messages import prefer_messages_io
from .models import SpanRecord
from .normalize import format_user_text

# Phoenix UI root name for a conversational turn (see Sessions → Traces).
_TURN_ROOT_NAMES = frozenset({"agent_request"})
_ROOT_KINDS = frozenset({"CHAIN", "AGENT"})
_ASK_KINDS = frozenset({"CHAIN", "AGENT", "LLM"})


def turn_root_spans(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per ``trace_id``: the session-turn root span.

    Selection order inside a trace (matches Phoenix ``get_session_turns``):

    1. Span named ``agent_request`` (earliest if several)
    2. Earliest CHAIN/AGENT with non-empty ``input_text``
    3. Earliest LLM/CHAIN/AGENT with non-empty ``input_text``
    4. Earliest span with any non-empty ``input_text``
    """
    if spans_df is None or spans_df.empty:
        return spans_df if spans_df is not None else pd.DataFrame()
    if "trace_id" not in spans_df.columns:
        return spans_df.iloc[0:0].copy()

    work = spans_df.copy()
    if "start_time" in work.columns:
        work = work.sort_values("start_time", kind="mergesort")

    roots: list[pd.Series] = []
    for _, group in work.groupby("trace_id", sort=False):
        picked = _pick_root_row(group)
        if picked is not None:
            roots.append(picked)
    if not roots:
        return work.iloc[0:0].copy()
    return pd.DataFrame(roots).reset_index(drop=True)


def _pick_root_row(group: pd.DataFrame) -> pd.Series | None:
    if group.empty:
        return None

    # Phoenix docs: turn roots have parent_id is None.
    if "parent_id" in group.columns:
        parents = group["parent_id"]
        is_root = parents.isna() | (parents.astype(str).str.strip() == "") | (
            parents.astype(str).str.casefold().isin({"none", "nan", "null"})
        )
        rooted = group.loc[is_root]
        if not rooted.empty:
            # Prefer named agent_request among roots when several exist.
            if "name" in rooted.columns:
                named = rooted.loc[
                    rooted["name"].fillna("").astype(str).str.casefold().isin(
                        _TURN_ROOT_NAMES
                    )
                ]
                if not named.empty:
                    return named.iloc[0]
            return rooted.iloc[0]

    names = (
        group["name"].fillna("").astype(str).str.casefold()
        if "name" in group.columns
        else pd.Series([""] * len(group), index=group.index)
    )
    named = group.loc[names.isin(_TURN_ROOT_NAMES)]
    if not named.empty:
        return named.iloc[0]

    kinds = (
        group["span_kind"].fillna("").astype(str).str.upper()
        if "span_kind" in group.columns
        else pd.Series(["UNKNOWN"] * len(group), index=group.index)
    )
    inputs = (
        group["input_text"].fillna("").astype(str).str.strip()
        if "input_text" in group.columns
        else pd.Series([""] * len(group), index=group.index)
    )
    has_input = inputs != ""

    chain_agent = group.loc[kinds.isin(_ROOT_KINDS) & has_input]
    if not chain_agent.empty:
        return chain_agent.iloc[0]

    askish = group.loc[kinds.isin(_ASK_KINDS) & has_input]
    if not askish.empty:
        return askish.iloc[0]

    any_input = group.loc[has_input]
    if not any_input.empty:
        return any_input.iloc[0]
    return None


def span_records_from_session_turns(
    turns: list[dict[str, Any]],
    *,
    project: str,
    session_id: str,
    user_id: str | None = None,
) -> list[SpanRecord]:
    """Map Phoenix ``SessionTurn`` dicts onto SpanRecords for upsert.

    Prefer the live root span id when present so we refresh the same row the
    span scrape already inserted; otherwise synthesize ``turn:{trace_id}``.
    """
    out: list[SpanRecord] = []
    for turn in turns:
        trace_id = str(turn.get("trace_id") or "").strip()
        if not trace_id:
            continue
        root = turn.get("root_span") or {}
        attrs = root.get("attributes") if isinstance(root, dict) else None
        if not isinstance(attrs, dict):
            attrs = {}

        input_text = _turn_io_value(turn.get("input"))
        output_text = _turn_io_value(turn.get("output"))
        if isinstance(attrs, dict):
            msg_in, msg_out = prefer_messages_io(
                attributes=attrs,
                input_value=str(attrs.get("input.value") or attrs.get("input") or ""),
                output_value=str(
                    attrs.get("output.value") or attrs.get("output") or ""
                ),
            )
            input_text = input_text or msg_in
            output_text = output_text or msg_out

        # Prefer the typed ask (USER QUERY / messages); escaped \\n → real breaks.
        if input_text:
            from .prompt_shape import extract_user_prompt

            input_text = extract_user_prompt(input_text)
        if output_text:
            output_text = format_user_text(output_text)

        span_id = _root_span_id(root) or f"turn:{trace_id}"
        start = _parse_dt(turn.get("start_time")) or _parse_dt(root.get("start_time"))
        if start is None:
            continue
        end = _parse_dt(turn.get("end_time")) or _parse_dt(root.get("end_time"))
        latency = None
        if end is not None:
            latency = (end - start).total_seconds() * 1000.0
        elif isinstance(root, dict) and root.get("latency_ms") is not None:
            try:
                latency = float(root["latency_ms"])
            except (TypeError, ValueError):
                latency = None

        name = ""
        kind = "CHAIN"
        if isinstance(root, dict):
            name = str(root.get("name") or "") or "agent_request"
            # OpenInference kind may sit on the span or under attributes.
            raw_kind = root.get("span_kind") or attrs.get(
                "openinference.span.kind"
            )
            if raw_kind:
                kind = str(raw_kind).upper()
        if not name:
            name = "agent_request"

        tokens_total = None
        cost = None
        if isinstance(root, dict):
            for key in ("cumulative_token_count_total", "cumulativeTokenCountTotal"):
                if root.get(key) is not None:
                    try:
                        tokens_total = int(float(root[key]))
                    except (TypeError, ValueError):
                        pass
            cost_summary = root.get("cost_summary") or {}
            if isinstance(cost_summary, dict):
                total = cost_summary.get("total") or {}
                if isinstance(total, dict) and total.get("cost") is not None:
                    try:
                        cost = float(total["cost"])
                    except (TypeError, ValueError):
                        pass

        out.append(
            SpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                session_id=session_id,
                project=project,
                name=name,
                span_kind=kind,
                start_time=start,
                end_time=end,
                latency_ms=latency,
                user_id=user_id,
                input_text=input_text or "",
                output_text=output_text or "",
                tokens_total=tokens_total,
                cost_usd=cost,
                attributes={
                    "pheonix.turn_source": "session_turns",
                    **{k: v for k, v in attrs.items() if isinstance(k, str)},
                },
                parent_id=None,
            )
        )
    return out


def _turn_io_value(io: object) -> str:
    if not isinstance(io, dict):
        return ""
    return str(io.get("value") or "").strip()


def _root_span_id(root: object) -> str | None:
    if not isinstance(root, dict):
        return None
    ctx = root.get("context")
    if isinstance(ctx, dict):
        sid = ctx.get("span_id") or ctx.get("spanId")
        if sid:
            return str(sid)
    sid = root.get("span_id") or root.get("id")
    return str(sid) if sid else None


def _parse_dt(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
