"""Tests for insights: trace profiles, question taxonomy, friction, efficiency."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from phoenix_scraper import insights

BASE_TS = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)

_COLUMNS = [
    "span_id", "trace_id", "session_id", "project", "name", "span_kind",
    "start_time", "end_time", "latency_ms", "status_code", "model_name",
    "user_id", "workflow_stage", "asset_class", "input_text", "output_text",
    "prompt_template", "tokens_prompt", "tokens_completion", "tokens_total",
    "cost_usd", "attributes",
]


def span(i: int, **overrides) -> dict:
    row = {
        "span_id": f"s{i:04d}",
        "trace_id": f"t{i:04d}",
        "session_id": "sess-1",
        "project": "default",
        "name": "ChatCompletion",
        "span_kind": "LLM",
        "start_time": BASE_TS + timedelta(minutes=i),
        "end_time": BASE_TS + timedelta(minutes=i, seconds=3),
        "latency_ms": 3000.0,
        "status_code": "OK",
        "model_name": "sonnet",
        "user_id": "user-1",
        "workflow_stage": None,
        "asset_class": None,
        "input_text": "",
        "output_text": "answer",
        "prompt_template": None,
        "tokens_prompt": 100,
        "tokens_completion": 50,
        "tokens_total": 150,
        "cost_usd": 0.01,
        "attributes": "{}",
    }
    row.update(overrides)
    return row


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


class TestTraceProfiles:
    def test_counts_span_kinds_and_route_length(self) -> None:
        rows = [
            span(0, trace_id="t1", span_kind="AGENT"),
            span(1, trace_id="t1", span_kind="LLM", input_text="why is there a break?"),
            span(2, trace_id="t1", span_kind="TOOL"),
            span(3, trace_id="t1", span_kind="TOOL"),
            span(4, trace_id="t1", span_kind="LLM"),
            span(5, trace_id="t2", span_kind="LLM", input_text="what is plex?"),
        ]
        df = insights.trace_profiles(frame(rows))

        assert len(df) == 2
        t1 = df[df["trace_id"] == "t1"].iloc[0]
        assert t1["n_spans"] == 5
        assert t1["n_llm"] == 2
        assert t1["n_tool"] == 2
        assert t1["first_prompt"] == "why is there a break?"
        assert t1["total_tokens"] == 5 * 150
        t2 = df[df["trace_id"] == "t2"].iloc[0]
        assert t2["n_spans"] == 1

    def test_error_traces_flagged(self) -> None:
        rows = [
            span(0, trace_id="t1", status_code="ERROR"),
            span(1, trace_id="t1"),
            span(2, trace_id="t2"),
        ]
        df = insights.trace_profiles(frame(rows))
        assert int(df[df["trace_id"] == "t1"].iloc[0]["n_errors"]) == 1
        assert int(df[df["trace_id"] == "t2"].iloc[0]["n_errors"]) == 0

    def test_unset_status_is_not_an_error(self) -> None:
        # OpenTelemetry/Phoenix spans routinely carry UNSET — never a failure.
        rows = [span(0, trace_id="t1", status_code="UNSET")]
        df = insights.trace_profiles(frame(rows))
        assert int(df.iloc[0]["n_errors"]) == 0

    def test_empty_frame(self) -> None:
        df = insights.trace_profiles(frame([]))
        assert df.empty


class TestQuestionTaxonomy:
    def test_classifies_question_types(self) -> None:
        rows = [
            span(0, input_text="Why is there an FX break of 100k on EURUSD?"),
            span(1, input_text="why is there a rates break of 20k?", session_id="sess-2"),
            span(2, input_text="What is the flash P&L for book EQ_NY1?"),
            span(3, input_text="Show me the unexplained for the fx desk"),
            span(4, input_text="how do I export adjustments?"),
            span(5, input_text="Book the adjustment now please"),
        ]
        df = insights.question_taxonomy(frame(rows))

        by_type = dict(zip(df["question_type"], df["count"], strict=True))
        assert by_type["why"] == 2
        assert by_type["what"] == 1
        assert by_type["how"] == 1
        assert by_type["request"] >= 1  # "Show me ..."
        why = df[df["question_type"] == "why"].iloc[0]
        assert why["n_sessions"] == 2
        assert why["example"]

    def test_entity_flags_counted(self) -> None:
        rows = [span(0, input_text="Why is there a 100k break on EURUSD?")]
        df = insights.question_taxonomy(frame(rows))
        row = df.iloc[0]
        assert row["asks_with_amounts"] == 1
        assert row["asks_with_ccy"] == 1

    def test_skips_non_llm_and_empty(self) -> None:
        rows = [
            span(0, span_kind="TOOL", input_text="tool payload"),
            span(1, input_text=""),
        ]
        assert insights.question_taxonomy(frame(rows)).empty


class TestSessionFriction:
    def test_reformulation_detected(self) -> None:
        rows = [
            span(0, input_text="why is there an fx break of 100k on EURUSD?"),
            span(1, input_text="why is there an fx break of 250k on EURUSD??"),  # re-ask
            span(2, input_text="show flash pnl", session_id="sess-2"),
        ]
        df = insights.session_friction(frame(rows))

        s1 = df[df["session_id"] == "sess-1"].iloc[0]
        assert s1["n_turns"] == 2
        assert s1["n_reformulations"] == 1
        assert s1["friction_score"] > 0
        s2 = df[df["session_id"] == "sess-2"].iloc[0]
        assert s2["n_reformulations"] == 0

    def test_different_entities_are_not_reformulations(self) -> None:
        # Same sentence shape, different currency/amount = a different question.
        rows = [
            span(0, input_text="why is there a EUR break of 100k?"),
            span(1, input_text="why is there a JPY break of 5m?"),
            span(2, input_text="flash pnl for book EQ_NY1"),
            span(3, input_text="flash pnl for book FX_LDN2"),
        ]
        df = insights.session_friction(frame(rows))
        assert int(df.iloc[0]["n_reformulations"]) == 0

    def test_errors_and_empty_outputs_raise_friction(self) -> None:
        rows = [
            span(0, input_text="q1", output_text="", status_code="ERROR"),
            span(1, input_text="totally different question about swaps"),
        ]
        df = insights.session_friction(frame(rows))
        row = df.iloc[0]
        assert row["n_errors"] == 1
        assert row["n_empty_responses"] == 1
        assert row["friction_score"] >= 3

    def test_sessions_sorted_by_friction(self) -> None:
        rows = [
            span(0, input_text="fine question", session_id="calm"),
            span(1, input_text="q", status_code="ERROR", output_text="", session_id="angry"),
            span(2, input_text="q again q again", status_code="ERROR", session_id="angry"),
        ]
        df = insights.session_friction(frame(rows))
        assert df.iloc[0]["session_id"] == "angry"


class TestClusterEfficiency:
    def _spans(self) -> pd.DataFrame:
        rows = []
        # cluster A: 3 asks, each trace has 6 spans (long route)
        for t in range(3):
            trace = f"a{t}"
            rows.append(span(len(rows), trace_id=trace, input_text="why break?",
                             session_id=f"sa{t}"))
            for _ in range(5):
                rows.append(span(len(rows), trace_id=trace, span_kind="TOOL", input_text=""))
        # cluster B: 3 asks, 1-span traces (short route)
        for t in range(3):
            rows.append(span(len(rows), trace_id=f"b{t}", input_text="what is plex?",
                             session_id=f"sb{t}"))
        return frame(rows)

    def _clusters(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"cluster_id": "ca", "representative": "why break?", "count": 3,
                 "total_cost_usd": 0.18, "avg_latency_ms": 3000.0},
                {"cluster_id": "cb", "representative": "what is plex?", "count": 3,
                 "total_cost_usd": 0.03, "avg_latency_ms": 3000.0},
            ]
        )

    def _members(self, spans_df: pd.DataFrame) -> pd.DataFrame:
        llm = spans_df[spans_df["input_text"] != ""]
        rows = [
            {"cluster_id": "ca" if "break" in r["input_text"] else "cb",
             "span_id": r["span_id"]}
            for _, r in llm.iterrows()
        ]
        return pd.DataFrame(rows)

    def test_route_length_and_long_route_flag(self) -> None:
        spans_df = self._spans()
        df = insights.cluster_efficiency(spans_df, self._clusters(), self._members(spans_df))

        ca = df[df["cluster_id"] == "ca"].iloc[0]
        cb = df[df["cluster_id"] == "cb"].iloc[0]
        assert ca["route_len_avg"] == 6.0
        assert cb["route_len_avg"] == 1.0
        assert bool(ca["long_route"]) is True
        assert bool(cb["long_route"]) is False
        assert ca["tokens_per_ask"] == 6 * 150

    def test_opportunity_ranked_first(self) -> None:
        spans_df = self._spans()
        df = insights.cluster_efficiency(spans_df, self._clusters(), self._members(spans_df))
        # cluster A burns 3 asks * 900 tokens; B burns 3 * 150 — A ranks first.
        assert df.iloc[0]["cluster_id"] == "ca"
        assert df.iloc[0]["opportunity_score"] >= df.iloc[1]["opportunity_score"]

    def test_empty_inputs(self) -> None:
        empty = frame([])
        assert insights.cluster_efficiency(empty, pd.DataFrame(), pd.DataFrame()).empty

    def test_duplicate_span_ids_do_not_crash(self) -> None:
        spans_df = self._spans()
        doubled = pd.concat([spans_df, spans_df.head(3)], ignore_index=True)
        df = insights.cluster_efficiency(doubled, self._clusters(), self._members(spans_df))
        assert not df.empty


class TestSkillHealth:
    def test_flags_skills_with_long_routes(self) -> None:
        efficiency = pd.DataFrame(
            [
                {"cluster_id": "ca", "representative": "why break?", "count": 2,
                 "route_len_avg": 6.0, "long_route": True, "tokens_per_ask": 900.0,
                 "error_rate": 0.0, "total_cost_usd": 0.12, "opportunity_score": 1800.0},
                {"cluster_id": "cb", "representative": "what is plex?", "count": 3,
                 "route_len_avg": 1.0, "long_route": False, "tokens_per_ask": 150.0,
                 "error_rate": 0.0, "total_cost_usd": 0.03, "opportunity_score": 450.0},
            ]
        )
        matches = pd.DataFrame(
            [
                {"cluster_id": "ca", "skill_name": "fobo-recon-breaks", "score": 0.8},
                {"cluster_id": "cb", "skill_name": "plex-glossary", "score": 0.9},
            ]
        )
        df = insights.skill_health(efficiency, matches)

        recon = df[df["skill_name"] == "fobo-recon-breaks"].iloc[0]
        plex = df[df["skill_name"] == "plex-glossary"].iloc[0]
        assert recon["status"] == "review"
        assert plex["status"] == "effective"
        assert recon["n_asks"] == 2

    def test_empty_matches(self) -> None:
        assert insights.skill_health(pd.DataFrame(), pd.DataFrame()).empty


class TestQuestionType:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Why is X broken?", "why"),
            ("what's the pnl?", "what"),
            ("HOW do I export?", "how"),
            ("When does flash run?", "when"),
            ("Where is the eod report?", "where"),
            ("Which book is off?", "which"),
            ("Who booked this adjustment?", "who"),
            ("Can you rerun the recon?", "check"),
            ("Is the adjustment booked?", "check"),
            ("Show me the breaks", "request"),
            ("export the report", "request"),
            ("Draft sign-off commentary for the credit desk", "request"),
            ("Suggest an adjustment for the missed accrual", "request"),
            ("the number looks wrong?", "other_question"),
            ("thanks", "other"),
        ],
    )
    def test_classification(self, text: str, expected: str) -> None:
        assert insights.question_type(text) == expected
