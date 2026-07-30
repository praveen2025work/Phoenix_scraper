"""Tests for prompt clustering: grouping, fuzzy merge, aggregation, determinism."""

import hashlib
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from phoenix_scraper.cluster import build_clusters
from phoenix_scraper.models import PromptCluster
from phoenix_scraper.storage import Store

BASE_TS = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)


def make_frame(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "span_id": "span-x",
        "session_id": "sess-0",
        "user_id": "analyst-0",
        "input_text": "",
        "cost_usd": None,
        "latency_ms": None,
        "start_time": BASE_TS,
        "workflow_stage": None,
        "asset_class": None,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


class TestEmptyInput:
    def test_empty_dataframe(self) -> None:
        assert build_clusters(pd.DataFrame()) == []

    def test_rows_with_empty_prompts_are_dropped(self) -> None:
        df = make_frame(
            [
                {"span_id": "s1", "input_text": ""},
                {"span_id": "s2", "input_text": "   "},
            ]
        )
        assert build_clusters(df) == []


class TestGroupingAndFrequency:
    def test_variant_prompts_form_one_cluster_with_counts(
        self, seeded_store: Store
    ) -> None:
        df = seeded_store.spans_frame()
        clusters = build_clusters(df)

        # 8 recon variants collapse into one cluster; commentary is separate;
        # the TOOL span with empty input_text is dropped.
        assert len(clusters) == 2
        recon, commentary = clusters
        assert recon.count == 8
        assert commentary.count == 1
        assert "recon break" in recon.signature
        assert "<num>" in recon.signature
        assert "<ccy>" in recon.signature
        assert "commentary" in commentary.signature

    def test_sorted_by_count_desc(self) -> None:
        rows = [
            {"span_id": f"a{i}", "input_text": f"Why is the FX break {i}k?"}
            for i in range(3)
        ] + [{"span_id": "b0", "input_text": "Draft the rates desk commentary"}]
        clusters = build_clusters(make_frame(rows))
        counts = [c.count for c in clusters]
        assert counts == sorted(counts, reverse=True)
        assert clusters[0].count == 3

    def test_distinct_intents_stay_separate(self) -> None:
        df = make_frame(
            [
                {
                    "span_id": "s1",
                    "input_text": "Why is there an FX recon break of 100k on EURUSD?",
                },
                {"span_id": "s2", "input_text": "Draft sign-off commentary for the rates desk"},
            ]
        )
        assert len(build_clusters(df)) == 2


class TestRepresentativeSelection:
    def test_most_frequent_raw_text_wins(self) -> None:
        df = make_frame(
            [
                {"span_id": "s1", "input_text": "Show FX breaks over 100k"},
                {"span_id": "s2", "input_text": "Show FX breaks over 100k"},
                {"span_id": "s3", "input_text": "show fx breaks over 250k"},
            ]
        )
        clusters = build_clusters(df)
        assert len(clusters) == 1
        assert clusters[0].representative == "Show FX breaks over 100k"


class TestAggregation:
    def test_cross_session_and_user_aggregation(self) -> None:
        df = make_frame(
            [
                {
                    "span_id": "s1",
                    "session_id": "sess-a",
                    "user_id": "u1",
                    "input_text": "Why is there a recon break of 100k?",
                    "cost_usd": 0.10,
                    "latency_ms": 1000.0,
                    "start_time": BASE_TS,
                    "workflow_stage": "fobo_recon",
                    "asset_class": "fx",
                },
                {
                    "span_id": "s2",
                    "session_id": "sess-b",
                    "user_id": "u2",
                    "input_text": "Why is there a recon break of 250k?",
                    "cost_usd": 0.30,
                    "latency_ms": 3000.0,
                    "start_time": BASE_TS + timedelta(hours=1),
                    "workflow_stage": "fobo_recon",
                    "asset_class": "rates",
                },
                {
                    "span_id": "s3",
                    "session_id": "sess-b",
                    "user_id": "u1",
                    "input_text": "why is there a recon break of 999k ?",
                    "cost_usd": None,
                    "latency_ms": None,
                    "start_time": BASE_TS + timedelta(hours=2),
                    "workflow_stage": None,
                    "asset_class": "fx",
                },
            ]
        )
        clusters = build_clusters(df)
        assert len(clusters) == 1
        c = clusters[0]
        assert c.count == 3
        assert c.n_sessions == 2
        assert c.n_users == 2
        assert c.total_cost_usd == pytest.approx(0.40)
        assert c.avg_latency_ms == pytest.approx(2000.0)
        assert c.first_seen == BASE_TS
        assert c.last_seen == BASE_TS + timedelta(hours=2)
        assert set(c.span_ids) == {"s1", "s2", "s3"}
        assert c.asset_classes == ("fx", "rates")
        assert c.workflow_stages == ("fobo_recon",)

    def test_all_null_latency_gives_none(self) -> None:
        df = make_frame([{"span_id": "s1", "input_text": "hello there"}])
        assert build_clusters(df)[0].avg_latency_ms is None


class TestFuzzyMerge:
    def test_near_identical_signatures_merge(self) -> None:
        # Same token set in a different order + one filler word: token_set_ratio 100.
        rows = [
            {"span_id": f"a{i}", "input_text": "Show me the recon breaks for the fx desk"}
            for i in range(3)
        ] + [{"span_id": "b0", "input_text": "Show me the fx desk recon breaks"}]
        clusters = build_clusters(make_frame(rows))
        assert len(clusters) == 1
        assert clusters[0].count == 4
        # Canonical signature comes from the larger group (desk mentions masked).
        assert clusters[0].signature == "show me the recon breaks for the <desk> desk"

    def test_high_threshold_keeps_dissimilar_apart(self) -> None:
        df = make_frame(
            [
                {"span_id": "s1", "input_text": "Why is there an FX recon break?"},
                {"span_id": "s2", "input_text": "Post an adjustment for the equities desk"},
            ]
        )
        assert len(build_clusters(df, fuzz_threshold=90)) == 2


class TestDeterminism:
    def test_cluster_id_is_sha1_of_signature(self) -> None:
        df = make_frame([{"span_id": "s1", "input_text": "Why is there an FX break of 5k?"}])
        c = build_clusters(df)[0]
        expected = hashlib.sha1(c.signature.encode()).hexdigest()[:12]
        assert c.cluster_id == expected

    def test_repeated_runs_are_identical(self, seeded_store: Store) -> None:
        df = seeded_store.spans_frame()
        first = build_clusters(df)
        second = build_clusters(df)
        assert [c.cluster_id for c in first] == [c.cluster_id for c in second]
        assert first == second

    def test_input_dataframe_is_not_mutated(self) -> None:
        df = make_frame([{"span_id": "s1", "input_text": "Why is there an FX break of 5k?"}])
        before = df.copy(deep=True)
        build_clusters(df)
        pd.testing.assert_frame_equal(df, before)

    def test_returns_prompt_cluster_models(self) -> None:
        df = make_frame([{"span_id": "s1", "input_text": "hello world"}])
        assert all(isinstance(c, PromptCluster) for c in build_clusters(df))
