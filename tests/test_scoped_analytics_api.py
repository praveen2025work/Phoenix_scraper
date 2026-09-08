"""The optional ?capability= param on the analytics routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
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
        yield c


def test_overview_scoped_to_capability_is_a_strict_subset(client: TestClient) -> None:
    whole = client.get("/overview").json()
    scoped = client.get("/overview?capability=plex").json()
    assert 0 < scoped["n_spans"] < whole["n_spans"]  # plex is one of several stages


def test_explicit_stage_overrides_capability(client: TestClient) -> None:
    a = client.get("/overview?capability=plex&stage=fobo_recon").json()
    b = client.get("/overview?stage=fobo_recon").json()
    assert a["n_spans"] == b["n_spans"]


def test_absent_capability_is_unchanged(client: TestClient) -> None:
    assert client.get("/overview").json() == client.get("/overview?capability=").json()


def test_spans_route_scopes_too(client: TestClient) -> None:
    scoped = client.get("/spans?capability=plex").json()
    assert scoped and all(row["workflow_stage"] == "plex" for row in scoped)
