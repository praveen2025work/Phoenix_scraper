"""Analytics snapshot: written on run finish, served by dedicated endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings
from phoenix_scraper.models import CapabilityRun
from phoenix_scraper.storage import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        db_path=tmp_path / "api.db",
        export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        c.post("/demo/seed")
        c.post(
            "/capabilities",
            json={"id": "plex", "name": "PLEX", "filter": {"workflow_stage": "plex"}},
        )
        yield c


class TestAnalyticsSnapshotOnRun:
    def test_run_writes_snapshot_and_endpoint_returns_it(self, client: TestClient) -> None:
        run = client.post("/capabilities/plex/runs", json={}).json()
        assert run["analytics_ready"] is True
        run_id = run["run_id"]

        r = client.get(f"/capabilities/plex/runs/{run_id}/analytics")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["capability_id"] == "plex"
        assert body["run_id"] == run_id
        panels = body["panels"]
        assert "overview" in panels and "quality_overview" in panels
        assert "activity" in panels and "skills_coverage" in panels
        assert panels["overview"]["n_spans"] > 0

        summary = client.get("/capabilities/plex").json()["summary"]
        assert summary["last_run"]["analytics_ready"] is True
        assert "analytics_snapshot_json" not in summary["last_run"]

        hist = client.get("/capabilities/plex/runs").json()
        assert hist[0]["analytics_ready"] is True
        assert "analytics_snapshot_json" not in hist[0]

    def test_missing_snapshot_is_404(self, client: TestClient, tmp_path: Path) -> None:
        # A failed run recorded without analysis leaves no snapshot.
        db = tmp_path / "api.db"
        with Store(db) as store:
            from datetime import UTC, datetime

            now = datetime(2026, 9, 10, tzinfo=UTC)
            store.record_capability_run(
                CapabilityRun(
                    run_id="2026-09-10T00:00:00+00:00",
                    capability_id="plex",
                    started_at=now,
                    finished_at=now,
                    window_start=now,
                    window_end=now,
                    status="failed",
                    notes=("analysis failed: boom",),
                ),
                [],
                [],
                history_limit=20,
            )

        r = client.get("/capabilities/plex/runs/2026-09-10T00:00:00+00:00/analytics")
        assert r.status_code == 404
        assert "not ready" in r.json()["detail"].lower()

        # Capability summary still surfaces analytics_ready=false for that last run.
        # (May not be last if other runs exist — force by checking the run detail.)
        one = client.get("/capabilities/plex/runs/2026-09-10T00:00:00+00:00").json()
        assert one["analytics_ready"] is False

    def test_unknown_run_is_404(self, client: TestClient) -> None:
        assert (
            client.get("/capabilities/plex/runs/no-such-run/analytics").status_code
            == 404
        )


def test_empty_overview_has_full_schema() -> None:
    import pandas as pd

    from phoenix_scraper.analytics_snapshot import _overview

    empty = _overview(pd.DataFrame(), n_clusters=0, n_matches=0, n_proposals=0)
    full_keys = {
        "n_spans", "n_traces", "n_sessions", "n_users", "total_tokens",
        "total_cost_usd", "error_rate", "avg_latency_ms", "first_span",
        "last_span", "n_clusters", "n_matches", "n_proposals",
    }
    assert set(empty) == full_keys
    assert empty["n_spans"] == 0
    assert empty["avg_latency_ms"] is None


def test_empty_dict_snapshot_is_not_ready(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from phoenix_scraper.api_capabilities import _run_summary

    db = tmp_path / "ready.db"
    with Store(db) as store:
        now = datetime(2026, 9, 10, tzinfo=UTC)
        store.record_capability_run(
            CapabilityRun(
                run_id="2026-09-10T00:00:00+00:00",
                capability_id="plex",
                started_at=now,
                finished_at=now,
                window_start=now,
                window_end=now,
                status="ok",
            ),
            [],
            [],
            history_limit=20,
            analytics_snapshot={},
        )
        assert store.get_analytics_snapshot("plex", "2026-09-10T00:00:00+00:00") is None
        row = store.get_capability_run("plex", "2026-09-10T00:00:00+00:00")
        assert row is not None
        assert _run_summary(row)["analytics_ready"] is False


def test_minimal_snapshot_is_ready(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from phoenix_scraper.api_capabilities import _run_summary
    from phoenix_scraper.analytics_snapshot import build_minimal_analytics_snapshot
    from phoenix_scraper.models import Capability, CapabilityFilter

    db = tmp_path / "min.db"
    with Store(db) as store:
        now = datetime(2026, 9, 10, tzinfo=UTC)
        store.record_capability_run(
            CapabilityRun(
                run_id="2026-09-10T00:00:00+00:00",
                capability_id="plex",
                started_at=now,
                finished_at=now,
                window_start=now,
                window_end=now,
                status="ok",
            ),
            [],
            [],
            history_limit=20,
        )
        cap = Capability(
            id="plex",
            name="PLEX",
            filter=CapabilityFilter(workflow_stage="plex"),
        )
        minimal = build_minimal_analytics_snapshot(
            store, cap,
            run_id="2026-09-10T00:00:00+00:00",
            window_start=now,
            window_end=now,
        )
        assert "overview" in minimal
        store.set_analytics_snapshot("plex", "2026-09-10T00:00:00+00:00", minimal)
        row = store.get_capability_run("plex", "2026-09-10T00:00:00+00:00")
        assert _run_summary(row)["analytics_ready"] is True
