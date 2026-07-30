"""Match prompt clusters to catalog skills; propose new skills for uncovered clusters."""

from rapidfuzz import fuzz

from .models import PromptCluster, SkillEntry, SkillGapProposal, SkillMatch
from .skills import distinctive_words
from .taxonomy import suggest_level

MATCH_METHOD = "keyword+fuzzy"
_PLACEHOLDER_TOKENS = frozenset({"num", "date", "ccy", "book", "desk", "id"})
_NAME_STOPWORDS = frozenset({
    "there", "why", "is", "are", "was", "were", "an", "a", "the", "for", "on",
    "of", "to", "in", "at", "with", "can", "you", "your", "please", "do",
    "does", "how", "what", "when", "which", "my", "our", "me", "over", "above",
})
_PROPOSED_NAME_WORDS = 4
_SAMPLE_SPAN_LIMIT = 5


def _keyword_ratio(cluster: PromptCluster, skill: SkillEntry) -> float:
    if not skill.keywords:
        return 0.0
    haystack = f"{cluster.signature} {cluster.representative}".casefold()
    hits = sum(1 for kw in skill.keywords if kw.casefold() in haystack)
    return hits / len(skill.keywords)


def _fuzzy_ratio(cluster: PromptCluster, skill: SkillEntry) -> float:
    references = [p for p in (*skill.example_prompts, skill.description) if p]
    if not references:
        return 0.0
    best = max(
        fuzz.token_set_ratio(cluster.representative, ref) for ref in references
    )
    return best / 100.0


def score_match(cluster: PromptCluster, skill: SkillEntry) -> float:
    """Combined 0-1 score: half keyword coverage, half best fuzzy similarity."""
    return 0.5 * _keyword_ratio(cluster, skill) + 0.5 * _fuzzy_ratio(cluster, skill)


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
    return f'Proposed skill covering {count} similar prompts ({scope}), e.g. "{representative}".'


def _build_proposal(cluster: PromptCluster) -> SkillGapProposal:
    level, asset_class, capability = suggest_level(cluster.representative)
    # A cluster observed across multiple asset classes is not an asset-class skill,
    # whatever its representative prompt happens to mention.
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
) -> tuple[list[SkillMatch], list[SkillGapProposal]]:
    """Best-scoring skill per cluster above threshold -> SkillMatch; otherwise a
    SkillGapProposal when the cluster has at least min_evidence occurrences."""
    matches: list[SkillMatch] = []
    proposals: list[SkillGapProposal] = []
    for cluster in clusters:
        scored = [(score_match(cluster, skill), skill) for skill in skills]
        best_score, best_skill = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        if best_skill is not None and best_score >= threshold:
            matches.append(
                SkillMatch(
                    cluster_id=cluster.cluster_id,
                    skill_name=best_skill.name,
                    score=round(best_score, 4),
                    method=MATCH_METHOD,
                )
            )
        elif cluster.count >= min_evidence:
            proposals.append(_build_proposal(cluster))
    return matches, _dedupe_proposals(proposals)


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
                "description": _description(total, scope, primary.representative_prompt),
            }
        )
    return sorted(by_name.values(), key=lambda p: p.evidence_count, reverse=True)
