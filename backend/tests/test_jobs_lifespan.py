"""The job worker lifespan: orphan reset on startup, clean thread stop."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings
from phoenix_scraper.storage import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})


def test_startup_fails_orphaned_jobs_and_worker_stops(settings) -> None:
    with Store(settings.db_path) as s:
        s.enqueue_job("stuck", "fobo", {})
        s.claim_next_job()  # 'stuck' -> running, as if a crash left it

    app = create_app(settings, run_jobs=True)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert app.state.job_worker is not None
    assert app.state.job_worker._thread is None

    with Store(settings.db_path) as s:
        job = s.get_job("stuck")
    assert job["state"] == "error"
    assert job["error"] == "interrupted by restart"


def test_default_create_app_has_no_worker(settings) -> None:
    app = create_app(settings)
    assert app.state.job_worker is None
