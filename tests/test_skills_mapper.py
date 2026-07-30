"""Tests for cluster -> skill matching and gap proposal generation."""

from datetime import UTC, datetime
from pathlib import Path

from phoenix_scraper.models import PromptCluster, SkillEntry, SkillGapProposal, SkillMatch
from phoenix_scraper.skills import load_catalog
from phoenix_scraper.skills_mapper import match_clusters, score_match

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = load_catalog(REPO_ROOT / "config" / "skills_catalog.yaml")


def make_cluster(
    signature: str,
    representative: str,
    count: int = 5,
    cluster_id: str = "abc123def456",
    span_ids: tuple[str, ...] = tuple(f"span-{i:04d}" for i in range(8)),
) -> PromptCluster:
    return PromptCluster(
        cluster_id=cluster_id,
        signature=signature,
        representative=representative,
        count=count,
        n_sessions=2,
        n_users=2,
        first_seen=datetime(2026, 7, 20, tzinfo=UTC),
        last_seen=datetime(2026, 7, 21, tzinfo=UTC),
        span_ids=span_ids,
        asset_classes=("fx",),
        workflow_stages=("fobo_recon",),
    )


FX_RECON_CLUSTER = make_cluster(
    signature="why is there an fx recon break of <num>k on <ccy>",
    representative="Why is there an FX recon break of 100k on EURUSD?",
)
FRENCH_CLUSTER = make_cluster(
    signature="convert my report to french",
    representative="Convert my report to french",
    cluster_id="fefe00112233",
)


class TestScoreMatch:
    def test_score_between_zero_and_one(self) -> None:
        for skill in CATALOG:
            score = score_match(FX_RECON_CLUSTER, skill)
            assert 0.0 <= score <= 1.0

    def test_relevant_skill_scores_high(self) -> None:
        triage = next(s for s in CATALOG if s.name == "fx-recon-break-triage")
        assert score_match(FX_RECON_CLUSTER, triage) >= 0.55

    def test_irrelevant_skill_scores_low(self) -> None:
        glossary = next(s for s in CATALOG if s.name == "glossary-explainer")
        assert score_match(FRENCH_CLUSTER, glossary) < 0.55

    def test_no_keywords_no_examples_scores_zero(self) -> None:
        empty_skill = SkillEntry(name="empty", description="")
        assert score_match(FX_RECON_CLUSTER, empty_skill) == 0.0

    def test_does_not_mutate_inputs(self) -> None:
        triage = next(s for s in CATALOG if s.name == "fx-recon-break-triage")
        before = FX_RECON_CLUSTER.model_copy()
        score_match(FX_RECON_CLUSTER, triage)
        assert FX_RECON_CLUSTER == before


class TestMatchClusters:
    def test_fx_recon_cluster_matches_triage_skill(self) -> None:
        matches, proposals = match_clusters([FX_RECON_CLUSTER], CATALOG)
        assert len(matches) == 1
        match = matches[0]
        assert isinstance(match, SkillMatch)
        assert match.cluster_id == FX_RECON_CLUSTER.cluster_id
        assert match.skill_name == "fx-recon-break-triage"
        assert match.score >= 0.55
        assert match.method == "keyword+fuzzy"
        assert proposals == []

    def test_best_match_only_per_cluster(self) -> None:
        # Several catalog skills mention recon/break; only the single best survives.
        matches, _ = match_clusters([FX_RECON_CLUSTER], CATALOG)
        assert len(matches) == 1

    def test_unmatched_cluster_becomes_gap_proposal(self) -> None:
        matches, proposals = match_clusters([FRENCH_CLUSTER], CATALOG)
        assert matches == []
        assert len(proposals) == 1
        gap = proposals[0]
        assert isinstance(gap, SkillGapProposal)
        assert gap.cluster_id == FRENCH_CLUSTER.cluster_id
        assert gap.level == "global"
        assert gap.asset_class is None
        assert gap.capability is None
        assert gap.evidence_count == FRENCH_CLUSTER.count
        assert gap.representative_prompt == FRENCH_CLUSTER.representative
        assert len(gap.sample_span_ids) == 5
        assert gap.sample_span_ids == FRENCH_CLUSTER.span_ids[:5]
        assert gap.description

    def test_proposal_name_is_kebab_case_from_signature(self) -> None:
        _, proposals = match_clusters([FRENCH_CLUSTER], CATALOG)
        name = proposals[0].proposed_name
        assert name == name.lower()
        assert " " not in name
        assert "convert" in name
        assert "report" in name

    def test_proposal_level_asset_class(self) -> None:
        cluster = make_cluster(
            signature="hedge the fx delta exposure on <ccy> overnight",
            representative="Hedge the FX delta exposure on GBPUSD overnight",
            cluster_id="aa11bb22cc33",
        )
        _, proposals = match_clusters([cluster], skills=[])
        assert len(proposals) == 1
        assert proposals[0].level == "asset_class"
        assert proposals[0].asset_class == "fx"

    def test_min_evidence_filters_thin_clusters(self) -> None:
        thin = make_cluster(
            signature="convert my report to french",
            representative="Convert my report to french",
            count=1,
            cluster_id="0011aabbccdd",
        )
        matches, proposals = match_clusters([thin], CATALOG, min_evidence=2)
        assert matches == []
        assert proposals == []

    def test_min_evidence_boundary_inclusive(self) -> None:
        boundary = make_cluster(
            signature="convert my report to french",
            representative="Convert my report to french",
            count=2,
            cluster_id="0011aabbccdd",
        )
        _, proposals = match_clusters([boundary], CATALOG, min_evidence=2)
        assert len(proposals) == 1

    def test_threshold_is_configurable(self) -> None:
        # An impossible threshold turns every cluster into a proposal.
        matches, proposals = match_clusters([FX_RECON_CLUSTER], CATALOG, threshold=1.01)
        assert matches == []
        assert len(proposals) == 1

    def test_empty_inputs(self) -> None:
        assert match_clusters([], CATALOG) == ([], [])
        matches, proposals = match_clusters([FX_RECON_CLUSTER], [])
        assert matches == []
        assert len(proposals) == 1
