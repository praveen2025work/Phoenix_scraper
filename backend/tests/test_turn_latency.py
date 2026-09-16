"""Turn latency: thinking vs tool/query time inside each Phoenix turn."""

from datetime import UTC, datetime

import pandas as pd

from phoenix_scraper.turn_latency import (
    format_turn_latency_notes,
    summarize_turn_latency,
    turn_latency_frame,
)


def _ts(sec: int) -> datetime:
    return datetime(2026, 8, 7, 7, 46, sec, tzinfo=UTC)


def test_tool_heavy_turn_bottleneck() -> None:
    df = pd.DataFrame(
        [
            {
                "span_id": "root",
                "trace_id": "tr-1",
                "name": "agent_request",
                "span_kind": "CHAIN",
                "parent_id": None,
                "start_time": _ts(0),
                "latency_ms": 200_000.0,
                "input_text": "analyze UAXK and UZRZ journals and let me know",
                "session_id": "sess-1",
            },
            {
                "span_id": "think",
                "trace_id": "tr-1",
                "name": "agent.thinking",
                "span_kind": "LLM",
                "parent_id": "root",
                "start_time": _ts(1),
                "latency_ms": 5_000.0,
                "input_text": "plan",
            },
            {
                "span_id": "tool1",
                "trace_id": "tr-1",
                "name": "agent.tool",
                "span_kind": "TOOL",
                "parent_id": "root",
                "start_time": _ts(2),
                "latency_ms": 120_000.0,
                "input_text": "select:mcp__data-analysis__query_data",
            },
            {
                "span_id": "tool2",
                "trace_id": "tr-1",
                "name": "agent.tool",
                "span_kind": "TOOL",
                "parent_id": "root",
                "start_time": _ts(3),
                "latency_ms": 60_000.0,
                "input_text": "reload trial balance",
            },
        ]
    )
    frame = turn_latency_frame(df)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["bottleneck"] == "tool"
    assert row["tool_ms"] == 180_000.0
    assert row["thinking_ms"] == 5_000.0
    assert "UAXK" in row["ask"]

    summary = summarize_turn_latency(df)
    assert summary["n_turns"] == 1
    assert summary["pct_bottleneck_tool"] == 100.0
    notes = format_turn_latency_notes(summary)
    assert any("tools" in n for n in notes)
    assert any("UAXK" in n for n in notes)


def test_thinking_heavy_turn_bottleneck() -> None:
    df = pd.DataFrame(
        [
            {
                "span_id": "root",
                "trace_id": "tr-2",
                "name": "agent_request",
                "span_kind": "CHAIN",
                "parent_id": None,
                "start_time": _ts(0),
                "latency_ms": 1_200_000.0,
                "input_text": "We are testing FOBO INVESTIGATION",
            },
            {
                "span_id": "t1",
                "trace_id": "tr-2",
                "name": "agent.thinking",
                "span_kind": "LLM",
                "parent_id": "root",
                "start_time": _ts(1),
                "latency_ms": 800_000.0,
                "input_text": "read skills",
            },
            {
                "span_id": "tool",
                "trace_id": "tr-2",
                "name": "agent.tool",
                "span_kind": "TOOL",
                "parent_id": "root",
                "start_time": _ts(2),
                "latency_ms": 2_000.0,
                "input_text": "list files",
            },
        ]
    )
    row = turn_latency_frame(df).iloc[0]
    assert row["bottleneck"] == "thinking"
    assert row["thinking_ms"] == 800_000.0


def test_parent_id_none_selects_root() -> None:
    df = pd.DataFrame(
        [
            {
                "span_id": "child-llm",
                "trace_id": "tr-3",
                "name": "llm-call",
                "span_kind": "LLM",
                "parent_id": "root",
                "start_time": _ts(1),
                "latency_ms": 100.0,
                "input_text": "nested planner text that looks like a question why",
            },
            {
                "span_id": "root",
                "trace_id": "tr-3",
                "name": "chain",
                "span_kind": "CHAIN",
                "parent_id": None,
                "start_time": _ts(0),
                "latency_ms": 500.0,
                "input_text": "why is there a recon break on UAXK?",
            },
        ]
    )
    from phoenix_scraper.prompt_shape import filter_user_ask_spans

    asks = filter_user_ask_spans(df)
    assert list(asks["span_id"]) == ["root"]
