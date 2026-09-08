"""CLI tests for `pheonix run` and `pheonix capability runs`."""

from pathlib import Path

from typer.testing import CliRunner, Result

from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.storage import Store

runner = CliRunner()


def _invoke(*args: str) -> Result:
    return runner.invoke(cli_app, list(args))


def _seed_db(tmp_path: Path) -> Path:
    db = tmp_path / "c.db"
    r = _invoke("demo", "--db", str(db), "--export-dir", str(tmp_path / "e"), "--sessions", "20")
    assert r.exit_code == 0, r.output
    return db


class TestRun:
    def test_run_one_capability(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        assert _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common).exit_code == 0
        r = _invoke("run", "--capability", "fobo", *common)
        assert r.exit_code == 0, r.output
        assert "fobo" in r.output
        assert "in scope" in r.output.lower() or "in-scope" in r.output.lower()
        store = Store(db)
        try:
            assert len(store.capability_runs_frame("fobo")) == 1
        finally:
            store.close()

    def test_run_all(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        _invoke("capability", "new", "plex", "--stage", "plex", *common)
        r = _invoke("run", "--all", *common)
        assert r.exit_code == 0, r.output
        assert "fobo" in r.output and "plex" in r.output

    def test_requires_exactly_one_selector(self, tmp_path: Path) -> None:
        common = ("--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"))
        assert _invoke("run", *common).exit_code == 1
        assert _invoke("run", "--capability", "x", "--all", *common).exit_code == 1

    def test_second_run_shows_a_delta(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        _invoke("run", "--capability", "fobo", *common)
        r = _invoke("run", "--capability", "fobo", "--replace-today", *common)
        assert r.exit_code == 0, r.output
        # a delta section renders (may be "no change" — assert the header, not rows)
        assert "since" in r.output.lower() or "change" in r.output.lower()

    def test_from_to_window_override(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        r = _invoke("run", "--capability", "fobo",
                    "--from", "2020-01-01", "--to", "2020-02-01", *common)
        assert r.exit_code == 0, r.output
        assert "0" in r.output  # nothing in that window


class TestCapabilityRunsVerb:
    def test_lists_recorded_runs(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        _invoke("run", "--capability", "fobo", *common)
        r = _invoke("capability", "runs", "fobo", *common)
        assert r.exit_code == 0, r.output
        assert "run_id" in r.output or "window" in r.output.lower()

    def test_runs_for_capability_with_no_runs(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", *common)
        r = _invoke("capability", "runs", "fobo", *common)
        assert r.exit_code == 0
        assert "no runs" in r.output.lower()
