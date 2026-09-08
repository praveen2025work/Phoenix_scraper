"""API tests for the ladder board / candidate / decision / promote routes."""

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
        c.post("/capabilities/plex/runs", json={})
        yield c


def _a_candidate(client: TestClient) -> str:
    board = client.get("/capabilities/plex/candidates").json()
    assert board, "demo plex run should yield at least one candidate"
    return board[0]["candidate_id"]


class TestBoard:
    def test_board_lists_candidates(self, client: TestClient) -> None:
        board = client.get("/capabilities/plex/candidates").json()
        assert isinstance(board, list) and board
        assert board[0]["candidate_id"].startswith("plex:")

    def test_board_filters_by_rung(self, client: TestClient) -> None:
        r = client.get("/capabilities/plex/candidates?rung=deterministic")
        assert r.status_code == 200


class TestCandidateDetail:
    def test_detail_has_observations_and_decisions(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.get(f"/candidates/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["candidate"]["candidate_id"] == cid
        assert isinstance(body["observations"], list)
        assert isinstance(body["decisions"], list)

    def test_unknown_candidate_404(self, client: TestClient) -> None:
        assert client.get("/candidates/plex:s:nope").status_code == 404


class TestDecision:
    def test_reject_applies_transition_and_logs(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.post(f"/candidates/{cid}/decision",
                        json={"action": "reject", "actor": "alice", "note": "dupe"})
        assert r.status_code == 200, r.text
        assert client.get(f"/candidates/{cid}").json()["candidate"]["status"] == "rejected"

    def test_invalid_transition_is_409(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.post(f"/candidates/{cid}/decision",
                        json={"action": "accept", "actor": "a"})
        assert r.status_code == 409


class TestPromote:
    def test_preview_writes_nothing(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.get(f"/candidates/{cid}/artifact/preview")
        assert r.status_code == 200
        assert r.json()["contents"]
        assert client.get(f"/candidates/{cid}").json()["candidate"]["status"] != "promoted"

    def test_promote_needs_accepted(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.post(f"/candidates/{cid}/promote")
        assert r.status_code == 409
