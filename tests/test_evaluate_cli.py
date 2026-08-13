"""Tests for the `pheonix evaluate` command, its storage, and pipeline wiring."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from phoenix_scraper import evaluations as evaluations_mod
from phoenix_scraper import fixtures
from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.config import Settings
from phoenix_scraper.models import QueryFilters, SpanEvaluation
from phoenix_scraper.pipeline import run_analysis
from phoenix_scraper.storage import Store


@pytest.fixture()
def demo_store(tmp_store: Store) -> Store:
    fixtures.seed_demo(tmp_store, n_sessions=20, seed=7)
    return tmp_store


class TestStorage:
    def test_replace_local_swaps_the_set(self, tmp_store: Store) -> None:
        tmp_store.replace_local_evaluations([
            SpanEvaluation(span_id="s1", name="a", label="x", score=0.0),
            SpanEvaluation(span_id="s1", name="b", label="y", score=1.0),
        ])
        assert tmp_store.replace_local_evaluations(
            [SpanEvaluation(span_id="s1", name="c", label="z", score=0.5)]
        ) == 1
        # The join drops rows without a span, so read the table directly here.
        names = tmp_store._conn.execute(
            "SELECT name FROM span_evaluations ORDER BY name"
        ).fetchall()
        assert [r[0] for r in names] == ["c"]

    def test_upsert_is_idempotent(self, tmp_store: Store) -> None:
        evaluation = SpanEvaluation(
            span_id="s1", name="correctness", label="ok", score=1.0, source="phoenix"
        )
        assert tmp_store.upsert_evaluations([evaluation]) == 1
        assert tmp_store.upsert_evaluations([evaluation]) == 0

    def test_same_name_from_two_sources_coexists(self, tmp_store: Store) -> None:
        tmp_store.upsert_evaluations([
            SpanEvaluation(span_id="s1", name="correctness", score=1.0, source="local"),
            SpanEvaluation(span_id="s1", name="correctness", score=0.0, source="phoenix"),
        ])
        rows = tmp_store._conn.execute(
            "SELECT COUNT(*) FROM span_evaluations"
        ).fetchone()[0]
        assert rows == 2

    def test_frame_joins_span_dimensions(self, demo_store: Store, settings: Settings) -> None:
        run_analysis(demo_store, settings)
        df = demo_store.evaluations_frame(QueryFilters(limit=100_000))
        assert not df.empty
        assert {"user_id", "model_name", "workflow_stage", "input_text",
                "output_text"} <= set(df.columns)
        assert df["user_id"].notna().any()

    def test_frame_drops_evaluations_without_a_span(self, tmp_store: Store) -> None:
        tmp_store.upsert_evaluations(
            [SpanEvaluation(span_id="ghost", name="a", score=0.0)]
        )
        assert tmp_store.evaluations_frame(QueryFilters(limit=100)).empty

    def test_frame_honours_every_filter(self, demo_store: Store, settings: Settings) -> None:
        run_analysis(demo_store, settings)
        everyone = demo_store.evaluations_frame(QueryFilters(limit=100_000))
        for filters in (
            QueryFilters(user_id="analyst-priya", limit=100_000),
            QueryFilters(asset_class="fx", limit=100_000),
            QueryFilters(workflow_stage="plex", limit=100_000),
            QueryFilters(span_kinds=("LLM",), limit=100_000),
        ):
            scoped = demo_store.evaluations_frame(filters)
            assert 0 < len(scoped) < len(everyone)


class TestPipelineWiring:
    def test_analysis_validates_by_default(
        self, demo_store: Store, settings: Settings
    ) -> None:
        result = run_analysis(demo_store, settings)
        assert result.evaluations
        assert len(demo_store.evaluations_frame(QueryFilters(limit=100_000))) == len(
            result.evaluations
        )

    def test_validation_can_be_switched_off(
        self, demo_store: Store, settings: Settings
    ) -> None:
        quiet = settings.model_copy(update={"evaluate_on_analyze": False})
        result = run_analysis(demo_store, quiet)
        assert result.evaluations == ()
        assert demo_store.evaluations_frame(QueryFilters(limit=100)).empty

    def test_rerun_replaces_rather_than_accumulates(
        self, demo_store: Store, settings: Settings
    ) -> None:
        first = run_analysis(demo_store, settings)
        run_analysis(demo_store, settings)
        assert len(demo_store.evaluations_frame(QueryFilters(limit=100_000))) == len(
            first.evaluations
        )

    def test_empty_store_yields_no_evaluations(
        self, tmp_store: Store, settings: Settings
    ) -> None:
        assert run_analysis(tmp_store, settings).evaluations == ()


class TestCli:
    def _seeded_db(self, tmp_path: Path) -> Path:
        db = tmp_path / "cli.db"
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            ["demo", "--db", str(db), "--export-dir", str(tmp_path / "e"),
             "--sessions", "20"],
        )
        assert result.exit_code == 0, result.output
        return db

    def test_evaluate_prints_the_scoreboard(self, tmp_path: Path) -> None:
        db = self._seeded_db(tmp_path)
        result = CliRunner().invoke(cli_app, ["evaluate", "--db", str(db)])

        assert result.exit_code == 0, result.output
        assert "Validated" in result.output
        assert "output issues" in result.output
        # The breakdown must name the checks that failed. Which ones appear at a
        # small sample size is a property of the fixture RNG, not of the CLI, so
        # assert on the shape rather than pinning one check name.
        assert "check" in result.output and "target" in result.output
        named = {name for name, _ in evaluations_mod.check_names()}
        assert named & set(result.output.split()), result.output

    def test_evaluate_on_an_empty_store(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli_app, ["evaluate", "--db", str(tmp_path / "empty.db")]
        )
        assert result.exit_code == 0, result.output
        assert "No spans to validate" in result.output

    def test_evaluate_respects_a_user_filter(self, tmp_path: Path) -> None:
        db = self._seeded_db(tmp_path)
        scoped = CliRunner().invoke(
            cli_app, ["evaluate", "--db", str(db), "--user", "analyst-priya"]
        )
        assert scoped.exit_code == 0, scoped.output
        assert "Validated" in scoped.output

    def test_analyze_reports_validation(self, tmp_path: Path) -> None:
        db = self._seeded_db(tmp_path)
        result = CliRunner().invoke(cli_app, ["analyze", "--db", str(db)])
        assert result.exit_code == 0, result.output
        assert "Validation:" in result.output

    def test_pull_annotations_without_phoenix_exits_cleanly(self, tmp_path: Path) -> None:
        db = self._seeded_db(tmp_path)
        result = CliRunner().invoke(
            cli_app, ["evaluate", "--db", str(db), "--pull-annotations"]
        )
        assert result.exit_code == 1
        assert "Phoenix is not available" in result.output

    def test_export_evaluations(self, tmp_path: Path) -> None:
        db = self._seeded_db(tmp_path)
        out = tmp_path / "exports"
        result = CliRunner().invoke(
            cli_app,
            ["export", "--what", "evaluations", "--fmt", "csv",
             "--db", str(db), "--export-dir", str(out)],
        )
        assert result.exit_code == 0, result.output
        exported = out / "evaluations.csv"
        assert exported.exists()
        assert "output_refusal" in exported.read_text(encoding="utf-8")


class TestFixturesSeedFailures:
    """The demo must show a believable quality picture, not a perfect one."""

    def test_seeded_traffic_contains_every_failure_mode(
        self, demo_store: Store, settings: Settings
    ) -> None:
        run_analysis(demo_store, settings)
        df = demo_store.evaluations_frame(QueryFilters(limit=100_000))
        failed = set(df.loc[df["score"] < 0.5, "name"])
        assert {"output_refusal", "output_empty", "output_truncated",
                "prompt_injection", "prompt_pii"} <= failed

    def test_most_spans_still_pass(self, demo_store: Store, settings: Settings) -> None:
        # A demo where everything fails is as useless as one where nothing does.
        run_analysis(demo_store, settings)
        df = demo_store.evaluations_frame(QueryFilters(limit=100_000))
        n_spans = df["span_id"].nunique()
        n_failed = df.loc[df["score"] < 0.5, "span_id"].nunique()
        assert 0 < n_failed < n_spans * 0.35

    def test_seeding_is_deterministic(self, tmp_path: Path) -> None:
        results = []
        for name in ("a", "b"):
            store = Store(tmp_path / f"{name}.db")
            fixtures.seed_demo(store, n_sessions=20, seed=7)
            settings = Settings(_env_file=None, db_path=tmp_path / f"{name}.db")
            results.append(len(run_analysis(store, settings).evaluations))
            store.close()
        assert results[0] == results[1]
