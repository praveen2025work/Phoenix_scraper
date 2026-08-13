"""Exchange span annotations with Phoenix: pull HUMAN/LLM judgements, push CODE ones.

Phoenix already holds validation data that no amount of local analysis can
reproduce — an analyst's thumbs-down on a wrong P&L answer, and the label/score
rows an `phoenix.evals` LLM-judge run logged back against spans. This module
pulls those in so they sit beside the local CODE checks in one table and roll up
through the same panels.

It also runs the other way: the CODE checks computed here can be pushed back as
span annotations, which is how they become visible to everyone using the Phoenix
UI rather than only to this tool. Push is opt-in, never automatic — it writes to
a shared system.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .models import AnnotationSyncReport, QueryFilters, SpanEvaluation
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

logger = logging.getLogger(__name__)

PHOENIX_SOURCE = "phoenix"
_VALID_ANNOTATOR_KINDS = frozenset({"HUMAN", "LLM", "CODE"})
_DEFAULT_ANNOTATOR_KIND = "HUMAN"

# Phoenix scores are free-form (0-1, 0-100, or a raw count). Anything above this
# is read as a percentage-style score and divided down, so a 0-1 "higher is
# better" convention holds across every source in one table.
_PERCENT_SCALE_MIN = 1.5


def pull_annotations(
    store: Store,
    client: PhoenixClientWrapper,
    settings: Settings,
    filters: QueryFilters | None = None,
) -> AnnotationSyncReport:
    """Fetch Phoenix annotations for the stored spans and persist them.

    Scoped to the spans this tool already scraped: Phoenix's annotation endpoint
    is span-id addressed, so the local corpus defines the query.
    """
    query = filters or QueryFilters(project=settings.project, limit=100_000)
    spans_df = store.spans_frame(query)
    if spans_df.empty:
        return AnnotationSyncReport(direction="pull")

    span_ids = [str(s) for s in spans_df["span_id"].dropna().unique()]
    raw = client.fetch_span_annotations(settings.project, span_ids)
    known = set(span_ids)
    evaluations = [
        evaluation
        for evaluation in (annotation_to_evaluation(item) for item in raw)
        if evaluation is not None and evaluation.span_id in known
    ]
    stored = store.upsert_evaluations(evaluations)
    return AnnotationSyncReport(
        direction="pull",
        spans_considered=len(span_ids),
        annotations=len(raw),
        stored=stored,
        skipped=len(raw) - len(evaluations),
    )


def push_annotations(
    store: Store,
    client: PhoenixClientWrapper,
    settings: Settings,
    filters: QueryFilters | None = None,
    only_failures: bool = True,
) -> AnnotationSyncReport:
    """Send locally computed CODE checks to Phoenix as span annotations.

    ``only_failures`` keeps the write small and the Phoenix UI readable: passing
    checks are the overwhelming majority and say nothing an analyst needs to see
    on a span. Pass False to mirror the full result set.
    """
    query = filters or QueryFilters(project=settings.project, limit=100_000)
    evals_df = store.evaluations_frame(query)
    if evals_df.empty:
        return AnnotationSyncReport(direction="push")
    local = evals_df.loc[evals_df["source"] == "local"]
    if only_failures:
        from .evaluations import PASS_SCORE

        scores = local["score"].astype(float).fillna(1.0)
        local = local.loc[scores < PASS_SCORE]
    payload = [to_phoenix_annotation(row) for row in local.to_dict("records")]
    sent = client.push_span_annotations(settings.project, payload)
    return AnnotationSyncReport(
        direction="push",
        spans_considered=int(evals_df["span_id"].nunique()),
        annotations=len(payload),
        stored=sent,
        skipped=len(payload) - sent,
    )


def annotation_to_evaluation(annotation: dict) -> SpanEvaluation | None:
    """Map one Phoenix annotation onto a SpanEvaluation.

    Tolerates both the nested ``result: {label, score, explanation}`` shape the
    REST API documents and the flattened columns the dataframe helpers return.
    Returns None when the annotation carries no span id or name to hang it on.
    """
    span_id = _text(_first(annotation, "span_id", "context.span_id", "spanId"))
    name = _text(_first(annotation, "name", "annotation_name"))
    if not span_id or not name:
        return None

    result = annotation.get("result")
    result = result if isinstance(result, dict) else {}
    label = _text(_first(result, "label") or _first(annotation, "label"))
    explanation = _text(
        _first(result, "explanation") or _first(annotation, "explanation")
    )
    score = _normalize_score(
        _first(result, "score") if "score" in result else _first(annotation, "score")
    )
    kind = _text(_first(annotation, "annotator_kind", "annotatorKind")).upper()
    return SpanEvaluation(
        span_id=span_id,
        name=name,
        label=label,
        score=score,
        explanation=explanation,
        annotator_kind=kind if kind in _VALID_ANNOTATOR_KINDS else _DEFAULT_ANNOTATOR_KIND,
        target="span",  # Phoenix does not distinguish prompt- from output-side checks
        source=PHOENIX_SOURCE,
        created_at=_parse_dt(_first(annotation, "created_at", "createdAt", "updated_at")),
    )


def to_phoenix_annotation(evaluation: dict[str, Any]) -> dict:
    """Map one local check onto the `/v1/span_annotations` payload shape.

    ``identifier`` is set to this tool's name so repeat pushes upsert their own
    rows instead of accumulating duplicates, and so a check we wrote can never
    overwrite a human's annotation of the same name.
    """
    return {
        "span_id": str(evaluation["span_id"]),
        "name": str(evaluation["name"]),
        "annotator_kind": "CODE",
        "result": {
            "label": str(evaluation.get("label") or ""),
            "score": _float_or_none(evaluation.get("score")),
            "explanation": str(evaluation.get("explanation") or ""),
        },
        "metadata": {"target": str(evaluation.get("target") or "span")},
        "identifier": "pheonix",
    }


def evaluations_to_annotations(
    evaluations: Iterable[SpanEvaluation],
) -> list[dict]:
    """Payload builder for callers holding SpanEvaluation objects directly."""
    return [to_phoenix_annotation(e.model_dump()) for e in evaluations]


# ---- helpers -----------------------------------------------------------------


def _first(mapping: dict, *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if result != result else result  # NaN check without importing math


def _normalize_score(value: Any) -> float | None:
    """Coerce a Phoenix score onto 0-1. Values above 1.5 are read as percentages."""
    score = _float_or_none(value)
    if score is None:
        return None
    if score > _PERCENT_SCALE_MIN:
        return min(1.0, score / 100.0)
    return max(0.0, min(1.0, score))


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def annotation_names(annotations: Sequence[dict]) -> list[str]:
    """Distinct annotation names present in a Phoenix response — used by diagnostics."""
    return sorted({_text(a.get("name")) for a in annotations if _text(a.get("name"))})
