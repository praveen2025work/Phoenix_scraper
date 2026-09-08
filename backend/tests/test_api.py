"""API tests: FastAPI TestClient against an app built with temp Settings."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app, create_app_default
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def api_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    tmp = tmp_path_factory.mktemp("api")
    base = Settings(
        db_path=tmp / "api.db",
        export_dir=tmp / "exports",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
    )
    # Force offline no matter what PHOENIX_* env vars exist on the host.
    return base.model_copy(update={"phoenix_endpoint": None})


@pytest.fixture(scope="module")
def client(api_settings: Settings) -> TestClient:
    with TestClient(create_app(api_settings)) as c:
        seeded = c.post("/demo/seed")
        assert seeded.status_code == 200, seeded.text
        yield c


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_demo_seed_reports_analysis(client: TestClient) -> None:
    resp = client.post("/demo/seed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["source"] == "fixtures"
    assert body["report"]["pulled"] > 0
    assert body["report"]["inserted"] == 0  # second seed is idempotent
    assert body["clusters"] > 0
    assert body["matches"] > 0
    assert body["proposals"] > 0
    assert body["sessions"] == 60


def test_prompts_frequent_json(client: TestClient) -> None:
    rows = client.get("/prompts/frequent").json()
    assert isinstance(rows, list) and rows
    top = rows[0]
    assert {"cluster_id", "signature", "representative", "count"} <= top.keys()
    assert top["count"] > 5
    counts = [r["count"] for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_prompts_frequent_min_count_filter(client: TestClient) -> None:
    rows = client.get("/prompts/frequent", params={"min_count": 10_000}).json()
    assert rows == []


def test_prompts_frequent_csv_download(client: TestClient, api_settings: Settings) -> None:
    resp = client.get("/prompts/frequent", params={"fmt": "csv"})
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "prompts_frequent.csv" in disposition
    assert resp.headers["content-type"].startswith("text/csv")
    # CSV responses are built in memory — nothing may be left behind on disk.
    assert not (api_settings.export_dir / "prompts_frequent.csv").exists()
    assert "cluster_id" in resp.text.splitlines()[0]


def test_prompts_frequent_invalid_fmt(client: TestClient) -> None:
    resp = client.get("/prompts/frequent", params={"fmt": "xml"})
    assert resp.status_code == 422


def test_skills_matches(client: TestClient) -> None:
    rows = client.get("/skills/matches").json()
    assert rows
    assert {"cluster_id", "skill_name", "score"} <= rows[0].keys()


def test_skills_gaps(client: TestClient) -> None:
    rows = client.get("/skills/gaps").json()
    assert rows
    assert {"cluster_id", "proposed_name", "level", "evidence_count"} <= rows[0].keys()
    assert all(r["evidence_count"] >= 2 for r in rows)


def test_sessions(client: TestClient) -> None:
    rows = client.get("/sessions").json()
    assert len(rows) == 60
    assert {"session_id", "n_llm_spans", "total_cost_usd"} <= rows[0].keys()


def test_spans_with_filters(client: TestClient) -> None:
    rows = client.get("/spans", params={"asset_class": "fx", "limit": 50}).json()
    assert rows
    assert all(r["asset_class"] == "fx" for r in rows)
    assert len(rows) <= 50


def test_costs_summary(client: TestClient) -> None:
    rows = client.get("/costs/summary", params={"group_by": "model_name"}).json()
    assert rows
    assert {"model_name", "n_spans", "total_tokens", "total_cost_usd"} <= rows[0].keys()
    assert sum(r["total_cost_usd"] for r in rows) > 0


def test_costs_summary_invalid_group_by(client: TestClient) -> None:
    resp = client.get("/costs/summary", params={"group_by": "nope"})
    assert resp.status_code == 400


def test_scrape_run_unavailable(client: TestClient) -> None:
    resp = client.post("/scrape/run")
    assert resp.status_code == 503


def test_create_app_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PHEONIX_DB_PATH", str(tmp_path / "default.db"))
    monkeypatch.setenv("PHEONIX_EXPORT_DIR", str(tmp_path / "exports"))
    app = create_app_default()
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200


def test_cors_headers_for_configured_origin(api_settings: Settings) -> None:
    app = create_app(api_settings.model_copy(update={"cors_origins": "http://localhost:5173"}))
    with TestClient(app) as c:
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        pre = c.options(
            "/overview",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert pre.status_code in (200, 204)


def test_cross_origin_post_from_allowed_origin_is_not_csrf_blocked(
    api_settings: Settings,
) -> None:
    app = create_app(api_settings.model_copy(update={"cors_origins": "http://localhost:5173"}))
    with TestClient(app) as c:
        c.post("/demo/seed")
        r = c.post("/analyze/run", headers={"Origin": "http://localhost:5173"})
        assert r.status_code == 200, r.text


def test_cross_origin_post_from_unknown_origin_is_csrf_blocked(api_settings: Settings) -> None:
    with TestClient(create_app(api_settings)) as c:
        r = c.post("/analyze/run", headers={"Origin": "http://evil.example"})
        assert r.status_code == 403


def test_dev_cors_allows_the_vite_dev_server_by_default(api_settings: Settings) -> None:
    # `pheonix serve` / create_app_default pass dev_cors=True so the SPA works
    # with zero PHEONIX_CORS_ORIGINS config.
    with TestClient(create_app(api_settings, dev_cors=True)) as c:
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    # explicit config still wins — dev default is not merged in
    explicit = api_settings.model_copy(update={"cors_origins": "http://example.com"})
    with TestClient(create_app(explicit, dev_cors=True)) as c:
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") is None


def test_root_is_a_json_notice_not_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "pheonix"
    assert "frontend" in body
    assert "legacy_dashboard" not in body
    assert "json" in r.headers["content-type"]


def test_legacy_dashboard_is_gone(client: TestClient) -> None:
    assert client.get("/legacy").status_code == 404
