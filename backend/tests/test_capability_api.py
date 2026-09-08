"""API tests for capability CRUD + run routes."""

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
        yield c


def _create(client: TestClient, cap_id="fobo", stage="fobo_recon", **over) -> dict:
    body = {"id": cap_id, "name": cap_id.upper(),
            "filter": {"workflow_stage": stage}, "window_days": 30}
    body.update(over)
    r = client.post("/capabilities", json=body)
    assert r.status_code == 201, r.text
    return r.json()


class TestCapabilityCrud:
    def test_create_lists_and_gets(self, client: TestClient) -> None:
        _create(client)
        listing = client.get("/capabilities").json()
        assert any(c["id"] == "fobo" for c in listing)
        detail = client.get("/capabilities/fobo")
        assert detail.status_code == 200
        assert detail.json()["capability"]["filter"]["workflow_stage"] == "fobo_recon"

    def test_create_duplicate_is_409(self, client: TestClient) -> None:
        _create(client)
        r = client.post("/capabilities", json={"id": "fobo", "name": "x"})
        assert r.status_code == 409

    def test_create_bad_id_is_422_or_400(self, client: TestClient) -> None:
        r = client.post("/capabilities", json={"id": "Bad Id!", "name": "x"})
        assert r.status_code in (400, 422)

    def test_patch_updates_filter_and_status(self, client: TestClient) -> None:
        _create(client)
        r = client.patch("/capabilities/fobo",
                         json={"window_days": 14, "status": "paused"})
        assert r.status_code == 200
        got = client.get("/capabilities/fobo").json()["capability"]
        assert got["window_days"] == 14 and got["status"] == "paused"

    def test_get_missing_is_404(self, client: TestClient) -> None:
        assert client.get("/capabilities/ghost").status_code == 404

    def test_delete_removes_row_keeps_dir(self, client: TestClient, tmp_path: Path) -> None:
        _create(client)
        r = client.delete("/capabilities/fobo")
        assert r.status_code == 200
        assert client.get("/capabilities/fobo").status_code == 404
        assert (tmp_path / "caps" / "fobo" / "capability.yaml").exists()

    def test_delete_purge_removes_dir(self, client: TestClient, tmp_path: Path) -> None:
        _create(client)
        client.delete("/capabilities/fobo?purge=true")
        assert not (tmp_path / "caps" / "fobo").exists()

    def test_sync_reads_hand_edited_yaml(self, client: TestClient, tmp_path: Path) -> None:
        _create(client)
        yaml_path = tmp_path / "caps" / "fobo" / "capability.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace("window_days: 30", "window_days: 7"),
            encoding="utf-8",
        )
        r = client.post("/capabilities/fobo/sync")
        assert r.status_code == 200
        assert client.get("/capabilities/fobo").json()["capability"]["window_days"] == 7


class TestRunRoutes:
    def test_trigger_run_records_and_returns_summary(self, client: TestClient) -> None:
        _create(client, "plex", stage="plex")
        r = client.post("/capabilities/plex/runs", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["capability_id"] == "plex"
        assert "n_rung1_candidates" in body and "n_rung2_candidates" in body
        hist = client.get("/capabilities/plex/runs").json()
        assert len(hist) == 1

    def test_one_run_detail_parses_notes(self, client: TestClient) -> None:
        _create(client, "plex", stage="plex")
        run_id = client.post("/capabilities/plex/runs", json={}).json()["run_id"]
        r = client.get(f"/capabilities/plex/runs/{run_id}")
        assert r.status_code == 200
        assert isinstance(r.json()["notes"], list)

    def test_delta_renders_after_two_runs(self, client: TestClient) -> None:
        _create(client, "plex", stage="plex")
        client.post("/capabilities/plex/runs", json={})
        client.post("/capabilities/plex/runs", json={"replace_today": False})
        r = client.get("/capabilities/plex/runs/delta")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_run_unknown_capability_is_404(self, client: TestClient) -> None:
        assert client.post("/capabilities/ghost/runs", json={}).status_code == 404
