"""API tests for the async capability-run job routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings
from phoenix_scraper.jobs import JobWorker

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    r = c.post("/capabilities/plex/jobs", json={})
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "queued" and body["capability_id"] == "plex"
    listed = c.get("/capabilities/plex/jobs").json()
    assert [j["job_id"] for j in listed] == [body["job_id"]]


def test_enqueue_unknown_capability_404(ctx) -> None:
    c, _ = ctx
    assert c.post("/capabilities/ghost/jobs", json={}).status_code == 404


def test_job_lifecycle_queued_then_done(ctx) -> None:
    c, settings = ctx
    job_id = c.post("/capabilities/plex/jobs", json={}).json()["job_id"]
    assert c.get(f"/capabilities/plex/jobs/{job_id}").json()["state"] == "queued"

    assert JobWorker(settings).drain_once() == job_id

    done = c.get(f"/capabilities/plex/jobs/{job_id}").json()
    assert done["state"] == "done" and done["run_id"]
    run = c.get(f"/capabilities/plex/runs/{done['run_id']}")
    assert run.status_code == 200


def test_job_id_under_wrong_capability_404(ctx) -> None:
    c, _ = ctx
    job_id = c.post("/capabilities/plex/jobs", json={}).json()["job_id"]
    c.post("/capabilities", json={"id": "fobo", "name": "F",
                                  "filter": {"workflow_stage": "fobo_recon"}})
    assert c.get(f"/capabilities/fobo/jobs/{job_id}").status_code == 404


def test_sync_run_endpoint_still_synchronous(ctx) -> None:
    c, _ = ctx
    r = c.post("/capabilities/plex/runs", json={})
    assert r.status_code == 200
    assert "run_id" in r.json() and "status" in r.json()
