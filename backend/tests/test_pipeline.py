"""End-to-end tests for pipeline.run_analysis plus a CLI demo smoke test."""

from datetime import UTC
from pathlib import Path

import pytest
from typer.testing import CliRunner

from phoenix_scraper import fixtures
from phoenix_scraper.config import Settings
from phoenix_scraper.models import AnalysisResult, QueryFilters
from phoenix_scraper.pipeline import run_analysis
from phoenix_scraper.storage import Store


@pytest.fixture()
def demo_store(tmp_store: Store) -> Store:
    fixtures.seed_demo(tmp_store)
    return tmp_store


def test_run_analysis_empty_store(tmp_store: Store, settings: Settings) -> None:
    result = run_analysis(tmp_store, settings)
    assert isinstance(result, AnalysisResult)
    assert result.clusters == ()
    assert result.matches == ()
    assert result.proposals == ()
    assert result.sessions == ()
    assert result.n_spans_analyzed == 0
    assert result.generated_at is not None
    assert result.generated_at.tzinfo is not None


def test_run_analysis_end_to_end(demo_store: Store, settings: Settings) -> None:
    result = run_analysis(demo_store, settings)

    assert result.n_spans_analyzed > 0
    assert result.clusters
    # Clusters are sorted by count desc and the hot templates repeat often.
    assert result.clusters[0].count > 5
    hot = [c for c in result.clusters if c.count > 5]
    assert len(hot) >= 3

    assert result.matches, "catalog skills should match some frequent prompts"
    assert result.proposals, "uncovered frequent prompts should yield gap proposals"
    assert result.sessions
    assert len(result.sessions) == 60

    assert result.generated_at is not None
    assert result.generated_at.utcoffset() == UTC.utcoffset(None)

    matched_ids = {m.cluster_id for m in result.matches}
    proposed_ids = {p.cluster_id for p in result.proposals}
    assert not matched_ids & proposed_ids, "a cluster is either matched or proposed"


def test_run_analysis_persists_costs(demo_store: Store, settings: Settings) -> None:
    before = demo_store.spans_frame(QueryFilters(span_kinds=("LLM",), limit=10_000))
    assert before["cost_usd"].isna().all()

    run_analysis(demo_store, settings)

    after = demo_store.spans_frame(QueryFilters(span_kinds=("LLM",), limit=10_000))
    assert after["cost_usd"].notna().all()
    assert (after["cost_usd"] > 0).all()


def test_run_analysis_persists_results(demo_store: Store, settings: Settings) -> None:
    result = run_analysis(demo_store, settings)

    assert len(demo_store.clusters_frame(limit=10_000)) == len(result.clusters)
    assert len(demo_store.matches_frame()) == len(result.matches)
    assert len(demo_store.proposals_frame()) == len(result.proposals)
    assert len(demo_store.sessions_frame()) == len(result.sessions)


def test_run_analysis_rerun_replaces_wholesale(demo_store: Store, settings: Settings) -> None:
    first = run_analysis(demo_store, settings)
    second = run_analysis(demo_store, settings)

    assert len(second.clusters) == len(first.clusters)
    assert len(demo_store.clusters_frame(limit=10_000)) == len(second.clusters)
    assert len(demo_store.matches_frame()) == len(second.matches)


def test_run_analysis_respects_filters(demo_store: Store, settings: Settings) -> None:
    filters = QueryFilters(asset_class="fx", limit=100_000)
    result = run_analysis(demo_store, settings, filters=filters)
    assert result.n_spans_analyzed > 0
    for c in result.clusters:
        assert c.asset_classes == ("fx",)


def test_cli_demo_smoke(tmp_path: Path) -> None:
    from phoenix_scraper.cli import app as cli_app

    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        [
            "demo",
            "--db", str(tmp_path / "cli.db"),
            "--export-dir", str(tmp_path / "exports"),
            "--sessions", "20",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "exports" / "report.md").exists()
    assert "Top prompts" in result.output
    assert str(tmp_path / "cli.db") in result.output
