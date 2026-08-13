"""API tests for /overview, /insights/*, and the dashboard shell."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    tmp = tmp_path_factory.mktemp("insights_api")
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


def test_dashboard_served_at_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Pheonix" in response.text


def test_overview_kpis(client: TestClient) -> None:
    data = client.get("/overview").json()
    assert data["n_spans"] > 0
    assert data["n_sessions"] > 0
    assert data["n_traces"] > 0
    assert data["n_clusters"] > 0
    assert 0.0 <= data["error_rate"] <= 1.0


def test_insights_traces(client: TestClient) -> None:
    rows = client.get("/insights/traces").json()
    assert rows
    first = rows[0]
    assert first["n_spans"] >= 1
    assert "n_llm" in first and "n_tool" in first


def test_insights_questions(client: TestClient) -> None:
    rows = client.get("/insights/questions").json()
    assert rows
    assert {"question_type", "count", "example"} <= set(rows[0])


def test_insights_friction(client: TestClient) -> None:
    rows = client.get("/insights/friction").json()
    assert rows
    scores = [r["friction_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_insights_efficiency(client: TestClient) -> None:
    rows = client.get("/insights/efficiency").json()
    assert rows
    first = rows[0]
    assert {"route_len_avg", "long_route", "opportunity_score"} <= set(first)
    scores = [r["opportunity_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_insights_skill_health(client: TestClient) -> None:
    response = client.get("/insights/skill-health")
    assert response.status_code == 200
    for row in response.json():  # fixtures match some catalog skills
        assert row["status"] in ("effective", "review")


def test_users_profiles(client: TestClient) -> None:
    rows = client.get("/users").json()
    assert rows
    first = rows[0]
    assert {"user_id", "n_asks", "n_reformulations", "top_intents", "top_prompts"} <= set(first)
    asks = [r["n_asks"] for r in rows]
    assert asks == sorted(asks, reverse=True)


def test_users_filterable_by_user(client: TestClient) -> None:
    all_users = client.get("/users").json()
    one = all_users[0]["user_id"]
    filtered = client.get("/users", params={"user_id": one}).json()
    assert [r["user_id"] for r in filtered] == [one]


def test_user_question_matrix(client: TestClient) -> None:
    rows = client.get("/users/questions").json()
    assert rows
    assert {"user_id", "question_type", "count"} <= set(rows[0])


def test_insights_activity(client: TestClient) -> None:
    rows = client.get("/insights/activity").json()
    assert rows
    days = [r["day"] for r in rows]
    assert days == sorted(days)


def test_insights_tools(client: TestClient) -> None:
    response = client.get("/insights/tools")
    assert response.status_code == 200
    for row in response.json():
        assert {"tool", "n_calls", "error_rate"} <= set(row)


def test_insights_models(client: TestClient) -> None:
    rows = client.get("/insights/models").json()
    assert rows
    assert {"model", "n_calls", "tokens_in", "tokens_out"} <= set(rows[0])


def test_insights_flows(client: TestClient) -> None:
    rows = client.get("/insights/flows").json()
    assert rows
    assert "→" in rows[0]["flow"] or rows[0]["flow"] == "LLM"
    counts = [r["n_traces"] for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_insights_breakdown(client: TestClient) -> None:
    rows = client.get("/insights/breakdown").json()
    assert rows
    assert {"workflow_stage", "asset_class", "n_asks"} <= set(rows[0])


def test_insights_csv_download(client: TestClient) -> None:
    response = client.get("/insights/efficiency", params={"fmt": "csv"})
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]


def test_filter_options(client: TestClient) -> None:
    data = client.get("/filters/options").json()
    assert data["users"]
    assert data["models"]
    assert data["workflow_stages"]
    assert data["min_time"] <= data["max_time"]


def test_spans_filter_by_search_and_time(client: TestClient) -> None:
    everything = client.get("/spans", params={"limit": 100000}).json()
    some_prompt = next(r["input_text"] for r in everything if r["input_text"])
    word = some_prompt.split()[0]
    filtered = client.get("/spans", params={"search": word, "limit": 100000}).json()
    assert 0 < len(filtered) <= len(everything)
    assert all(word.lower() in r["input_text"].lower() for r in filtered)


def test_cross_origin_post_rejected(client: TestClient) -> None:
    response = client.post("/demo/seed", headers={"Origin": "http://evil.example:8200"})
    assert response.status_code == 403


def test_same_origin_post_allowed(client: TestClient) -> None:
    response = client.post("/demo/seed", headers={"Origin": "http://testserver"})
    assert response.status_code == 200


def test_security_headers_present(client: TestClient) -> None:
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
