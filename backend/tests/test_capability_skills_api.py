"""API tests for a capability's own skill files: upload, and the gap loop they close."""

import json
from datetime import UTC, datetime, timedelta
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


def test_uploading_the_suggested_skill_closes_the_gap(ctx) -> None:
    """The whole loop: coverage names a gap -> upload a skill file demonstrating it
    -> re-run -> that gap is gone. Scoped to the capability, not the global tables."""
    c, _ = ctx
    c.post("/demo/seed")
    c.post("/capabilities/fobo/runs", json={})

    before = c.get("/skills/coverage?capability=fobo").json()
    gapped = [r for r in before if float(r["coverage"] or 0) < 1.0]
    assert gapped, "expected at least one partially-covered skill to fix"
    target, gap = gapped[0]["skill_name"], gapped[0]["top_gap"]
    n_uncovered_before = len(c.get("/skills/uncovered?capability=fobo").json())
    assert n_uncovered_before > 0

    # the fix the tool itself prints, applied as a capability-local skill file
    c.post("/capabilities/fobo/skills", json={
        "filename": f"{target}.md",
        "content": f'---\nname: {target}\ndescription: local\n'
                   f'example_prompts:\n  - "{gap}"\n---\n',
    })
    c.post("/capabilities/fobo/runs", json={"replace_today": True})

    after = {r["skill_name"]: float(r["coverage"] or 0) for r
             in c.get("/skills/coverage?capability=fobo").json()}
    assert after[target] == 1.0, f"{target} should be fully covered after the upload"
    assert len(c.get("/skills/uncovered?capability=fobo").json()) < n_uncovered_before


def test_coverage_without_capability_stays_global(ctx) -> None:
    """?capability= scopes; omitting it must still answer from the global tables."""
    c, _ = ctx
    c.post("/demo/seed")
    c.post("/analyze/run")
    c.post("/capabilities/fobo/runs", json={})
    glob = c.get("/skills/coverage").json()
    scoped = c.get("/skills/coverage?capability=fobo").json()
    assert len(glob) > len(scoped)  # the capability filter is narrower than everything


def test_scoped_coverage_before_any_run_is_empty(ctx) -> None:
    c, _ = ctx
    assert c.get("/skills/coverage?capability=fobo").json() == []
    assert c.get("/skills/uncovered?capability=fobo").json() == []


def test_scoped_coverage_unknown_capability_404(ctx) -> None:
    c, _ = ctx
    c.post("/demo/seed")
    c.post("/capabilities/fobo/runs", json={})
    assert c.get("/skills/coverage?capability=ghost").status_code == 404


def test_scoped_gaps_are_narrower_than_global(ctx) -> None:
    """Proposed NEW skills must come from this capability's run, not the whole DB."""
    c, _ = ctx
    c.post("/demo/seed")
    c.post("/analyze/run")
    c.post("/capabilities/fobo/runs", json={})
    glob = c.get("/skills/gaps").json()
    scoped = c.get("/skills/gaps?capability=fobo").json()
    assert glob, "the demo corpus should propose something globally"
    assert len(scoped) < len(glob)
    # and every scoped proposal has the columns the global one has
    if scoped:
        assert set(scoped[0]) == set(glob[0])


def test_scoped_gaps_edge_cases(ctx) -> None:
    c, _ = ctx
    assert c.get("/skills/gaps?capability=fobo").json() == []      # no run yet
    c.post("/demo/seed")
    c.post("/capabilities/fobo/runs", json={})
    assert c.get("/skills/gaps?capability=ghost").status_code == 404


def test_multi_asset_cluster_is_not_proposed_as_an_asset_class_skill(ctx) -> None:
    """The guard `asset_classes` exists for: one pattern asked on FX and rates and
    credit is a capability/global skill, not an FX one. It only works because the
    run snapshot persists the asset classes."""
    from phoenix_scraper.models import SpanRecord
    from phoenix_scraper.storage import Store

    c, settings = ctx
    base = datetime(2026, 9, 1, 9, tzinfo=UTC)
    with Store(settings.db_path) as store:
        store.upsert_spans([
            SpanRecord(
                span_id=f"ma-{i:03d}", trace_id=f"ma-t{i}", session_id=f"ma-s{i}",
                project="pnl-agent", span_kind="LLM",
                start_time=base + timedelta(minutes=i),
                workflow_stage="fobo_recon",
                asset_class=["fx", "rates", "credit"][i % 3],
                user_id=f"analyst-{i % 5}",
                input_text="explain the zzz widget variance for the desk",
                output_text="Because of a zzz widget.",
            )
            for i in range(12)
        ])
    c.post("/capabilities/fobo/runs", json={})

    with Store(settings.db_path) as store:
        run_id = store.previous_capability_run_id("fobo")
        snap = store.capability_run_snapshot_frame("fobo", run_id)
    row = snap[snap["representative"].str.contains("zzz widget", na=False)]
    assert not row.empty, "the multi-asset cluster should be in the snapshot"
    assert set(json.loads(row.iloc[0]["asset_classes"])) == {"fx", "rates", "credit"}

    proposals = c.get("/skills/gaps?capability=fobo").json()
    zzz = [p for p in proposals if "zzz widget" in str(p["representative_prompt"])]
    if zzz:  # only asserted when it did surface as a proposal
        assert zzz[0]["level"] != "asset_class", (
            "asked across fx/rates/credit — must not be labelled an asset-class skill"
        )


def test_asset_classes_column_is_added_to_an_existing_db(tmp_path: Path) -> None:
    """Existing DBs predate the column; CREATE TABLE IF NOT EXISTS won't add it."""
    import sqlite3

    from phoenix_scraper.storage import Store

    db = tmp_path / "old.db"
    with Store(db):
        pass
    raw = sqlite3.connect(db)
    raw.execute("ALTER TABLE capability_cluster_snapshots DROP COLUMN asset_classes")
    raw.commit()
    cols = {r[1] for r in raw.execute("PRAGMA table_info(capability_cluster_snapshots)")}
    assert "asset_classes" not in cols
    raw.close()

    with Store(db) as store:  # reopening migrates it
        cols = {
            r["name"] for r in
            store._conn.execute("PRAGMA table_info(capability_cluster_snapshots)")
        }
    assert "asset_classes" in cols


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
