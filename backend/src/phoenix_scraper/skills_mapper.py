"""Match prompt clusters to catalog skills; propose new skills for uncovered clusters.

Classical ensemble: keyword + rapidfuzz + BM25/TF-IDF/char-n-grams, with optional
local MiniLM assist when match_mode=semantic. No generative LLM.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from .models import PromptCluster, SkillEntry, SkillGapProposal, SkillMatch
from .near_dup import collapse_near_duplicates
from .semantic_match import last_load_error, semantic_available, semantic_similarity
from .skills import distinctive_words
from .taxonomy import suggest_level
from .text_normalize import normalize_text
from .text_similarity import (
    bm25_similarity,
    char_tfidf_similarity,
    tfidf_similarity,
)

MATCH_METHOD_CLASSICAL = "keyword+fuzzy+bm25+tfidf"
MATCH_METHOD_SEMANTIC = "keyword+fuzzy+bm25+tfidf+semantic"
MATCH_METHOD = MATCH_METHOD_CLASSICAL  # back-compat for tests
_PLACEHOLDER_TOKENS = frozenset({"num", "date", "ccy", "book", "desk", "id"})
_NAME_STOPWORDS = frozenset({
    "there", "why", "is", "are", "was", "were", "an", "a", "the", "for", "on",
    "of", "to", "in", "at", "with", "can", "you", "your", "please", "do",
    "does", "how", "what", "when", "which", "my", "our", "me", "over", "above",
})
_PROPOSED_NAME_WORDS = 4
_SAMPLE_SPAN_LIMIT = 5


def _skill_refs(skill: SkillEntry) -> list[str]:
    return [p for p in (*skill.example_prompts, skill.description) if p]


def _keyword_ratio(cluster: PromptCluster, skill: SkillEntry) -> float:
    if not skill.keywords:
        return 0.0
    haystack = normalize_text(f"{cluster.signature} {cluster.representative}")
    hits = sum(1 for kw in skill.keywords if normalize_text(kw) in haystack)
    return hits / len(skill.keywords)


def _fuzzy_ratio(cluster: PromptCluster, skill: SkillEntry) -> float:
    references = _skill_refs(skill)
    if not references:
        return 0.0
    best = max(
        fuzz.token_set_ratio(cluster.representative, ref) for ref in references
    )
    return best / 100.0


def _lexical_ratio(cluster: PromptCluster, skill: SkillEntry) -> float:
    references = _skill_refs(skill)
    if not references:
        return 0.0
    query = cluster.representative
    return (
        0.40 * bm25_similarity(query, references)
        + 0.35 * tfidf_similarity(query, references)
        + 0.25 * char_tfidf_similarity(query, references)
    )


def score_match(
    cluster: PromptCluster,
    skill: SkillEntry,
    *,
    match_mode: str = "classical",
    semantic_model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> float:
    """Combined 0-1 score. match_mode=semantic blends in local MiniLM cosine."""
    classical = (
        0.20 * _keyword_ratio(cluster, skill)
        + 0.25 * _fuzzy_ratio(cluster, skill)
        + 0.55 * _lexical_ratio(cluster, skill)
    )
    if match_mode != "semantic":
        return classical
    refs = _skill_refs(skill)
    if not refs:
        return classical
    sem = semantic_similarity(
        cluster.representative, refs, model_name=semantic_model
    )
    return 0.70 * classical + 0.30 * sem


def _proposed_name(cluster: PromptCluster) -> str:
    words = [
        w
        for w in distinctive_words(cluster.signature or cluster.representative)
        if w not in _PLACEHOLDER_TOKENS and w not in _NAME_STOPWORDS
    ]
    if not words:
        return f"skill-{cluster.cluster_id}"
    return "-".join(words[:_PROPOSED_NAME_WORDS])


def _description(count: int, scope: str, representative: str) -> str:
    return (
        f'Proposed skill covering {count} similar prompts ({scope}), '
        f'e.g. "{representative}".'
    )


def _build_proposal(cluster: PromptCluster) -> SkillGapProposal:
    level, asset_class, capability = suggest_level(cluster.representative)
    distinct_asset_classes = {ac for ac in cluster.asset_classes if ac}
    if level == "asset_class" and len(distinct_asset_classes) > 1:
        level, asset_class = ("capability", None) if capability else ("global", None)
    scope = asset_class or capability or "all desks"
    description = _description(cluster.count, scope, cluster.representative)
    return SkillGapProposal(
        cluster_id=cluster.cluster_id,
        proposed_name=_proposed_name(cluster),
        level=level,
        asset_class=asset_class,
        capability=capability,
        description=description,
        evidence_count=cluster.count,
        representative_prompt=cluster.representative,
        sample_span_ids=cluster.span_ids[:_SAMPLE_SPAN_LIMIT],
    )


def match_clusters(
    clusters: list[PromptCluster],
    skills: list[SkillEntry],
    threshold: float = 0.55,
    min_evidence: int = 2,
    *,
    match_mode: str = "classical",
    semantic_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    collapse_duplicates: bool = True,
) -> tuple[list[SkillMatch], list[SkillGapProposal]]:
    """Best-scoring skill per cluster above threshold -> SkillMatch; otherwise a
    SkillGapProposal when the cluster has at least min_evidence occurrences.
    """
    matches, proposals, _notes = match_clusters_with_notes(
        clusters,
        skills,
        threshold=threshold,
        min_evidence=min_evidence,
        match_mode=match_mode,
        semantic_model=semantic_model,
        collapse_duplicates=collapse_duplicates,
    )
    return matches, proposals


def match_clusters_with_notes(
    clusters: list[PromptCluster],
    skills: list[SkillEntry],
    threshold: float = 0.55,
    min_evidence: int = 2,
    *,
    match_mode: str = "classical",
    semantic_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    collapse_duplicates: bool = True,
) -> tuple[list[SkillMatch], list[SkillGapProposal], list[str]]:
    """Like match_clusters, plus operator notes (e.g. semantic fallback)."""
    notes: list[str] = []
    mode = (match_mode or "classical").strip().lower()
    if mode not in {"classical", "semantic"}:
        notes.append(f"unknown match_mode={match_mode!r}; using classical")
        mode = "classical"
    if mode == "semantic" and not semantic_available():
        notes.append(
            "semantic match requested but sentence-transformers is not installed; "
            "falling back to classical (pip install 'phoenix-scraper[semantic]')"
        )
        mode = "classical"
    method = MATCH_METHOD_SEMANTIC if mode == "semantic" else MATCH_METHOD_CLASSICAL

    work = (
        collapse_near_duplicates(clusters) if collapse_duplicates else list(clusters)
    )

    matches: list[SkillMatch] = []
    proposals: list[SkillGapProposal] = []
    for cluster in work:
        scored = [
            (
                score_match(
                    cluster, skill, match_mode=mode, semantic_model=semantic_model
                ),
                skill,
            )
            for skill in skills
        ]
        best_score, best_skill = max(
            scored, key=lambda pair: pair[0], default=(0.0, None)
        )
        if best_skill is not None and best_score >= threshold:
            matches.append(
                SkillMatch(
                    cluster_id=cluster.cluster_id,
                    skill_name=best_skill.name,
                    score=round(best_score, 4),
                    method=method,
                )
            )
        elif cluster.count >= min_evidence:
            proposals.append(_build_proposal(cluster))

    err = last_load_error()
    if mode == "semantic" and err:
        notes.append(
            f"semantic model load issue ({err}); "
            "scores may have used classical-only blend where encode failed"
        )
    return matches, _dedupe_proposals(proposals), notes


def _dedupe_proposals(proposals: list[SkillGapProposal]) -> list[SkillGapProposal]:
    """Merge proposals sharing a proposed_name: evidence sums, strongest cluster leads."""
    by_name: dict[str, SkillGapProposal] = {}
    for proposal in proposals:
        existing = by_name.get(proposal.proposed_name)
        if existing is None:
            by_name[proposal.proposed_name] = proposal
            continue
        primary, secondary = (
            (existing, proposal)
            if existing.evidence_count >= proposal.evidence_count
            else (proposal, existing)
        )
        total = existing.evidence_count + proposal.evidence_count
        scope = primary.asset_class or primary.capability or "all desks"
        by_name[proposal.proposed_name] = primary.model_copy(
            update={
                "evidence_count": total,
                "sample_span_ids": (
                    *primary.sample_span_ids,
                    *secondary.sample_span_ids,
                )[:_SAMPLE_SPAN_LIMIT],
                "description": _description(
                    total, scope, primary.representative_prompt
                ),
            }
        )
    return sorted(by_name.values(), key=lambda p: p.evidence_count, reverse=True)
