"""Run-history storage, the pipeline snapshot, and the coverage/trigger endpoints."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from phoenix_scraper import fixtures
from phoenix_scraper.api import create_app
from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.config import Settings
from phoenix_scraper.models import PromptCluster, SkillMatch
from phoenix_scraper.pipeline import run_analysis
from phoenix_scraper.storage import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


def cluster(cid: str, count: int = 5) -> PromptCluster:
    return PromptCluster(
        cluster_id=cid, signature=f"sig-{cid}", representative=f"prompt {cid}",
        count=count, n_users=2,
    )


class TestRunHistoryStorage:
    def test_records_and_reads_back_a_run(self, tmp_store: Store) -> None:
        when = datetime(2026, 8, 1, tzinfo=UTC)
        match = SkillMatch(cluster_id="a", skill_name="s", score=0.9)
        tmp_store.record_run(
            "r1", when, [cluster("a"), cluster("b")], [match], 42
        )
        runs = tmp_store.runs_frame()
        assert list(runs["run_id"]) == ["r1"]
        assert int(runs.iloc[0]["n_spans"]) == 42
        assert int(runs.iloc[0]["n_clusters"]) == 2

        snapshot = tmp_store.run_snapshot_frame("r1").set_index("cluster_id")
        assert set(snapshot.index) == {"a", "b"}
        assert snapshot.loc["a", "skill_name"] == "s"
        # An unmatched cluster stores SQL NULL, which pandas reads back as NaN.
        assert pd.isna(snapshot.loc["b", "skill_name"])

    def test_previous_run_id_walks_backwards(self, tmp_store: Store) -> None:
        base = datetime(2026, 8, 1, tzinfo=UTC)
        for i, name in enumerate(["r1", "r2", "r3"]):
            tmp_store.record_run(name, base + timedelta(days=i), [cluster("a")], [], 1)
        assert tmp_store.previous_run_id() == "r3"
        assert tmp_store.previous_run_id("r3") == "r2"
        assert tmp_store.previous_run_id("r2") == "r1"
        assert tmp_store.previous_run_id("r1") is None

    def test_no_runs_yet(self, tmp_store: Store) -> None:
        assert tmp_store.previous_run_id() is None
        assert tmp_store.run_snapshot_frame(None).empty
        assert tmp_store.runs_frame().empty

    def test_history_is_pruned(self, tmp_store: Store) -> None:
        base = datetime(2026, 8, 1, tzinfo=UTC)
        for i in range(8):
            tmp_store.record_run(
                f"r{i}", base + timedelta(days=i), [cluster("a")], [], 1, history_limit=3
            )
        runs = tmp_store.runs_frame()
        assert len(runs) == 3
        assert set(runs["run_id"]) == {"r5", "r6", "r7"}
        # Pruned runs take their snapshots with them.
        assert tmp_store.run_snapshot_frame("r0").empty

    def test_re_recording_a_run_replaces_its_snapshot(self, tmp_store: Store) -> None:
        when = datetime(2026, 8, 1, tzinfo=UTC)
        tmp_store.record_run("r1", when, [cluster("a"), cluster("b")], [], 1)
        tmp_store.record_run("r1", when, [cluster("c")], [], 1)
        assert set(tmp_store.run_snapshot_frame("r1")["cluster_id"]) == {"c"}


class TestPipelineSnapshots:
    def test_analysis_records_a_run(self, tmp_store: Store, settings: Settings) -> None:
        fixtures.seed_demo(tmp_store, n_sessions=15, seed=3)
        result = run_analysis(tmp_store, settings)
        assert result.run_id is not None
        assert result.previous_run_id is None  # nothing came before
        assert len(tmp_store.run_snapshot_frame(result.run_id)) == len(result.clusters)

    def test_second_run_points_at_the_first(
        self, tmp_store: Store, settings: Settings
    ) -> None:
        fixtures.seed_demo(tmp_store, n_sessions=15, seed=3)
        first = run_analysis(tmp_store, settings)
        second = run_analysis(tmp_store, settings)
        assert second.previous_run_id == first.run_id
        assert second.run_id != first.run_id

    def test_run_ids_are_unique_across_runs(
        self, tmp_store: Store, settings: Settings
    ) -> None:
        fixtures.seed_demo(tmp_store, n_sessions=10, seed=3)
        ids = {run_analysis(tmp_store, settings).run_id for _ in range(3)}
        assert len(ids) == 3


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    tmp = tmp_path_factory.mktemp("coverage_api")
    settings = Settings(
        _env_file=None,
        db_path=tmp / "api.db",
        export_dir=tmp / "exports",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        assert c.post("/demo/seed").status_code == 200
        yield c


class TestCoverageEndpoints:
    def test_coverage_reports_gaps(self, client: TestClient) -> None:
        rows = client.get("/skills/coverage").json()
        assert rows
        first = rows[0]
        assert {"skill_name", "source_file", "n_asks", "n_covered_asks",
                "n_uncovered_asks", "coverage"} <= set(first)
        # The seeded traffic includes drift phrasings the catalog doesn't show.
        assert any(r["n_uncovered_asks"] > 0 for r in rows)

    def test_coverage_never_exceeds_one(self, client: TestClient) -> None:
        for row in client.get("/skills/coverage").json():
            assert 0.0 <= row["coverage"] <= 1.0
            assert row["n_covered_asks"] + row["n_uncovered_asks"] == row["n_asks"]

    def test_uncovered_lists_the_questions(self, client: TestClient) -> None:
        rows = client.get("/skills/uncovered").json()
        assert rows
        assert all(r["representative"] for r in rows)
        assert all(r["coverage_score"] < 0.70 for r in rows)

    def test_updates_are_paste_ready(self, client: TestClient) -> None:
        rows = client.get("/skills/updates").json()
        assert rows
        first = rows[0]
        assert first["new_prompts"]
        assert "example_prompts:" in first["yaml_block"]
        assert first["source_file"].endswith(".yaml")

    def test_updates_markdown(self, client: TestClient) -> None:
        response = client.get("/skills/updates.md")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "# Skill updates" in response.text

    def test_updates_csv_flattens_the_lists(self, client: TestClient) -> None:
        response = client.get("/skills/updates", params={"fmt": "csv"})
        assert response.status_code == 200
        # A python list literal in a CSV cell would be unusable in a spreadsheet.
        assert "['" not in response.text

    def test_runs_are_listed(self, client: TestClient) -> None:
        rows = client.get("/runs").json()
        assert rows
        assert {"run_id", "generated_at", "n_spans", "n_clusters"} <= set(rows[0])

    def test_delta_is_empty_until_a_second_run(self, client: TestClient) -> None:
        # /demo/seed ran the analysis once; there is nothing to compare against.
        assert client.get("/runs/delta").json() == []


class TestTriggerEndpoints:
    def test_analyze_runs_and_reports(self, client: TestClient) -> None:
        body = client.post("/analyze/run").json()
        assert body["n_spans_analyzed"] > 0
        assert body["clusters"] > 0
        assert body["evaluations"] > 0
        assert body["run_id"]

    def test_analyze_twice_enables_the_delta(self, client: TestClient) -> None:
        client.post("/analyze/run")
        client.post("/analyze/run")
        rows = client.get("/runs/delta").json()
        assert rows
        assert {"status", "count", "count_prev", "count_change"} <= set(rows[0])
        # Same corpus analyzed twice: nothing should look new.
        assert all(r["status"] == "stable" for r in rows)

    def test_report_writes_both_documents(self, client: TestClient) -> None:
        body = client.post("/report/run").json()
        report = Path(body["report"])
        updates = Path(body["skill_updates"])
        assert report.exists() and updates.exists()
        assert "# Prompt Mining Report" in report.read_text(encoding="utf-8")
        assert "# Skill updates" in updates.read_text(encoding="utf-8")
        assert "Skill coverage gaps" in report.read_text(encoding="utf-8")

    def test_triggers_are_protected(self, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None,
            db_path=tmp_path / "auth.db",
            export_dir=tmp_path / "exports",
            skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
            pricing_path=REPO_ROOT / "config" / "pricing.yaml",
            api_key="s3cret",
        ).model_copy(update={"phoenix_endpoint": None})
        with TestClient(create_app(settings)) as c:
            for route in ("/analyze/run", "/report/run"):
                assert c.post(route).status_code == 401, route
            for route in ("/skills/coverage", "/skills/uncovered", "/skills/updates",
                          "/runs", "/runs/delta"):
                assert c.get(route).status_code == 401, route

    def test_triggers_reject_cross_origin(self, client: TestClient) -> None:
        for route in ("/analyze/run", "/report/run"):
            response = client.post(route, headers={"Origin": "http://evil.example"})
            assert response.status_code == 403, route


class TestCoverageCli:
    def _seeded(self, tmp_path: Path) -> Path:
        db = tmp_path / "cov.db"
        result = CliRunner().invoke(
            cli_app,
            ["demo", "--db", str(db), "--export-dir", str(tmp_path / "e"),
             "--sessions", "30"],
        )
        assert result.exit_code == 0, result.output
        return db

    def test_coverage_command_prints_gaps(self, tmp_path: Path) -> None:
        db = self._seeded(tmp_path)
        result = CliRunner().invoke(
            cli_app, ["coverage", "--db", str(db), "--export-dir", str(tmp_path / "e")]
        )
        assert result.exit_code == 0, result.output
        assert "Skill coverage" in result.output
        assert "Add to each file:" in result.output

    def test_write_flag_emits_the_markdown(self, tmp_path: Path) -> None:
        db = self._seeded(tmp_path)
        out = tmp_path / "e"
        result = CliRunner().invoke(
            cli_app,
            ["coverage", "--db", str(db), "--export-dir", str(out), "--write"],
        )
        assert result.exit_code == 0, result.output
        written = out / "skill_updates.md"
        assert written.exists()
        assert "# Skill updates" in written.read_text(encoding="utf-8")

    def test_coverage_on_an_empty_store(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli_app, ["coverage", "--db", str(tmp_path / "empty.db")]
        )
        assert result.exit_code == 0, result.output
        assert "No matched skills yet" in result.output

    def test_report_writes_the_updates_file(self, tmp_path: Path) -> None:
        db = self._seeded(tmp_path)
        out = tmp_path / "rep"
        result = CliRunner().invoke(
            cli_app, ["report", "--db", str(db), "--export-dir", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert (out / "report.md").exists()
        assert (out / "skill_updates.md").exists()

    @pytest.mark.parametrize("what", ["coverage", "uncovered"])
    def test_export_targets(self, tmp_path: Path, what: str) -> None:
        db = self._seeded(tmp_path)
        out = tmp_path / "exp"
        result = CliRunner().invoke(
            cli_app,
            ["export", "--what", what, "--fmt", "csv", "--db", str(db),
             "--export-dir", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert (out / f"{what}.csv").exists()
