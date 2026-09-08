"""Rung-1 artifact rendering + promote."""

from datetime import UTC, date, datetime, timedelta

import pytest

from phoenix_scraper import artifacts
from phoenix_scraper import capability as cap_mod
from phoenix_scraper.models import Candidate, CapabilityFilter, SkillEntry, SpanRecord

TS = datetime(2026, 9, 8, 12, tzinfo=UTC)


def _capability():
    return cap_mod.Capability(
        id="fobo", name="FOBO", filter=CapabilityFilter(workflow_stage="fobo_recon"),
    )


def _cand(subtype="new_skill", **over) -> Candidate:
    base = dict(
        candidate_id="fobo:s:abc123", capability_id="fobo", rung="skill",
        subtype=subtype, cluster_id="abc123",
        title="why is there a recon break of 100k on the credit book",
        signature="why recon break of <num> on <book>",
        matched_skill="fobo-triage" if subtype == "strengthen_skill" else None,
        status="accepted", first_seen_run_id="r1", first_seen_at=TS,
        last_seen_run_id="r6", last_seen_at=TS,
        current_evidence={"count": 214, "n_users": 7},
    )
    base.update(over)
    return Candidate(**base)


class TestRendering:
    def test_slugify(self) -> None:
        assert artifacts.slugify("Recon Break Explain!") == "recon-break-explain"

    def test_dedupe_path(self, tmp_path) -> None:
        (tmp_path / "x.md").write_text("", encoding="utf-8")
        assert artifacts.dedupe_path(tmp_path, "x").name == "x-2.md"

    def test_new_skill_md_has_frontmatter_and_scaffold(self) -> None:
        name, md = artifacts.render_new_skill_md(
            _cand(), capability=_capability(), member_prompts=[
                "why is there a recon break of 100k on the credit book",
                "explain the fx recon break on EURUSD_LDN",
            ], today=date(2026, 9, 8),
        )
        assert name.endswith(".md")
        assert "status: draft" in md
        assert "source_candidate: fobo:s:abc123" in md
        assert "## Procedure" in md and "1. TODO" in md
        assert "example_prompts:" in md

    def test_strengthen_block_targets_the_matched_skill(self) -> None:
        skill = SkillEntry(name="fobo-triage", description="Triage recon breaks.",
                           example_prompts=("existing one",), source="skill_md",
                           path="capabilities/fobo/skills/fobo-triage.md")
        target, block = artifacts.render_strengthen_block(
            _cand("strengthen_skill"), skill,
            member_prompts=["why is there a recon break of 100k on the credit book"],
            member_signatures=["why recon break of <num> on <book>"],
        )
        assert target == "capabilities/fobo/skills/fobo-triage.md"
        assert "```yaml" in block and "example_prompts:" in block


class TestPromote:
    @pytest.fixture()
    def wired(self, seeded_store, tmp_path, settings):
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "fobo", cap_filter=CapabilityFilter(workflow_stage="fobo_recon")
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        base = datetime(2026, 7, 20, 9, tzinfo=UTC)
        seeded_store.upsert_spans([
            SpanRecord(
                span_id=f"unc-{i:03d}", trace_id=f"unc-t{i}", session_id=f"unc-s{i}",
                project="pnl-agent", span_kind="LLM",
                start_time=base + timedelta(minutes=i),
                workflow_stage="fobo_recon", asset_class="fx",
                user_id=f"analyst-{i % 4}",
                input_text="Walk me through the xyzzy quux adjustment posting workflow",
                output_text="Steps ...",
            )
            for i in range(8)
        ])
        from phoenix_scraper.capability_run import run_capability_analysis
        run_capability_analysis(seeded_store, s, cap,
                                now=datetime(2026, 7, 21, 12, tzinfo=UTC))
        cid = seeded_store.candidates_frame("fobo", rung="skill").iloc[0]["candidate_id"]
        cand = seeded_store.get_candidate(cid).model_copy(update={"status": "accepted"})
        seeded_store.upsert_candidate(cand)
        return seeded_store, s, cap, cand

    def test_promote_new_skill_writes_a_draft_file(self, wired) -> None:
        store, s, cap, cand = wired
        result = artifacts.promote_candidate(store, cap, cand, now=TS, actor="alice",
                                             settings=s)
        assert result.wrote_files is True
        assert len(result.paths) == 1
        from pathlib import Path
        written = Path(result.paths[0])
        assert written.exists() and written.parent.name == "skills"
        assert store.get_candidate(cand.candidate_id).status == "promoted"
        decisions = store.candidate_decisions_frame(cand.candidate_id)
        assert "promote" in list(decisions["action"])

    def test_dry_run_writes_nothing(self, wired) -> None:
        store, s, cap, cand = wired
        result = artifacts.promote_candidate(store, cap, cand, now=TS, actor="a",
                                             settings=s, dry_run=True)
        assert result.wrote_files is False
        assert store.get_candidate(cand.candidate_id).status == "accepted"
