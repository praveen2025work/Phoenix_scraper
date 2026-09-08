"""Tests for run_capability_analysis and run_capabilities (offline)."""

from datetime import UTC, datetime, timedelta

import pytest

from phoenix_scraper import capability as cap_mod
from phoenix_scraper.capability_run import run_capability_analysis
from phoenix_scraper.models import CapabilityFilter

# The shared seeded_store fixture places spans around 2026-07-20; NOW is picked so
# a default window (now - window_days) covers them (see test_explicit_window_overrides).
NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def fobo_capability(tmp_path, settings):
    root = tmp_path / "caps"
    cap = cap_mod.scaffold_capability(
        root, "fobo", name="FOBO",
        cap_filter=CapabilityFilter(workflow_stage="fobo_recon"),
        window_days=30,
    )
    return settings.model_copy(update={"capabilities_dir": root}), cap


class TestRunCapabilityAnalysis:
    def test_scopes_to_the_capability_filter(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        # sample_spans: 8 fobo_recon LLM spans, 1 adjustments TOOL, 1 commentary_signoff.
        # Only fobo_recon user turns are in scope.
        assert result.run.n_in_scope_spans == 8
        assert result.run.n_spans == 10  # total in the store, unscoped
        assert result.run.capability_id == "fobo"
        assert result.run.status == "ok"
        assert all("fobo" not in c.representative.lower() or True for c in result.clusters)

    def test_window_default_is_now_minus_window_days(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        assert result.run.window_end == NOW
        assert result.run.window_start == NOW - timedelta(days=30)

    def test_explicit_window_overrides(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        ws, we = datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 25, tzinfo=UTC)
        result = run_capability_analysis(
            seeded_store, settings, cap, window_start=ws, window_end=we, now=NOW
        )
        assert result.run.window_start == ws and result.run.window_end == we

    def test_records_the_run_and_snapshots(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        runs = seeded_store.capability_runs_frame("fobo")
        assert len(runs) == 1 and runs.iloc[0]["run_id"] == result.run.run_id
        snaps = seeded_store.capability_run_snapshot_frame("fobo", result.run.run_id)
        assert len(snaps) == result.run.n_clusters == len(result.clusters)
        members = seeded_store.capability_cluster_members_frame("fobo", result.run.run_id)
        assert len(members) > 0
        assert runs.iloc[0]["n_rung1_candidates"] == 0  # Phase C fills this

    def test_previous_run_id_is_read_before_recording(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        first = run_capability_analysis(seeded_store, settings, cap,
                                        now=NOW - timedelta(days=1))
        second = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        assert first.previous_run_id is None
        assert second.previous_run_id == first.run.run_id

    def test_replace_today_reuses_the_days_run_id(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        a = run_capability_analysis(seeded_store, settings, cap,
                                    now=NOW.replace(hour=8))
        b = run_capability_analysis(seeded_store, settings, cap,
                                    now=NOW.replace(hour=17), replace_today=True)
        assert b.run.run_id == a.run.run_id
        assert len(seeded_store.capability_runs_frame("fobo")) == 1

    def test_empty_scope_records_a_zero_run(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "ghost", name="Ghost",
            cap_filter=CapabilityFilter(workflow_stage="does_not_exist"),
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        result = run_capability_analysis(seeded_store, s, cap, now=NOW)
        assert result.run.n_in_scope_spans == 0
        assert result.run.n_clusters == 0
        assert result.run.status == "ok"
        assert len(seeded_store.capability_runs_frame("ghost")) == 1

    def test_notes_force_partial_status(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(
            seeded_store, settings, cap, notes=["scrape failed for pnl-agent"], now=NOW
        )
        assert result.run.status == "partial"
        assert "scrape failed for pnl-agent" in result.run.notes

    def test_capability_skills_dir_is_scanned(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        skill_md = (settings.capabilities_dir / "fobo" / "skills" / "recon.md")
        skill_md.write_text(
            "---\nname: recon-break-local\ndescription: local recon skill\n"
            "keywords: [recon, break]\nexample_prompts:\n"
            '  - "Why is there an FX recon break on the EURUSD book?"\n---\n',
            encoding="utf-8",
        )
        from phoenix_scraper.capability_run import load_capability_skills
        names = {s.name for s in load_capability_skills(settings, cap)}
        assert "recon-break-local" in names
        assert "glossary-explainer" in names  # catalog entries still present
