"""Frozen data models shared by every module. All timestamps are UTC."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SpanKind = Literal["LLM", "AGENT", "RETRIEVER", "TOOL", "CHAIN", "UNKNOWN"]
SkillLevel = Literal["global", "asset_class", "capability"]

# Phoenix's three annotator kinds: a human clicking thumbs up/down, an
# llm-as-judge eval, or a deterministic programmatic check (what evaluations.py
# produces). Kept as Phoenix spells them so annotations round-trip unchanged.
AnnotatorKind = Literal["HUMAN", "LLM", "CODE"]
EvalTarget = Literal["prompt", "output", "span"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class SpanRecord(_Frozen):
    """One flattened Phoenix span, normalized from OpenInference attributes."""

    span_id: str
    trace_id: str
    session_id: str | None = None
    project: str = "default"
    name: str = ""
    span_kind: str = "UNKNOWN"
    start_time: datetime
    end_time: datetime | None = None
    latency_ms: float | None = None
    status_code: str = "OK"
    model_name: str | None = None
    user_id: str | None = None
    workflow_stage: str | None = None  # e.g. fobo_recon | plex | flash_vs_formal | ...
    asset_class: str | None = None  # e.g. fx | rates | equities | credit | commodities
    input_text: str = ""  # user-facing prompt / input.value
    output_text: str = ""
    prompt_template: str | None = None
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    tokens_total: int | None = None
    cost_usd: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class SessionRecord(_Frozen):
    session_id: str
    project: str = "default"
    user_id: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    n_traces: int = 0
    n_llm_spans: int = 0
    n_user_turns: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    models: tuple[str, ...] = ()
    first_prompt: str = ""


class PromptCluster(_Frozen):
    """A group of near-identical user prompts with frequency and cost evidence."""

    cluster_id: str  # sha1(signature)[:12]
    signature: str  # normalized prompt used as the grouping key
    representative: str  # most common raw prompt in the cluster
    count: int
    n_sessions: int = 0
    n_users: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    span_ids: tuple[str, ...] = ()
    asset_classes: tuple[str, ...] = ()
    workflow_stages: tuple[str, ...] = ()


class ModelPricing(_Frozen):
    input_per_1k: float
    output_per_1k: float


class SkillEntry(_Frozen):
    """One entry from the skills catalog (YAML) or a scanned SKILL.md file."""

    name: str
    level: SkillLevel = "global"
    asset_class: str | None = None
    capability: str | None = None
    description: str = ""
    keywords: tuple[str, ...] = ()
    example_prompts: tuple[str, ...] = ()
    source: str = "yaml"  # yaml | skill_md
    path: str | None = None


class SkillMatch(_Frozen):
    cluster_id: str
    skill_name: str
    score: float  # 0-1
    method: str = "keyword+fuzzy"


class SkillGapProposal(_Frozen):
    """A frequent prompt cluster with no matching skill — a proposed new skill."""

    cluster_id: str
    proposed_name: str
    level: SkillLevel
    asset_class: str | None = None
    capability: str | None = None
    description: str
    evidence_count: int
    representative_prompt: str
    sample_span_ids: tuple[str, ...] = ()


class SpanEvaluation(_Frozen):
    """One judgement about a span, in Phoenix's span-annotation shape.

    Mirrors the Phoenix `/v1/span_annotations` payload (name + annotator_kind +
    result.label/score/explanation) so locally computed checks and annotations
    pulled from Phoenix live in one table and roll up together. `score` is
    always 0-1 with **higher = better**; `passed` derives from PASS_SCORE.
    """

    span_id: str
    name: str  # check/annotation name, e.g. "output_refusal" or "correctness"
    label: str = ""  # descriptive class, e.g. "refused" / "answered"
    score: float | None = None
    explanation: str = ""
    annotator_kind: AnnotatorKind = "CODE"
    target: EvalTarget = "span"  # which side of the exchange the check judges
    source: str = "local"  # local (computed here) | phoenix (pulled from Phoenix)
    created_at: datetime | None = None


class AnnotationSyncReport(_Frozen):
    """Outcome of exchanging span annotations with a live Phoenix server."""

    direction: str  # pull | push
    spans_considered: int = 0
    annotations: int = 0
    stored: int = 0
    skipped: int = 0


class ScrapeReport(_Frozen):
    source: str  # live | fixtures | jsonl
    pulled: int = 0
    inserted: int = 0
    skipped: int = 0
    watermark_before: datetime | None = None
    watermark_after: datetime | None = None


class QueryFilters(_Frozen):
    """Shared filter set for storage queries, exports, and API params."""

    project: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    span_kinds: tuple[str, ...] = ()
    workflow_stage: str | None = None
    asset_class: str | None = None
    model_name: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    search: str | None = None  # substring match on input_text
    min_count: int = 1  # for clusters
    limit: int = 1000


class AnalysisResult(_Frozen):
    clusters: tuple[PromptCluster, ...] = ()
    matches: tuple[SkillMatch, ...] = ()
    proposals: tuple[SkillGapProposal, ...] = ()
    sessions: tuple[SessionRecord, ...] = ()
    evaluations: tuple[SpanEvaluation, ...] = ()
    n_spans_analyzed: int = 0
    generated_at: datetime | None = None
    run_id: str | None = None  # this run's snapshot key
    previous_run_id: str | None = None  # the run this one can be diffed against
