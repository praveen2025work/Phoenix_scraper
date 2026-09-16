"""Session turn = trace root (agent_request) for Rung 1 asks."""

from datetime import UTC, datetime

import pandas as pd

from phoenix_scraper.prompt_shape import (
    filter_deterministic_source_spans,
    filter_user_ask_spans,
)
from phoenix_scraper.turns import span_records_from_session_turns, turn_root_spans


def _ts(minute: int) -> datetime:
    return datetime(2026, 8, 7, 7, 46, minute, tzinfo=UTC)


class TestTurnRootSpans:
    def test_prefers_agent_request_over_nested_llm(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "span_id": "root",
                    "trace_id": "tr-1",
                    "name": "agent_request",
                    "span_kind": "CHAIN",
                    "start_time": _ts(0),
                    "input_text": "analyze UAXK and UZRZ journals and let me know",
                },
                {
                    "span_id": "think",
                    "trace_id": "tr-1",
                    "name": "agent.thinking",
                    "span_kind": "LLM",
                    "start_time": _ts(1),
                    "input_text": "plan the journal analysis steps",
                },
                {
                    "span_id": "tool",
                    "trace_id": "tr-1",
                    "name": "agent.tool",
                    "span_kind": "TOOL",
                    "start_time": _ts(2),
                    "input_text": "select:mcp__data-analysis__query_data",
                },
            ]
        )
        roots = turn_root_spans(df)
        assert list(roots["span_id"]) == ["root"]
        asks = filter_user_ask_spans(df)
        assert list(asks["span_id"]) == ["root"]
        assert "UAXK" in asks.iloc[0]["input_text"]
        # Nested tool stays on deterministic lane; nested NL LLM is neither ask nor tool.
        dets = filter_deterministic_source_spans(df)
        assert list(dets["span_id"]) == ["tool"]
        assert "think" not in set(asks["span_id"]) | set(dets["span_id"])

    def test_one_ask_per_trace_across_session(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "span_id": "t0-root",
                    "trace_id": "c4fe",
                    "name": "agent_request",
                    "span_kind": "CHAIN",
                    "start_time": _ts(0),
                    "input_text": (
                        "We are testing FOBO INVESTIGATION. "
                        "Read FOBO_Investigation_Skill_v2.0.md"
                    ),
                },
                {
                    "span_id": "t0-llm",
                    "trace_id": "c4fe",
                    "name": "agent.thinking",
                    "span_kind": "LLM",
                    "start_time": _ts(1),
                    "input_text": "load the skill files now",
                },
                {
                    "span_id": "t1-root",
                    "trace_id": "87bf",
                    "name": "agent_request",
                    "span_kind": "CHAIN",
                    "start_time": _ts(10),
                    "input_text": "analyze UAXK and UZRZ journals and let me know",
                },
                {
                    "span_id": "t1-llm",
                    "trace_id": "87bf",
                    "name": "agent.thinking",
                    "span_kind": "LLM",
                    "start_time": _ts(11),
                    "input_text": "reload Trial Balance and RecFactory",
                },
            ]
        )
        asks = filter_user_ask_spans(df)
        assert list(asks["span_id"]) == ["t0-root", "t1-root"]
        texts = list(asks["input_text"])
        assert any("FOBO INVESTIGATION" in t for t in texts)
        assert any("UAXK" in t for t in texts)

    def test_fixture_style_llm_only_still_works(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "span_id": "llm-1",
                    "trace_id": "tr-9",
                    "name": "llm-call",
                    "span_kind": "LLM",
                    "start_time": _ts(0),
                    "input_text": "Why is there a recon break of 100k?",
                },
                {
                    "span_id": "agent-1",
                    "trace_id": "tr-9",
                    "name": "pnl-agent-step",
                    "span_kind": "AGENT",
                    "start_time": _ts(1),
                    "input_text": "",
                },
            ]
        )
        asks = filter_user_ask_spans(df)
        assert list(asks["span_id"]) == ["llm-1"]


class TestSessionTurnRecords:
    def test_span_records_from_session_turns(self) -> None:
        turns = [
            {
                "trace_id": "c4fe7f446fd938d67a26e6143c8efc88",
                "start_time": "2026-08-07T07:46:46.378567+00:00",
                "end_time": "2026-08-07T08:07:23.000000+00:00",
                "input": {
                    "value": "analyze UAXK and UZRZ journals and let me know"
                },
                "output": {"value": "journal analysis json…"},
                "root_span": {
                    "context": {"span_id": "span-root-1"},
                    "name": "agent_request",
                    "attributes": {"openinference.span.kind": "CHAIN"},
                    "cumulativeTokenCountTotal": 17134,
                    "cost_summary": {"total": {"cost": 0.21}},
                },
            }
        ]
        rows = span_records_from_session_turns(
            turns, project="pnl-agent", session_id="756f6061-0012-43da-b91a-39bea6a9ba6b"
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.span_id == "span-root-1"
        assert row.trace_id.startswith("c4fe")
        assert row.name == "agent_request"
        assert row.span_kind == "CHAIN"
        assert "UAXK" in row.input_text
        assert row.cost_usd == 0.21
        assert row.tokens_total == 17134
