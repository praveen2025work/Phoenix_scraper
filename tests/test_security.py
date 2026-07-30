"""Regression tests for the confirmed security-review findings: API auth,
in-memory CSV responses, and CSV formula-injection sanitization."""

import pandas as pd
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from phoenix_scraper.api import create_app
from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.export import export_frame, frame_to_csv_text, sanitize_for_csv


class TestCsvFormulaInjection:
    def test_formula_triggers_neutralized(self):
        df = pd.DataFrame(
            {
                "input_text": ['=HYPERLINK("http://evil")', "+SUM(A1)", "@cmd", "\tX", "safe"],
                "count": [1, 2, 3, 4, 5],
            }
        )
        out = sanitize_for_csv(df)
        assert list(out["input_text"][:4]) == [
            "'=HYPERLINK(\"http://evil\")", "'+SUM(A1)", "'@cmd", "'\tX",
        ]
        assert out["input_text"][4] == "safe"
        assert list(out["count"]) == [1, 2, 3, 4, 5]
        # Original frame untouched.
        assert df["input_text"][0].startswith("=")

    def test_export_frame_csv_is_sanitized(self, tmp_path):
        df = pd.DataFrame({"input_text": ["=cmd|' /C calc'!A0"]})
        path = export_frame(df, tmp_path, "spans", "csv")
        content = path.read_text()
        assert "'=cmd" in content
        assert "\n=cmd" not in content

    def test_csv_text_helper_sanitized(self):
        text = frame_to_csv_text(pd.DataFrame({"a": ["=1+1"]}))
        assert "'=1+1" in text


class TestApiAuth:
    def _client(self, settings) -> TestClient:
        return TestClient(create_app(settings))

    def test_open_mode_without_key(self, settings):
        client = self._client(settings)
        assert client.get("/health").status_code == 200
        assert client.get("/spans").status_code == 200

    def test_key_required_when_configured(self, settings):
        client = self._client(settings.model_copy(update={"api_key": "sekret"}))
        assert client.get("/health").status_code == 200  # health stays open
        assert client.get("/spans").status_code == 401
        assert client.get("/spans", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.post("/demo/seed?n_sessions=1").status_code == 401
        assert client.get("/spans", headers={"X-API-Key": "sekret"}).status_code == 200

    def test_csv_response_streams_in_memory(self, settings):
        client = self._client(settings)
        resp = client.get("/spans?fmt=csv")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="spans.csv"'
        # No file round-trip: nothing lands in the export dir.
        assert not (settings.export_dir / "spans.csv").exists()


class TestServeGuard:
    def test_refuses_public_bind_without_key(self, monkeypatch):
        monkeypatch.delenv("PHEONIX_API_KEY", raising=False)
        result = CliRunner().invoke(cli_app, ["serve", "--host", "0.0.0.0"])
        assert result.exit_code == 1
