"""Tests for per-user analytics and LLM-behavior analytics."""

from datetime import timedelta

import pandas as pd
from test_insights import BASE_TS, frame, span

from phoenix_scraper import insights_llm, insights_users


class TestUserProfiles:
    def _spans(self) -> pd.DataFrame:
        rows = []
        # alice: 2 sessions, 3 asks, one reformulation pair
        rows.append(span(0, user_id="alice", session_id="a1",
                         input_text="why is there an fx break of 100k on EURUSD?"))
        rows.append(span(1, user_id="alice", session_id="a1",
                         input_text="why is there an fx break of 250k on EURUSD??"))
        rows.append(span(2, user_id="alice", session_id="a2", input_text="show flash pnl"))
        rows.append(span(3, user_id="alice", session_id="a2", span_kind="TOOL", input_text="",
                         trace_id="t0002"))
        # bob: 1 session, 1 ask, 1 error span
        rows.append(span(4, user_id="bob", session_id="b1", input_text="what is plex?",
                         status_code="ERROR"))
        return frame(rows)

    def test_per_user_rollup(self) -> None:
        df = insights_users.user_profiles(self._spans())

        assert set(df["user_id"]) == {"alice", "bob"}
        alice = df[df["user_id"] == "alice"].iloc[0]
        assert alice["n_asks"] == 3
        assert alice["n_sessions"] == 2
        assert alice["n_reformulations"] == 1
        assert "why" in alice["top_intents"]
        assert alice["total_tokens"] == 4 * 150
        bob = df[df["user_id"] == "bob"].iloc[0]
        assert bob["n_asks"] == 1
        assert bob["n_errors"] == 1

    def test_sorted_by_asks(self) -> None:
        df = insights_users.user_profiles(self._spans())
        assert df.iloc[0]["user_id"] == "alice"

    def test_empty(self) -> None:
        assert insights_users.user_profiles(frame([])).empty


class TestUserQuestionMatrix:
    def test_counts_per_user_and_type(self) -> None:
        rows = [
            span(0, user_id="alice", input_text="why did it break?"),
            span(1, user_id="alice", input_text="why again?"),
            span(2, user_id="bob", input_text="show me the report"),
        ]
        df = insights_users.user_question_matrix(frame(rows))
        alice_why = df[(df["user_id"] == "alice") & (df["question_type"] == "why")]
        assert int(alice_why.iloc[0]["count"]) == 2
        bob_req = df[(df["user_id"] == "bob") & (df["question_type"] == "request")]
        assert int(bob_req.iloc[0]["count"]) == 1


class TestDailyActivity:
    def test_daily_counts(self) -> None:
        rows = [
            span(0, start_time=BASE_TS),
            span(1, start_time=BASE_TS + timedelta(hours=2)),
            span(2, start_time=BASE_TS + timedelta(days=1)),
        ]
        df = insights_users.daily_activity(frame(rows))
        assert len(df) == 2
        assert int(df.iloc[0]["n_asks"]) == 2
        assert "n_sessions" in df.columns and "total_cost_usd" in df.columns


class TestToolUsage:
    def test_per_tool_stats(self) -> None:
        rows = [
            span(0, span_kind="TOOL", name="query_breaks", trace_id="t1", latency_ms=100.0),
            span(1, span_kind="TOOL", name="query_breaks", trace_id="t2",
                 status_code="ERROR", latency_ms=300.0),
            span(2, span_kind="TOOL", name="export_csv", trace_id="t1", latency_ms=50.0),
            span(3, span_kind="LLM", name="ChatCompletion", trace_id="t1"),
        ]
        df = insights_llm.tool_usage(frame(rows))

        assert set(df["tool"]) == {"query_breaks", "export_csv"}
        qb = df[df["tool"] == "query_breaks"].iloc[0]
        assert qb["n_calls"] == 2
        assert qb["n_traces"] == 2
        assert qb["error_rate"] == 0.5
        assert qb["avg_latency_ms"] == 200.0

    def test_no_tools(self) -> None:
        assert insights_llm.tool_usage(frame([span(0)])).empty


class TestModelUsage:
    def test_per_model_stats(self) -> None:
        rows = [
            span(0, model_name="sonnet", tokens_prompt=100, tokens_completion=50),
            span(1, model_name="sonnet", tokens_prompt=200, tokens_completion=100,
                 tokens_total=300),
            span(2, model_name="haiku", tokens_total=30, cost_usd=0.001),
        ]
        df = insights_llm.model_usage(frame(rows))
        sonnet = df[df["model"] == "sonnet"].iloc[0]
        assert sonnet["n_calls"] == 2
        assert sonnet["tokens_in"] == 300
        assert sonnet["tokens_out"] == 150
        assert df.iloc[0]["model"] == "sonnet"  # sorted by calls


class TestAgentFlows:
    def test_flow_signatures(self) -> None:
        rows = [
            # two traces with the same LLM->TOOL->LLM shape
            span(0, trace_id="t1", span_kind="LLM", input_text="q1"),
            span(1, trace_id="t1", span_kind="TOOL"),
            span(2, trace_id="t1", span_kind="LLM"),
            span(3, trace_id="t2", span_kind="LLM", input_text="q2"),
            span(4, trace_id="t2", span_kind="TOOL"),
            span(5, trace_id="t2", span_kind="LLM"),
            # one single-shot trace
            span(6, trace_id="t3", span_kind="LLM", input_text="q3"),
        ]
        df = insights_llm.agent_flows(frame(rows))

        assert df.iloc[0]["flow"] == "LLM → TOOL → LLM"
        assert int(df.iloc[0]["n_traces"]) == 2
        assert "example_prompt" in df.columns

    def test_repeated_kind_collapsed_with_counts(self) -> None:
        rows = [
            span(0, trace_id="t1", span_kind="LLM", input_text="q"),
            span(1, trace_id="t1", span_kind="TOOL"),
            span(2, trace_id="t1", span_kind="TOOL"),
            span(3, trace_id="t1", span_kind="TOOL"),
            span(4, trace_id="t1", span_kind="LLM"),
        ]
        df = insights_llm.agent_flows(frame(rows))
        assert df.iloc[0]["flow"] == "LLM → TOOL ×3 → LLM"


class TestStageAssetBreakdown:
    def test_rollup(self) -> None:
        rows = [
            span(0, workflow_stage="fobo_recon", asset_class="fx", input_text="q1"),
            span(1, workflow_stage="fobo_recon", asset_class="fx", input_text="q2"),
            span(2, workflow_stage="plex", asset_class="rates", input_text="q3"),
            span(3, workflow_stage=None, asset_class=None, input_text="q4"),
        ]
        df = insights_llm.stage_asset_breakdown(frame(rows))

        fobo = df[(df["workflow_stage"] == "fobo_recon") & (df["asset_class"] == "fx")]
        assert int(fobo.iloc[0]["n_asks"]) == 2
        unattributed = df[df["workflow_stage"] == "(unattributed)"]
        assert int(unattributed.iloc[0]["n_asks"]) == 1
