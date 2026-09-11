"""Tests for the background JobWorker (driven synchronously via drain_once)."""

from pathlib import Path

import pytest

from phoenix_scraper import capability as cap_mod
from phoenix_scraper.config import Settings
from phoenix_scraper.jobs import JobWorker
from phoenix_scraper.models import CapabilityFilter

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def job_settings(tmp_path, seeded_store):
    root = tmp_path / "caps"
    cap_mod.scaffold_capability(
        root, "fobo", name="FOBO",
        cap_filter=CapabilityFilter(workflow_stage="fobo_recon"), window_days=30,
    )
    return Settings(
        db_path=tmp_path / "test.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=root,
    ).model_copy(update={"phoenix_endpoint": None})


def test_drain_once_empty_queue_returns_none(job_settings) -> None:
    assert JobWorker(job_settings).drain_once() is None


def test_drain_once_runs_the_capability_and_marks_done(job_settings, seeded_store) -> None:
    seeded_store.enqueue_job("j1", "fobo", {"replace_today": False})
    processed = JobWorker(job_settings).drain_once()
    assert processed == "j1"
    job = seeded_store.get_job("j1")
    assert job["state"] == "done"
    assert job["run_id"] is not None
    runs = seeded_store.capability_runs_frame("fobo")
    assert job["run_id"] in set(runs["run_id"])


def test_drain_once_infra_failure_marks_error(job_settings, seeded_store, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr("phoenix_scraper.jobs.run_capabilities", boom)
    seeded_store.enqueue_job("j1", "fobo", {})
    JobWorker(job_settings).drain_once()
    job = seeded_store.get_job("j1")
    assert job["state"] == "error"
    assert "RuntimeError: db gone" in job["error"]
    assert job["run_id"] is None


def test_start_stop_is_safe_and_idempotent(job_settings) -> None:
    w = JobWorker(job_settings, poll_seconds=0.05)
    w.start()
    w.start()  # idempotent
    assert w.is_alive()
    w.stop()
    w.stop()   # safe when already stopped
    assert not w.is_alive()


def test_notify_wakes_worker_to_claim_job(job_settings, seeded_store) -> None:
    """Enqueue + notify must claim without waiting for the poll interval."""
    import time

    w = JobWorker(job_settings, poll_seconds=30.0)  # would stall without notify
    w.start()
    try:
        seeded_store.enqueue_job("j-wake", "fobo", {})
        w.notify()
        deadline = time.time() + 3.0
        while time.time() < deadline:
            job = seeded_store.get_job("j-wake")
            if job and job["state"] != "queued":
                break
            time.sleep(0.05)
        assert seeded_store.get_job("j-wake")["state"] in {"running", "done", "error"}
        # Let the run finish so stop() doesn't join a busy thread too early.
        while time.time() < deadline:
            if seeded_store.get_job("j-wake")["state"] in {"done", "error"}:
                break
            time.sleep(0.05)
    finally:
        w.stop()
