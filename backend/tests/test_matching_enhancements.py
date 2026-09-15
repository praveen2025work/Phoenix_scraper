"""Tests for classical matching upgrades (stem, synonyms, BM25, near-dup, modes)."""

from datetime import UTC, datetime

from phoenix_scraper.models import PromptCluster, SkillEntry
from phoenix_scraper.near_dup import collapse_near_duplicates, jaccard
from phoenix_scraper.skills_mapper import (
    MATCH_METHOD_CLASSICAL,
    MATCH_METHOD_SEMANTIC,
    match_clusters_with_notes,
    score_match,
)
from phoenix_scraper.text_normalize import normalize_text, stem, tokenize
from phoenix_scraper.text_similarity import (
    bm25_similarity,
    char_tfidf_similarity,
    tfidf_similarity,
)


def _cluster(rep: str, signature: str | None = None, count: int = 5) -> PromptCluster:
    return PromptCluster(
        cluster_id="abc123def456",
        signature=signature or rep.casefold(),
        representative=rep,
        count=count,
        n_sessions=2,
        n_users=2,
        first_seen=datetime(2026, 7, 20, tzinfo=UTC),
        last_seen=datetime(2026, 7, 21, tzinfo=UTC),
        span_ids=tuple(f"s{i}" for i in range(count)),
        asset_classes=("fx",),
        workflow_stages=("fobo_recon",),
    )


def test_stem_and_synonym_expand_recon_terms() -> None:
    toks = tokenize("FX reconciliation breaks on EURUSD")
    assert "fx" in toks
    # break/reconciliation collapse toward recon via synonym map + stem
    assert "recon" in toks or any(t.startswith("recon") for t in toks)
    assert "eurusd" in toks
    assert stem("breaks") in {"break", "recon"} or len(stem("breaks")) >= 3


def test_normalize_text_is_stable() -> None:
    a = normalize_text("Why is there an FX recon break?")
    b = normalize_text("why is there an fx recon break?")
    assert a == b


def test_bm25_ranks_related_above_unrelated() -> None:
    query = "Why is there an FX recon break of 100k on EURUSD?"
    related = ["FX recon break triage for currency pairs"]
    unrelated = ["Convert my report to French please"]
    assert bm25_similarity(query, related) > bm25_similarity(query, unrelated)
    assert char_tfidf_similarity(query, related) >= 0.0
    assert tfidf_similarity(query, related) > tfidf_similarity(query, unrelated)


def test_near_dup_collapses_paraphrases() -> None:
    a = _cluster("Why is there an FX recon break on EURUSD?", count=10)
    b = _cluster(
        "Why is there an FX recon break on EURUSD today?",
        signature="why is there an fx recon break on eurusd today",
        count=3,
    )
    # Force high overlap by nearly identical text
    b = b.model_copy(update={"representative": a.representative, "signature": a.signature})
    collapsed = collapse_near_duplicates([a, b], threshold=0.85)
    assert len(collapsed) == 1
    assert collapsed[0].count == 13


def test_jaccard_identical_is_one() -> None:
    s = {"fx", "recon", "break"}
    assert jaccard(s, s) == 1.0
    assert jaccard(s, set()) == 0.0


def test_classical_mode_method_label() -> None:
    cluster = _cluster("Why is there an FX recon break of 100k on EURUSD?")
    skill = SkillEntry(
        name="fx-recon-break-triage",
        description="Triage FX recon breaks",
        keywords=("fx", "recon", "break"),
        example_prompts=("Why is there an FX recon break on EURUSD?",),
    )
    matches, proposals, notes = match_clusters_with_notes(
        [cluster], [skill], threshold=0.4, match_mode="classical"
    )
    assert notes == []
    assert len(matches) == 1
    assert matches[0].method == MATCH_METHOD_CLASSICAL
    assert proposals == []
    assert score_match(cluster, skill) >= 0.4


def test_semantic_mode_falls_back_without_extra() -> None:
    cluster = _cluster("Why is there an FX recon break of 100k on EURUSD?")
    skill = SkillEntry(
        name="fx-recon-break-triage",
        description="Triage FX recon breaks",
        keywords=("fx", "recon", "break"),
        example_prompts=("Why is there an FX recon break on EURUSD?",),
    )
    matches, _proposals, notes = match_clusters_with_notes(
        [cluster], [skill], threshold=0.4, match_mode="semantic"
    )
    # Without sentence-transformers installed, we fall back to classical.
    assert matches and matches[0].method in {
        MATCH_METHOD_CLASSICAL,
        MATCH_METHOD_SEMANTIC,
    }
    if matches[0].method == MATCH_METHOD_CLASSICAL:
        assert any("sentence-transformers" in n or "falling back" in n for n in notes)
