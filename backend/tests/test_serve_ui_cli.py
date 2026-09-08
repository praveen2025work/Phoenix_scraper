"""CLI test for `pheonix serve-ui`."""

from pathlib import Path

from typer.testing import CliRunner

from phoenix_scraper.cli import app

runner = CliRunner()


def test_serve_ui_without_a_build_exits_1(tmp_path: Path) -> None:
    r = runner.invoke(app, ["serve-ui", "--dist", str(tmp_path / "nope")])
    assert r.exit_code == 1
    assert "make ui-build" in r.output
