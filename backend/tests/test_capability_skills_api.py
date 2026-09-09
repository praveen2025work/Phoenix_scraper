"""API tests for uploading / listing / deleting a capability's own skill files."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent

_GOOD = """---
name: fx-recon-triage
description: Triage FX reconciliation breaks.
example_prompts:
  - why is there a recon break on EURUSD
keywords: [recon, break]
---

## When to use
Recon break questions on FX.
"""


@pytest.fixture()
def ctx(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        c.post("/capabilities", json={"id": "fobo", "name": "FOBO",
                                      "filter": {"workflow_stage": "fobo_recon"}})
        yield c, settings


def test_upload_then_list(ctx) -> None:
    c, settings = ctx
    assert c.get("/capabilities/fobo/skills").json() == []

    r = c.post("/capabilities/fobo/skills",
               json={"filename": "fx-recon-triage", "content": _GOOD})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["filename"] == "fx-recon-triage.md"
    assert row["valid"] is True
    assert row["name"] == "fx-recon-triage"
    assert row["n_example_prompts"] == 1
    assert row["replaced"] is False

    listed = c.get("/capabilities/fobo/skills").json()
    assert [s["filename"] for s in listed] == ["fx-recon-triage.md"]
    # and it shows up on the capability detail payload
    assert "fx-recon-triage.md" in c.get("/capabilities/fobo").json()["skill_files"]
    # ... and on disk where a run will read it
    assert (settings.capabilities_dir / "fobo" / "skills" / "fx-recon-triage.md").is_file()


def test_reupload_replaces(ctx) -> None:
    c, _ = ctx
    c.post("/capabilities/fobo/skills", json={"filename": "a.md", "content": _GOOD})
    r = c.post("/capabilities/fobo/skills", json={"filename": "a.md", "content": _GOOD})
    assert r.status_code == 201
    assert r.json()["replaced"] is True
    assert len(c.get("/capabilities/fobo/skills").json()) == 1


def test_content_without_frontmatter_is_rejected_and_not_left_behind(ctx) -> None:
    c, settings = ctx
    r = c.post("/capabilities/fobo/skills",
               json={"filename": "bad.md", "content": "just some notes\n"})
    assert r.status_code == 422
    assert "frontmatter" in r.json()["detail"].lower()
    assert c.get("/capabilities/fobo/skills").json() == []
    assert not (settings.capabilities_dir / "fobo" / "skills" / "bad.md").exists()


@pytest.mark.parametrize("bad", ["../escape.md", "Has Spaces.md", "9leading.md", "a/b.md"])
def test_unsafe_filenames_rejected(ctx, bad: str) -> None:
    c, _ = ctx
    r = c.post("/capabilities/fobo/skills", json={"filename": bad, "content": _GOOD})
    assert r.status_code in (400, 404)  # 404 when the path segment breaks routing


def test_unknown_capability_404(ctx) -> None:
    c, _ = ctx
    assert c.get("/capabilities/ghost/skills").status_code == 404
    r = c.post("/capabilities/ghost/skills", json={"filename": "a.md", "content": _GOOD})
    assert r.status_code == 404


def test_delete(ctx) -> None:
    c, _ = ctx
    c.post("/capabilities/fobo/skills", json={"filename": "a.md", "content": _GOOD})
    assert c.delete("/capabilities/fobo/skills/a.md").status_code == 200
    assert c.get("/capabilities/fobo/skills").json() == []
    assert c.delete("/capabilities/fobo/skills/a.md").status_code == 404


def test_uploaded_skill_is_loaded_by_a_run(ctx) -> None:
    """The whole point: an uploaded file joins the skill set the miner matches against."""
    from phoenix_scraper.capability import load_capability
    from phoenix_scraper.capability_run import load_capability_skills

    c, settings = ctx
    c.post("/capabilities/fobo/skills",
           json={"filename": "fx-recon-triage", "content": _GOOD})
    cap = load_capability(settings.capabilities_dir, "fobo")
    names = {s.name for s in load_capability_skills(settings, cap)}
    assert "fx-recon-triage" in names
