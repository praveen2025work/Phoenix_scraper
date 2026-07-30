"""End-to-end analysis: spans -> costs -> clusters -> sessions -> skill mapping -> store."""

from datetime import UTC, datetime

from .cluster import build_clusters
from .config import Settings
from .costs import compute_span_costs, load_pricing
from .models import AnalysisResult, QueryFilters
from .sessions import derive_sessions
from .skills import load_all_skills
from .skills_mapper import match_clusters
from .storage import Store

_ANALYSIS_SPAN_LIMIT = 100_000


def run_analysis(
    store: Store, settings: Settings, filters: QueryFilters | None = None
) -> AnalysisResult:
    """Run the full mining pipeline over the stored spans and persist the results.

    Newly computed span costs are persisted first (via store.update_span_costs) so
    every downstream aggregate (clusters, sessions) sees priced spans. Analysis
    output is replaced wholesale in the store on each run.
    """
    query = filters or QueryFilters(limit=_ANALYSIS_SPAN_LIMIT)
    spans_df = store.spans_frame(query)

    if not spans_df.empty:
        pricing, default_pricing = load_pricing(settings.pricing_path)
        new_costs = compute_span_costs(spans_df, pricing, default_pricing)
        if new_costs:
            store.update_span_costs(new_costs)
            spans_df = store.spans_frame(query)  # re-read so aggregates include costs

    clusters = build_clusters(spans_df, fuzz_threshold=settings.cluster_fuzz_threshold)
    sessions = derive_sessions(spans_df)
    skills = load_all_skills(settings)
    matches, proposals = match_clusters(
        clusters, skills, threshold=settings.skill_match_threshold
    )

    store.replace_analysis(clusters, matches, proposals, sessions)
    return AnalysisResult(
        clusters=tuple(clusters),
        matches=tuple(matches),
        proposals=tuple(proposals),
        sessions=tuple(sessions),
        n_spans_analyzed=int(len(spans_df)),
        generated_at=datetime.now(UTC),
    )
