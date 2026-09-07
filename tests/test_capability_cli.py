"""CLI tests for `pheonix capability` verbs."""

from pathlib import Path

from typer.testing import CliRunner, Result

from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.storage import Store

runner = CliRunner()


def _invoke(*args: str) -> Result:
    return runner.invoke(cli_app, list(args))


class TestCapabilityNew:
    def test_creates_dir_and_row(self, tmp_path: Path) -> None:
        caps = tmp_path / "caps"
        db = tmp_path / "c.db"
        result = _invoke(
            "capability", "new", "fobo",
            "--name", "FOBO reconciliation",
            "--project", "pnl-agent", "--stage", "fobo_recon",
            "--window-days", "21",
            "--capabilities-dir", str(caps), "--db", str(db),
        )
        assert result.exit_code == 0, result.output
        assert (caps / "fobo" / "capability.yaml").is_file()
        store = Store(db)
        try:
            cap = store.get_capability("fobo")
            assert cap is not None
            assert cap.name == "FOBO reconciliation"
            assert cap.filter.project == "pnl-agent"
            assert cap.window_days == 21
        finally:
            store.close()

    def test_duplicate_exits_1(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        assert _invoke("capability", "new", "fobo", *common).exit_code == 0
        dup = _invoke("capability", "new", "fobo", *common)
        assert dup.exit_code == 1
        assert "already exists" in dup.output

    def test_bad_id_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "new", "Bad_Id",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 1
        assert "Invalid capability id" in result.output

    def test_zero_window_days_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "new", "x", "--window-days", "0",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 1


class TestCapabilitySync:
    def test_sync_all_after_hand_edit(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--name", "FOBO", *common)
        # hand-edit the yaml the way a user would
        yaml_path = caps / "fobo" / "capability.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace("status: active", "status: paused"),
            encoding="utf-8",
        )
        result = _invoke("capability", "sync", *common)
        assert result.exit_code == 0, result.output
        store = Store(db)
        try:
            assert store.get_capability("fobo").status == "paused"
        finally:
            store.close()

    def test_sync_unknown_id_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "sync", "ghost",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 1

    def test_sync_single_id_success(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--name", "FOBO", *common)
        # drop the row, then sync just this id back
        store = Store(db)
        try:
            store.delete_capability("fobo")
        finally:
            store.close()
        result = _invoke("capability", "sync", "fobo", *common)
        assert result.exit_code == 0, result.output
        assert "synced fobo" in result.output
        store = Store(db)
        try:
            assert store.get_capability("fobo") is not None
        finally:
            store.close()

    def test_sync_empty_root_reports_nothing(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "sync",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 0, result.output
        assert "No capabilities found." in result.output


class TestCapabilityList:
    def test_lists_disk_capabilities_with_sync_state(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--name", "FOBO", *common)
        _invoke("capability", "new", "plex", "--name", "PLEX", *common)
        # drop plex's row so it exists on disk but is "not synced"
        store = Store(db)
        try:
            store.delete_capability("plex")
        finally:
            store.close()
        result = _invoke("capability", "list", *common)
        assert result.exit_code == 0, result.output
        assert "fobo" in result.output and "plex" in result.output
        assert "not synced" in result.output  # plex

    def test_list_empty(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "list",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 0
        assert "No capabilities" in result.output


class TestCapabilityShow:
    def test_shows_fields_and_file_counts(self, tmp_path: Path) -> None:
        caps = tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(tmp_path / "c.db"))
        _invoke(
            "capability", "new", "fobo", "--name", "FOBO reconciliation",
            "--project", "pnl-agent", *common,
        )
        (caps / "fobo" / "skills" / "a.md").write_text("x", encoding="utf-8")
        result = _invoke("capability", "show", "fobo", "--capabilities-dir", str(caps))
        assert result.exit_code == 0, result.output
        assert "FOBO reconciliation" in result.output
        assert "pnl-agent" in result.output
        assert "skills: 1" in result.output

    def test_show_unknown_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "show", "ghost", "--capabilities-dir", str(tmp_path / "caps")
        )
        assert result.exit_code == 1
