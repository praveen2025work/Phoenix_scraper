"""API tests for the /quality/* validation endpoints and annotation sync routes."""

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    tmp = tmp_path_factory.mktemp("quality_api")
    settings = Settings(
        _env_file=None,
        db_path=tmp / "api.db",
        export_dir=tmp / "exports",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        seeded = c.post("/demo/seed")
        assert seeded.status_code == 200, seeded.text
        yield c


def csv_rows(response) -> list[dict]:
    return list(csv.DictReader(io.StringIO(response.text)))


class TestQualityOverview:
    def test_headline_numbers(self, client: TestClient) -> None:
        data = client.get("/quality/overview").json()
        assert data["n_evaluated_spans"] > 0
        assert data["n_checks"] > 0
        assert 0.0 <= data["span_pass_rate"] <= 1.0
        assert data["sources"] == ["local"]
        assert data["annotator_kinds"] == ["CODE"]

    def test_respects_filters(self, client: TestClient) -> None:
        everyone = client.get("/quality/overview").json()
        one = client.get("/quality/overview", params={"user_id": "analyst-priya"}).json()
        assert 0 < one["n_evaluated_spans"] < everyone["n_evaluated_spans"]

    def test_impossible_filter_yields_zeroes(self, client: TestClient) -> None:
        data = client.get("/quality/overview", params={"user_id": "nobody"}).json()
        assert data["n_evaluated_spans"] == 0
        assert data["span_pass_rate"] is None


class TestQualityChecks:
    def test_lists_the_checks_that_ran(self, client: TestClient) -> None:
        rows = client.get("/quality/checks").json()
        assert rows
        names = {r["check"] for r in rows}
        # The seeded traffic exercises the answer-side and prompt-side checks.
        assert {"output_refusal", "output_empty", "prompt_injection"} <= names
        first = rows[0]
        assert first["n_evaluated"] >= first["n_failed"]
        assert 0.0 <= first["fail_rate"] <= 1.0

    def test_seeded_failures_are_detected(self, client: TestClient) -> None:
        rows = {r["check"]: r for r in client.get("/quality/checks").json()}
        # fixtures.py deliberately seeds refusals, empties, truncation and PII.
        assert rows["output_refusal"]["n_failed"] > 0
        assert rows["output_empty"]["n_failed"] > 0
        assert rows["output_truncated"]["n_failed"] > 0
        assert rows["prompt_injection"]["n_failed"] > 0

    def test_csv_export(self, client: TestClient) -> None:
        response = client.get("/quality/checks", params={"fmt": "csv"})
        assert response.headers["content-type"].startswith("text/csv")
        assert "quality_checks.csv" in response.headers["content-disposition"]
        assert csv_rows(response)


class TestQualityByDimension:
    @pytest.mark.parametrize(
        "dimension", ["user_id", "model_name", "workflow_stage", "asset_class"]
    )
    def test_supported_dimensions(self, client: TestClient, dimension: str) -> None:
        rows = client.get("/quality/by", params={"dimension": dimension}).json()
        assert rows
        assert dimension in rows[0]
        assert rows[0]["n_evaluated"] > 0

    def test_rejects_unknown_dimension(self, client: TestClient) -> None:
        response = client.get("/quality/by", params={"dimension": "secret_column"})
        assert response.status_code == 400
        assert "dimension must be one of" in response.json()["detail"]

    def test_csv_filename_distinguishes_dimensions(self, client: TestClient) -> None:
        response = client.get(
            "/quality/by", params={"dimension": "model_name", "fmt": "csv"}
        )
        assert "quality_by_model_name.csv" in response.headers["content-disposition"]


class TestQualityFailures:
    def test_lists_failing_spans_with_evidence(self, client: TestClient) -> None:
        rows = client.get("/quality/failures").json()
        assert rows
        first = rows[0]
        assert first["n_failed_checks"] >= 1
        assert first["failed_checks"]
        assert first["explanations"]  # every finding states why

    def test_top_limits_rows(self, client: TestClient) -> None:
        assert len(client.get("/quality/failures", params={"top": 3}).json()) <= 3

    def test_csv_export(self, client: TestClient) -> None:
        response = client.get("/quality/failures", params={"fmt": "csv"})
        assert "quality_failures.csv" in response.headers["content-disposition"]


class TestQualityByPrompt:
    def test_links_quality_to_prompt_clusters(self, client: TestClient) -> None:
        rows = client.get("/quality/by-prompt").json()
        assert rows
        first = rows[0]
        assert first["representative"]
        assert first["count"] >= 1
        assert 0.0 <= first["span_fail_rate"] <= 1.0


class TestEvaluationsAndCatalog:
    def test_raw_evaluations(self, client: TestClient) -> None:
        rows = client.get("/quality/evaluations", params={"limit": 5}).json()
        assert len(rows) <= 5
        assert {"span_id", "name", "label", "score", "annotator_kind"} <= set(rows[0])

    def test_catalog_describes_every_check(self, client: TestClient) -> None:
        rows = client.get("/quality/catalog").json()
        assert len(rows) >= 10
        assert {r["target"] for r in rows} <= {"prompt", "output", "span"}


class TestRowLimits:
    """A rollup must never present a truncated corpus as the whole picture."""

    def test_default_limit_covers_every_check_of_every_span(self) -> None:
        from phoenix_scraper.api import EVALUATION_ROW_LIMIT
        from phoenix_scraper.evaluations import CHECKS
        from phoenix_scraper.pipeline import ANALYSIS_SPAN_LIMIT

        # One span yields up to one row per registered check, so the row ceiling
        # has to clear spans x checks or the quality panels silently truncate.
        assert EVALUATION_ROW_LIMIT >= ANALYSIS_SPAN_LIMIT * len(CHECKS)

    def test_quality_routes_see_more_rows_than_spans(self, client: TestClient) -> None:
        n_spans = client.get("/overview").json()["n_spans"]
        n_checks = client.get("/quality/overview").json()["n_checks"]
        assert n_checks > n_spans
        # Every stored span was evaluated, none dropped by the limit.
        assert client.get("/quality/overview").json()["n_evaluated_spans"] == n_spans


class TestAnnotationRoutes:
    def test_pull_requires_phoenix(self, client: TestClient) -> None:
        response = client.post("/annotations/pull")
        assert response.status_code == 503
        assert "Phoenix is not available" in response.json()["detail"]

    def test_push_requires_phoenix(self, client: TestClient) -> None:
        assert client.post("/annotations/push").status_code == 503


class TestAuth:
    def test_quality_routes_are_protected(self, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None,
            db_path=tmp_path / "auth.db",
            export_dir=tmp_path / "exports",
            skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
            pricing_path=REPO_ROOT / "config" / "pricing.yaml",
            api_key="s3cret",
        ).model_copy(update={"phoenix_endpoint": None})
        with TestClient(create_app(settings)) as c:
            for route in ("/quality/overview", "/quality/checks", "/quality/failures",
                          "/quality/catalog", "/quality/by-prompt"):
                assert c.get(route).status_code == 401, route
            assert c.post("/annotations/pull").status_code == 401
            assert c.get(
                "/quality/overview", headers={"X-API-Key": "s3cret"}
            ).status_code == 200
