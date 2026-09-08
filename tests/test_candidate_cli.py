"""CLI tests for pheonix candidates / decide / promote."""

from pathlib import Path

from typer.testing import CliRunner, Result

from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.storage import Store

runner = CliRunner()


def _invoke(*args: str) -> Result:
    return runner.invoke(cli_app, list(args))


def _seed(tmp_path: Path):
    """demo traffic + a 'plex' capability whose run yields a Rung-1 candidate."""
    db, caps = tmp_path / "c.db", tmp_path / "caps"
    assert _invoke("demo", "--db", str(db), "--export-dir", str(tmp_path / "e"),
                   "--sessions", "24").exit_code == 0
    common = ("--capabilities-dir", str(caps), "--db", str(db))
    assert _invoke("capability", "new", "plex", "--stage", "plex", *common).exit_code == 0
    assert _invoke("run", "--capability", "plex", *common).exit_code == 0
    return db, common


def _first_candidate(db: Path) -> str:
    store = Store(db)
    try:
        return store.candidates_frame("plex").iloc[0]["candidate_id"]
    finally:
        store.close()


class TestCandidatesVerb:
    def test_lists_candidates(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        r = _invoke("candidates", "plex", *common)
        assert r.exit_code == 0, r.output
        assert "plex:s:" in r.output

    def test_empty_capability(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        _invoke("capability", "new", "empty", *common)
        r = _invoke("candidates", "empty", *common)
        assert r.exit_code == 0 and "no candidates" in r.output.lower()


class TestDecide:
    def test_reject_then_status_changes(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        r = _invoke("decide", cid, "--action", "reject", "--actor", "alice",
                    "--note", "covered elsewhere", *common)
        assert r.exit_code == 0, r.output
        store = Store(db)
        try:
            assert store.get_candidate(cid).status == "rejected"
            assert list(store.candidate_decisions_frame(cid)["action"]) == ["reject"]
        finally:
            store.close()

    def test_invalid_transition_exits_1(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        # a brand-new / accumulating candidate cannot be 'accept'ed (only ready can)
        r = _invoke("decide", cid, "--action", "accept", "--actor", "a", *common)
        assert r.exit_code == 1
        assert "ready" in r.output.lower() or "cannot" in r.output.lower()


class TestPromote:
    def test_promote_dry_run_prints_without_writing(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        store = Store(db)
        try:
            store.upsert_candidate(store.get_candidate(cid).model_copy(
                update={"status": "accepted"}))
        finally:
            store.close()
        r = _invoke("promote", cid, "--dry-run", "--actor", "a", *common)
        assert r.exit_code == 0, r.output
        store = Store(db)
        try:
            assert store.get_candidate(cid).status == "accepted"
        finally:
            store.close()
