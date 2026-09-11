"""API tests for the async capability-run job routes."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings
from phoenix_scraper.jobs import JobWorker

REPO_ROOT = Path(__file__).resolve().parent.parent

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
WINDOW = {
    "from": (NOW - timedelta(days=7)).isoformat(),
    "to": NOW.isoformat(),
}


@pytest.fixture()
def ctx(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        c.post("/demo/seed")
        c.post("/capabilities", json={"id": "plex", "name": "PLEX",
                                      "filter": {"workflow_stage": "plex"}})
        yield c, settings


def test_enqueue_returns_202_and_persists(ctx) -> None:
    c, _ = ctx
    r = c.post("/capabilities/plex/jobs", json=WINDOW)
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "queued" and body["capability_id"] == "plex"
    assert body["stage"] == "queued" and body["progress"] == 0.0
    assert body["message"]  # offline / queue hint — never leave the SPA blank
    listed = c.get("/capabilities/plex/jobs").json()
    assert [j["job_id"] for j in listed] == [body["job_id"]]


def test_enqueue_with_live_worker_leaves_queued(tmp_path: Path) -> None:
    """create_app_default-style serving must claim jobs without a manual drain."""
    import time

    from phoenix_scraper import capability as cap_mod
    from phoenix_scraper.models import CapabilityFilter

    settings = Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})
    cap_mod.scaffold_capability(
        tmp_path / "caps", "plex", name="PLEX",
        cap_filter=CapabilityFilter(workflow_stage="plex"), window_days=30,
    )
    app = create_app(settings, run_jobs=True)
    with TestClient(app) as c:
        health = c.get("/health").json()
        assert health["jobs"] == "running"
        c.post("/demo/seed")
        job_id = c.post("/capabilities/plex/jobs", json=WINDOW).json()["job_id"]
        deadline = time.time() + 5.0
        state = "queued"
        while time.time() < deadline:
            state = c.get(f"/capabilities/plex/jobs/{job_id}").json()["state"]
            if state != "queued":
                break
            time.sleep(0.05)
        assert state in {"running", "done"}, f"job stuck in {state!r}"
        # Wait for completion so lifespan shutdown is clean.
        while time.time() < deadline:
            if c.get(f"/capabilities/plex/jobs/{job_id}").json()["state"] in {
                "done", "error",
            }:
                break
            time.sleep(0.05)


def test_enqueue_requires_closed_window(ctx) -> None:
    c, _ = ctx
    assert c.post("/capabilities/plex/jobs", json={}).status_code == 422
    assert c.post(
        "/capabilities/plex/jobs", json={"from": WINDOW["from"]}
    ).status_code == 422
    assert c.post(
        "/capabilities/plex/jobs",
        json={"from": WINDOW["to"], "to": WINDOW["from"]},
    ).status_code == 422


def test_enqueue_unknown_capability_404(ctx) -> None:
    c, _ = ctx
    assert c.post("/capabilities/ghost/jobs", json=WINDOW).status_code == 404


def test_job_lifecycle_queued_then_done(ctx) -> None:
    c, settings = ctx
    job_id = c.post("/capabilities/plex/jobs", json=WINDOW).json()["job_id"]
    queued = c.get(f"/capabilities/plex/jobs/{job_id}").json()
    assert queued["state"] == "queued"
    assert queued["stage"] == "queued"

    assert JobWorker(settings).drain_once() == job_id

    done = c.get(f"/capabilities/plex/jobs/{job_id}").json()
    assert done["state"] == "done" and done["run_id"]
    assert done["stage"] == "done" and done["progress"] == 1.0
    assert done["message"]
    run = c.get(f"/capabilities/plex/runs/{done['run_id']}")
    assert run.status_code == 200


def test_job_id_under_wrong_capability_404(ctx) -> None:
    c, _ = ctx
    job_id = c.post("/capabilities/plex/jobs", json=WINDOW).json()["job_id"]
    c.post("/capabilities", json={"id": "fobo", "name": "F",
                                  "filter": {"workflow_stage": "fobo_recon"}})
    assert c.get(f"/capabilities/fobo/jobs/{job_id}").status_code == 404


def test_sync_run_endpoint_still_synchronous(ctx) -> None:
    c, _ = ctx
    r = c.post("/capabilities/plex/runs", json={})
    assert r.status_code == 200
    assert "run_id" in r.json() and "status" in r.json()


def test_run_results_aggregate(ctx) -> None:
    c, settings = ctx
    job_id = c.post("/capabilities/plex/jobs", json=WINDOW).json()["job_id"]
    JobWorker(settings).drain_once()
    run_id = c.get(f"/capabilities/plex/jobs/{job_id}").json()["run_id"]
    body = c.get(f"/capabilities/plex/runs/{run_id}/results").json()
    assert body["run_id"] == run_id
    assert "funnel" in body
    assert {"n_spans", "n_in_scope_spans", "n_clusters", "empty_at", "empty_reason"} <= set(
        body["funnel"]
    )
    assert "uncovered" in body and "suggested_skill_updates" in body
    assert "rung1_candidates" in body and "rung2_candidates" in body
    assert isinstance(body["skill_hashes"], dict)
    assert isinstance(body["warnings"], list)
    for cand in body["rung1_candidates"] + body["rung2_candidates"]:
        assert "current_evidence" in cand and isinstance(cand["current_evidence"], dict)
        assert "current_evidence_json" not in cand
        assert "promoted_artifact_paths" in cand
        assert "promoted_artifact_paths_json" not in cand


def test_run_compare_requires_two_runs(ctx) -> None:
    c, settings = ctx
    # First version
    j1 = c.post("/capabilities/plex/jobs", json=WINDOW).json()["job_id"]
    JobWorker(settings).drain_once()
    r1 = c.get(f"/capabilities/plex/jobs/{j1}").json()["run_id"]

    # Second version (slightly later window so run_id differs)
    later = {
        "from": (NOW - timedelta(days=6)).isoformat(),
        "to": (NOW + timedelta(hours=1)).isoformat(),
    }
    j2 = c.post("/capabilities/plex/jobs", json=later).json()["job_id"]
    JobWorker(settings).drain_once()
    r2 = c.get(f"/capabilities/plex/jobs/{j2}").json()["run_id"]
    assert r1 != r2

    body = c.get(
        "/capabilities/plex/runs/compare",
        params={"from_run": r1, "to_run": r2},
    ).json()
    assert body["from_run"]["run_id"] == r1
    assert body["to_run"]["run_id"] == r2
    assert "skill_hash_changes" in body
    assert {"added", "removed", "changed", "unchanged"} <= set(
        body["skill_hash_changes"]
    )
    assert isinstance(body["gaps_closed"], list)
    assert isinstance(body["gaps_new"], list)
    assert isinstance(body["candidates_advancing"], list)


def test_run_compare_missing_run_404(ctx) -> None:
    c, settings = ctx
    j1 = c.post("/capabilities/plex/jobs", json=WINDOW).json()["job_id"]
    JobWorker(settings).drain_once()
    r1 = c.get(f"/capabilities/plex/jobs/{j1}").json()["run_id"]
    assert (
        c.get(
            "/capabilities/plex/runs/compare",
            params={"from_run": r1, "to_run": "ghost"},
        ).status_code
        == 404
    )
