"""Tests for the quality rollups over span evaluations."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from phoenix_scraper import insights_quality

BASE_TS = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)

_COLUMNS = [
    "span_id", "name", "source", "label", "score", "explanation", "annotator_kind",
    "target", "created_at", "trace_id", "session_id", "project", "user_id",
    "model_name", "workflow_stage", "asset_class", "span_kind", "status_code",
    "start_time", "latency_ms", "tokens_total", "cost_usd", "input_text",
    "output_text",
]


def row(span_id: str, name: str, score: float | None, **overrides) -> dict:
    base = {
        "span_id": span_id,
        "name": name,
        "source": "local",
        "label": "fail" if (score is not None and score < 0.5) else "pass",
        "score": score,
        "explanation": f"{name} said so",
        "annotator_kind": "CODE",
        "target": "output",
        "created_at": BASE_TS.isoformat(),
        "trace_id": "t1",
        "session_id": "sess-1",
        "project": "pnl-agent",
        "user_id": "alice",
        "model_name": "sonnet",
        "workflow_stage": "fobo_recon",
        "asset_class": "fx",
        "span_kind": "LLM",
        "status_code": "OK",
        "start_time": BASE_TS,
        "latency_ms": 1000.0,
        "tokens_total": 150,
        "cost_usd": 0.01,
        "input_text": "why is there a break?",
        "output_text": "an unsettled trade",
    }
    base.update(overrides)
    return base


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


class TestPassFlag:
    def test_low_scores_fail(self) -> None:
        df = insights_quality.with_pass_flag(frame([row("s1", "c", 0.0)]))
        assert not df["passed"].iloc[0]

    def test_unscored_annotations_pass(self) -> None:
        # A human "note" annotation carries no score; it must not invent a failure.
        df = insights_quality.with_pass_flag(frame([row("s1", "note", None)]))
        assert df["passed"].iloc[0]

    def test_empty_frame_gets_the_column(self) -> None:
        assert "passed" in insights_quality.with_pass_flag(frame([])).columns


class TestQualitySummary:
    def test_per_check_counts_and_rates(self) -> None:
        rows = [
            row("s1", "output_refusal", 0.0),
            row("s2", "output_refusal", 1.0),
            row("s3", "output_refusal", 1.0),
            row("s1", "output_empty", 1.0),
        ]
        df = insights_quality.quality_summary(frame(rows))
        refusal = df[df["check"] == "output_refusal"].iloc[0]
        assert refusal["n_evaluated"] == 3
        assert refusal["n_failed"] == 1
        assert refusal["fail_rate"] == pytest.approx(1 / 3)
        assert refusal["avg_score"] == pytest.approx(2 / 3)
        assert refusal["target"] == "output"
        assert refusal["annotator_kind"] == "CODE"
        assert refusal["example"]

    def test_sorted_by_failures(self) -> None:
        rows = [row("s1", "rare", 0.0)] + [
            row(f"s{i}", "common", 0.0) for i in range(2, 6)
        ]
        df = insights_quality.quality_summary(frame(rows))
        assert df.iloc[0]["check"] == "common"

    def test_local_and_phoenix_checks_are_reported_separately(self) -> None:
        # A Phoenix eval named the same as a local check is a different judgement.
        rows = [
            row("s1", "correctness", 0.0, source="phoenix", annotator_kind="HUMAN"),
            row("s1", "correctness", 1.0, source="local"),
        ]
        df = insights_quality.quality_summary(frame(rows))
        assert len(df) == 2
        assert set(df["source"]) == {"local", "phoenix"}

    def test_counts_distinct_users_and_sessions_affected(self) -> None:
        rows = [
            row("s1", "c", 0.0, user_id="alice", session_id="a"),
            row("s2", "c", 0.0, user_id="bob", session_id="b"),
            row("s3", "c", 0.0, user_id="alice", session_id="a"),
        ]
        summary = insights_quality.quality_summary(frame(rows)).iloc[0]
        assert summary["n_users_affected"] == 2
        assert summary["n_sessions_affected"] == 2

    def test_empty(self) -> None:
        assert insights_quality.quality_summary(frame([])).empty


class TestQualityByDimension:
    def _rows(self) -> list[dict]:
        return [
            row("s1", "output_refusal", 0.0, user_id="alice"),
            row("s1", "prompt_pii", 0.0, user_id="alice", target="prompt"),
            row("s2", "output_refusal", 1.0, user_id="alice"),
            row("s3", "output_refusal", 1.0, user_id="bob"),
        ]

    def test_groups_by_user(self) -> None:
        df = insights_quality.quality_by_dimension(frame(self._rows()), "user_id")
        alice = df[df["user_id"] == "alice"].iloc[0]
        assert alice["n_spans"] == 2
        assert alice["n_failed"] == 2
        assert alice["n_spans_failed"] == 1
        assert alice["n_output_issues"] == 1
        assert alice["n_prompt_issues"] == 1
        assert "output_refusal" in alice["top_issues"]
        bob = df[df["user_id"] == "bob"].iloc[0]
        assert bob["n_failed"] == 0

    def test_groups_by_model(self) -> None:
        rows = [
            row("s1", "c", 0.0, model_name="haiku"),
            row("s2", "c", 1.0, model_name="sonnet"),
        ]
        df = insights_quality.quality_by_dimension(frame(rows), "model_name")
        assert df.iloc[0]["model_name"] == "haiku"
        assert df.iloc[0]["fail_rate"] == 1.0

    def test_missing_dimension_values_are_labelled(self) -> None:
        df = insights_quality.quality_by_dimension(
            frame([row("s1", "c", 0.0, user_id=None)]), "user_id"
        )
        assert df.iloc[0]["user_id"] == "(unattributed)"

    def test_unknown_column_returns_empty(self) -> None:
        assert insights_quality.quality_by_dimension(
            frame([row("s1", "c", 0.0)]), "nope"
        ).empty


class TestFailingSpans:
    def test_one_row_per_failing_span_with_evidence(self) -> None:
        rows = [
            row("s1", "output_refusal", 0.0),
            row("s1", "answer_relevance", 0.2),
            row("s2", "output_refusal", 1.0),
        ]
        df = insights_quality.failing_spans(frame(rows))
        assert list(df["span_id"]) == ["s1"]
        first = df.iloc[0]
        assert first["n_failed_checks"] == 2
        assert first["failed_checks"] == "answer_relevance, output_refusal"
        assert first["worst_score"] == pytest.approx(0.0)
        assert "output_refusal said so" in first["explanations"]
        assert first["input_text"] == "why is there a break?"

    def test_sorted_by_failure_count(self) -> None:
        rows = [
            row("s1", "a", 0.0),
            row("s2", "a", 0.0),
            row("s2", "b", 0.0),
        ]
        df = insights_quality.failing_spans(frame(rows))
        assert df.iloc[0]["span_id"] == "s2"

    def test_limit_is_honoured(self) -> None:
        rows = [row(f"s{i}", "a", 0.0) for i in range(10)]
        assert len(insights_quality.failing_spans(frame(rows), limit=3)) == 3

    def test_no_failures(self) -> None:
        assert insights_quality.failing_spans(frame([row("s1", "a", 1.0)])).empty

    def test_empty(self) -> None:
        assert insights_quality.failing_spans(frame([])).empty


class TestQualityByCluster:
    def _clusters(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"cluster_id": "c1", "representative": "why is there a break?", "count": 10},
            {"cluster_id": "c2", "representative": "draft commentary", "count": 4},
        ])

    def _members(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"cluster_id": "c1", "span_id": "s1"},
            {"cluster_id": "c1", "span_id": "s2"},
            {"cluster_id": "c2", "span_id": "s3"},
        ])

    def test_links_failures_to_prompt_patterns(self) -> None:
        rows = [
            row("s1", "output_refusal", 0.0, user_id="alice"),
            row("s2", "output_refusal", 0.0, user_id="bob"),
            row("s3", "output_refusal", 1.0, user_id="alice"),
        ]
        df = insights_quality.quality_by_cluster(
            frame(rows), self._clusters(), self._members()
        )
        c1 = df[df["cluster_id"] == "c1"].iloc[0]
        assert c1["representative"] == "why is there a break?"
        assert c1["count"] == 10
        assert c1["n_spans_failed"] == 2
        assert c1["span_fail_rate"] == pytest.approx(1.0)
        assert c1["n_users_affected"] == 2
        assert "output_refusal" in c1["top_issues"]

    def test_worst_pattern_ranks_first(self) -> None:
        rows = [
            row("s1", "a", 0.0, user_id="alice"),
            row("s2", "a", 0.0, user_id="bob"),
            row("s3", "a", 0.0, user_id="alice"),
        ]
        df = insights_quality.quality_by_cluster(
            frame(rows), self._clusters(), self._members()
        )
        assert df.iloc[0]["cluster_id"] == "c1"

    def test_unknown_clusters_are_ignored(self) -> None:
        members = pd.DataFrame([{"cluster_id": "ghost", "span_id": "s1"}])
        df = insights_quality.quality_by_cluster(
            frame([row("s1", "a", 0.0)]), self._clusters(), members
        )
        assert df.empty

    def test_empty_inputs(self) -> None:
        empty = pd.DataFrame()
        assert insights_quality.quality_by_cluster(frame([]), empty, empty).empty


class TestQualityOverview:
    def test_headline_numbers(self) -> None:
        rows = [
            row("s1", "output_refusal", 0.0),
            row("s1", "prompt_pii", 0.0, target="prompt"),
            row("s2", "output_refusal", 1.0),
        ]
        overview = insights_quality.quality_overview(frame(rows))
        assert overview["n_evaluated_spans"] == 2
        assert overview["n_checks"] == 3
        assert overview["n_failed_checks"] == 2
        assert overview["n_failed_spans"] == 1
        assert overview["span_pass_rate"] == pytest.approx(0.5)
        assert overview["n_prompt_issues"] == 1
        assert overview["n_output_issues"] == 1
        assert overview["sources"] == ["local"]
        assert overview["annotator_kinds"] == ["CODE"]

    def test_empty(self) -> None:
        overview = insights_quality.quality_overview(frame([]))
        assert overview["n_evaluated_spans"] == 0
        assert overview["span_pass_rate"] is None


class TestStoreIntegration:
    """The rollups must work against the real Store schema, not just a hand frame."""

    def test_end_to_end_from_seeded_store(self, tmp_path) -> None:
        from phoenix_scraper.config import Settings
        from phoenix_scraper.fixtures import seed_demo
        from phoenix_scraper.models import QueryFilters
        from phoenix_scraper.pipeline import run_analysis
        from phoenix_scraper.storage import Store

        settings = Settings(_env_file=None, db_path=tmp_path / "q.db")
        store = Store(settings.db_path)
        seed_demo(store, n_sessions=20, seed=7)
        run_analysis(store, settings)

        evals = store.evaluations_frame(QueryFilters(limit=100_000))
        assert not evals.empty
        summary = insights_quality.quality_summary(evals)
        assert not summary.empty
        # The seeded traffic deliberately contains refusals, truncation and PII.
        assert summary["n_failed"].sum() > 0
        assert insights_quality.quality_overview(evals)["n_evaluated_spans"] > 0
        by_user = insights_quality.quality_by_dimension(evals, "user_id")
        assert not by_user.empty
        by_cluster = insights_quality.quality_by_cluster(
            evals, store.clusters_frame(limit=1000), store.cluster_members_frame()
        )
        assert not by_cluster.empty
        store.close()

    def test_filters_scope_the_rollup(self, tmp_path) -> None:
        from phoenix_scraper.config import Settings
        from phoenix_scraper.fixtures import seed_demo
        from phoenix_scraper.models import QueryFilters
        from phoenix_scraper.pipeline import run_analysis
        from phoenix_scraper.storage import Store

        settings = Settings(_env_file=None, db_path=tmp_path / "q2.db")
        store = Store(settings.db_path)
        seed_demo(store, n_sessions=20, seed=7)
        run_analysis(store, settings)

        everyone = store.evaluations_frame(QueryFilters(limit=100_000))
        one_user = store.evaluations_frame(
            QueryFilters(user_id="analyst-priya", limit=100_000)
        )
        assert 0 < len(one_user) < len(everyone)
        assert set(one_user["user_id"]) == {"analyst-priya"}
        store.close()
