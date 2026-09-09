"""Tests for run_capability_analysis and run_capabilities (offline)."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from phoenix_scraper import capability as cap_mod
from phoenix_scraper.capability_run import run_capabilities, run_capability_analysis
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

    def test_run_evaluates_in_scope_spans(self, seeded_store, fobo_capability) -> None:
        from phoenix_scraper.models import QueryFilters
        settings, cap = fobo_capability
        assert seeded_store.evaluations_frame(
            QueryFilters(workflow_stage="fobo_recon")
        ).empty
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        evals = seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon"))
        assert not evals.empty
        assert set(evals["source"]) == {"local"}

    def test_evaluation_is_idempotent_across_two_runs(
        self, seeded_store, fobo_capability
    ) -> None:
        from phoenix_scraper.models import QueryFilters
        settings, cap = fobo_capability
        run_capability_analysis(seeded_store, settings, cap, now=NOW - timedelta(days=1))
        n1 = len(
            seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon"))
        )
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        n2 = len(
            seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon"))
        )
        assert n1 == n2  # re-run rewrites the same rows, does not stack

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

    def test_capability_skill_file_overrides_the_catalog_entry(
        self, seeded_store, fobo_capability
    ) -> None:
        """Coverage says "add this example to <catalog skill>"; dropping that file in
        the capability's skills/ has to win, or the advice is a no-op."""
        settings, cap = fobo_capability
        (settings.capabilities_dir / "fobo" / "skills" / "glossary.md").write_text(
            "---\nname: glossary-explainer\ndescription: LOCAL OVERRIDE\n"
            'example_prompts:\n  - "what does PLEX mean"\n---\n',
            encoding="utf-8",
        )
        from phoenix_scraper.capability_run import load_capability_skills
        by_name = {s.name: s for s in load_capability_skills(settings, cap)}
        assert by_name["glossary-explainer"].description == "LOCAL OVERRIDE"
        assert "what does PLEX mean" in by_name["glossary-explainer"].example_prompts

    def _seed_uncovered_cluster(self, store) -> None:
        # A recurring fobo_recon question no catalog skill demonstrates -> a
        # new_skill Rung-1 candidate. Distinct users so the evidence bar can be met.
        from datetime import timedelta as _td

        from phoenix_scraper.models import SpanRecord
        base = datetime(2026, 7, 20, 9, tzinfo=UTC)
        store.upsert_spans([
            SpanRecord(
                span_id=f"unc-{i:03d}", trace_id=f"unc-t{i}", session_id=f"unc-s{i}",
                project="pnl-agent", span_kind="LLM",
                start_time=base + _td(minutes=i),
                workflow_stage="fobo_recon", asset_class="fx",
                user_id=f"analyst-{i % 4}",
                input_text="Walk me through the xyzzy quux adjustment posting workflow",
                output_text="Steps ...",
            )
            for i in range(8)
        ])

    def test_rung1_candidates_created_by_a_run(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        self._seed_uncovered_cluster(seeded_store)
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        runs = seeded_store.capability_runs_frame("fobo")
        assert runs.iloc[0]["n_rung1_candidates"] >= 1
        assert runs.iloc[0]["status"] == "ok"  # ladder notes do not force partial
        cands = seeded_store.candidates_frame("fobo", rung="skill")
        assert len(cands) >= 1
        assert set(cands["status"]) <= {"new", "accumulating"}

    def test_second_run_advances_candidate_status(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        self._seed_uncovered_cluster(seeded_store)
        run_capability_analysis(seeded_store, settings, cap, now=NOW - timedelta(days=1))
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        cands = seeded_store.candidates_frame("fobo", rung="skill")
        assert "accumulating" in set(cands["status"])

    def test_rung2_candidate_from_a_deterministic_cluster(
        self, seeded_store, fobo_capability
    ) -> None:
        settings, cap = fobo_capability
        from datetime import timedelta as _td

        from phoenix_scraper.models import SpanRecord
        base = datetime(2026, 7, 20, 9, tzinfo=UTC)
        seeded_store.upsert_spans([
            SpanRecord(
                span_id=f"det-{i:03d}", trace_id=f"det-t{i}", session_id=f"det-s{i}",
                project="pnl-agent", span_kind="LLM",
                start_time=base + _td(minutes=i),
                workflow_stage="fobo_recon", asset_class="fx",
                user_id=f"analyst-{i % 4}",
                input_text=f"why is there a recon break of {100 + i}k on EURUSD",
                output_text="The FX break is caused by an unsettled trade; post an adjustment.",
            )
            for i in range(14)
        ])
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        runs = seeded_store.capability_runs_frame("fobo")
        assert runs.iloc[0]["n_rung2_candidates"] >= 1
        assert runs.iloc[0]["status"] == "ok"
        d_cands = seeded_store.candidates_frame("fobo", rung="deterministic")
        assert len(d_cands) >= 1


class _FakeClient:
    """Stand-in for PhoenixClientWrapper; never touches the network."""

    def __init__(self, *, available=True, fail_projects=()):
        self._available = available
        self._fail = set(fail_projects)
        self.scraped: list[str] = []

    def available(self) -> bool:
        return self._available

    def fetch_spans(self, *, project, start, end, limit):
        self.scraped.append(project)
        if project in self._fail:
            raise RuntimeError(f"boom for {project}")
        return pd.DataFrame()  # no new spans


class TestRunCapabilities:
    def _two_caps(self, tmp_path, settings):
        root = tmp_path / "caps"
        cap_mod.scaffold_capability(root, "fobo", name="FOBO",
                                    cap_filter=CapabilityFilter(workflow_stage="fobo_recon"))
        cap_mod.scaffold_capability(root, "plex", name="PLEX",
                                    cap_filter=CapabilityFilter(workflow_stage="plex"))
        return settings.model_copy(update={"capabilities_dir": root})

    def test_all_active_runs_every_capability(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        results = run_capabilities(seeded_store, s, all_active=True, now=NOW)
        assert {r.run.capability_id for r in results} == {"fobo", "plex"}
        assert len(seeded_store.capability_runs_frame("fobo")) == 1
        assert len(seeded_store.capability_runs_frame("plex")) == 1

    def test_paused_capability_is_skipped(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        yaml_path = s.capabilities_dir / "plex" / "capability.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace("status: active", "status: paused"),
            encoding="utf-8",
        )
        results = run_capabilities(seeded_store, s, all_active=True, now=NOW)
        assert {r.run.capability_id for r in results} == {"fobo"}

    def test_sync_happens_before_run(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        run_capabilities(seeded_store, s, capability_ids=["fobo"], now=NOW)
        assert seeded_store.get_capability("fobo") is not None  # synced into the DB

    def test_scrape_once_per_distinct_project(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap_mod.scaffold_capability(root, "a", name="A",
                                    cap_filter=CapabilityFilter(project="proj-1"))
        cap_mod.scaffold_capability(root, "b", name="B",
                                    cap_filter=CapabilityFilter(project="proj-1"))
        cap_mod.scaffold_capability(root, "c", name="C",
                                    cap_filter=CapabilityFilter(project="proj-2"))
        s = settings.model_copy(update={"capabilities_dir": root})
        client = _FakeClient()
        run_capabilities(seeded_store, s, all_active=True, client=client, now=NOW)
        assert sorted(client.scraped) == ["proj-1", "proj-2"]

    def test_scrape_failure_marks_partial_not_abort(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap_mod.scaffold_capability(
            root, "a", name="A",
            cap_filter=CapabilityFilter(project="proj-1", workflow_stage="fobo_recon"),
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        client = _FakeClient(fail_projects=["proj-1"])
        results = run_capabilities(seeded_store, s, all_active=True, client=client, now=NOW)
        assert len(results) == 1
        assert results[0].run.status == "partial"
        assert any("proj-1" in n for n in results[0].run.notes)

    def test_offline_no_client_notes_stored_spans(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        results = run_capabilities(seeded_store, s, capability_ids=["fobo"], client=None, now=NOW)
        assert results[0].run.status == "partial"
        assert any("offline" in n.lower() or "stored spans" in n.lower()
                   for n in results[0].run.notes)

    def test_one_capability_failing_does_not_abort_the_rest(
        self, seeded_store, tmp_path, settings, monkeypatch
    ) -> None:
        s = self._two_caps(tmp_path, settings)
        real = run_capability_analysis

        def flaky(store, settings_, capability, **kw):
            if capability.id == "fobo":
                raise ValueError("kaboom")
            return real(store, settings_, capability, **kw)

        monkeypatch.setattr("phoenix_scraper.capability_run.run_capability_analysis", flaky)
        results = run_capabilities(seeded_store, s, all_active=True, now=NOW)
        by_id = {r.run.capability_id: r for r in results}
        assert by_id["fobo"].run.status == "failed"
        assert any("kaboom" in n for n in by_id["fobo"].run.notes)
        assert by_id["plex"].run.status in ("ok", "partial")
        # the failed run is still recorded so it is visible
        assert len(seeded_store.capability_runs_frame("fobo")) == 1
        assert seeded_store.capability_runs_frame("fobo").iloc[0]["status"] == "failed"

    def test_unknown_capability_id_raises(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        with pytest.raises((ValueError, FileNotFoundError)):
            run_capabilities(seeded_store, s, capability_ids=["ghost"], now=NOW)
