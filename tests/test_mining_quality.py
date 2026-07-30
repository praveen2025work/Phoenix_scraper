"""Regression tests for mining-quality fixes: book/desk masking and proposal dedupe."""

from phoenix_scraper.models import PromptCluster, SkillGapProposal
from phoenix_scraper.normalize import normalize_prompt, prompt_signature
from phoenix_scraper.skills_mapper import _dedupe_proposals, _proposed_name, match_clusters


class TestBookMasking:
    def test_book_codes_masked(self):
        assert "<book>" in normalize_prompt("Recon break on EQ_DELTA1_NY today")
        assert "<book>" in normalize_prompt("List trades for BUNDS_FFT")

    def test_numeric_reference_ids_still_ids(self):
        assert "<id>" in normalize_prompt("Check ticket TRD_998877")
        assert "<book>" not in normalize_prompt("Check ticket TRD_998877")

    def test_book_variants_share_signature(self):
        a = prompt_signature("List unmatched FOBO trades over 25k for IRS_USD_NY")
        b = prompt_signature("List unmatched FOBO trades over 120k for BONDS_EM_LDN")
        c = prompt_signature("List unmatched FOBO trades over 150k for BUNDS_FFT")
        assert a == b == c

    def test_bare_ccy_pair_still_ccy(self):
        assert "<ccy>" in normalize_prompt("Why is there a break on EURUSD?")


class TestDeskMasking:
    def test_desk_variants_share_signature(self):
        a = prompt_signature("Is the rates desk ready for sign-off on 2026-07-20?")
        b = prompt_signature("Is the credit desk ready for sign-off on 2026-07-21?")
        assert a == b
        assert "<desk>" in a

    def test_non_desk_asset_mentions_unmasked(self):
        assert "fx" in prompt_signature("Run PLEX attribution for FX")


class TestProposalQuality:
    @staticmethod
    def _cluster(cluster_id: str, signature: str, representative: str, count: int) -> PromptCluster:
        return PromptCluster(
            cluster_id=cluster_id,
            signature=signature,
            representative=representative,
            count=count,
            span_ids=tuple(f"{cluster_id}-s{i}" for i in range(3)),
        )

    def test_names_free_of_stopwords_and_placeholders(self):
        cluster = self._cluster(
            "abc123def456",
            "why is there an equities recon break of <num> on <book>",
            "Why is there an equities recon break of 210k on EQ_DELTA1_NY?",
            18,
        )
        name = _proposed_name(cluster)
        for banned in ("there", "why", "is", "num", "book"):
            assert banned not in name.split("-")

    def test_duplicate_proposals_merged(self):
        clusters = [
            self._cluster("c1", "list unmatched fobo trades over <num> for <book>",
                          "List unmatched FOBO trades over 25k for IRS_USD_NY", 8),
            self._cluster("c2", "list unmatched fobo trades over <num> for <book>",
                          "List unmatched FOBO trades over 120k for BONDS_EM_LDN", 6),
        ]
        _, proposals = match_clusters(clusters, skills=[], threshold=0.55, min_evidence=2)
        assert len(proposals) == 1
        merged = proposals[0]
        assert merged.evidence_count == 14
        assert merged.representative_prompt.endswith("IRS_USD_NY")
        assert "14 similar prompts" in merged.description

    def test_multi_asset_cluster_not_slotted_at_asset_class_level(self):
        cluster = PromptCluster(
            cluster_id="c9",
            signature="why is there an credit recon break of <num> on <book>",
            representative="Why is there an credit recon break of 75k on CDS_IG_NY?",
            count=44,
            asset_classes=("credit", "equities", "fx", "rates"),
            span_ids=("s1", "s2"),
        )
        _, proposals = match_clusters([cluster], skills=[], threshold=0.55, min_evidence=2)
        assert proposals[0].level == "capability"
        assert proposals[0].asset_class is None

    def test_single_asset_cluster_keeps_asset_class_level(self):
        cluster = PromptCluster(
            cluster_id="c8",
            signature="why is there an fx recon break of <num> on <book>",
            representative="Why is there an FX recon break of 300k on USDJPY_NY?",
            count=7,
            asset_classes=("fx",),
            span_ids=("s1",),
        )
        _, proposals = match_clusters([cluster], skills=[], threshold=0.55, min_evidence=2)
        assert proposals[0].level == "asset_class"
        assert proposals[0].asset_class == "fx"

    def test_dedupe_keeps_distinct_names(self):
        p1 = SkillGapProposal(
            cluster_id="c1", proposed_name="alpha", level="global",
            description="d", evidence_count=3, representative_prompt="r1",
        )
        p2 = SkillGapProposal(
            cluster_id="c2", proposed_name="beta", level="global",
            description="d", evidence_count=5, representative_prompt="r2",
        )
        result = _dedupe_proposals([p1, p2])
        assert [p.proposed_name for p in result] == ["beta", "alpha"]
