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


class CapabilityFilter(_Frozen):
    """The span selector for a capability — a subset of QueryFilters' dimensions."""

    project: str | None = None
    workflow_stage: str | None = None
    asset_class: str | None = None
    model_name: str | None = None
    search: str | None = None  # substring match on input_text
    # Any-of substrings, OR-ed together and AND-ed with `search`. The escape
    # hatch when spans carry no workflow_stage: scope a capability by phrasing.
    search_any: tuple[str, ...] = ()


class Capability(_Frozen):
    """A named analysis scope: a saved span filter plus an owned directory of
    skill files. Defined on disk in capabilities/<id>/capability.yaml; mirrored
    into the `capabilities` table."""

    id: str
    name: str
    description: str = ""
    filter: CapabilityFilter = Field(default_factory=CapabilityFilter)
    window_days: int = Field(default=30, gt=0)
    thresholds: dict[str, float] = Field(default_factory=dict)
    status: Literal["active", "paused"] = "active"


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


class CapabilityRun(_Frozen):
    """One recorded scoped analysis run for a capability (mirrors capability_runs)."""

    run_id: str  # ISO-8601 UTC timestamp
    capability_id: str
    started_at: datetime
    finished_at: datetime | None = None
    window_start: datetime
    window_end: datetime
    n_spans: int = 0  # total spans in the store at run time
    n_in_scope_spans: int = 0
    n_clusters: int = 0
    n_rung1_candidates: int = 0  # written 0 until Phase C
    n_rung2_candidates: int = 0  # written 0 until Phase D
    status: Literal["ok", "partial", "failed"] = "ok"
    notes: tuple[str, ...] = ()
    # filename -> sha256 hex of each capabilities/<id>/skills/*.md at run start
    skill_hashes: dict[str, str] = Field(default_factory=dict)


class CapabilityRunResult(_Frozen):
    """The return value of run_capability_analysis — the run plus what a caller
    needs to print or report without re-querying."""

    run: CapabilityRun
    clusters: tuple[PromptCluster, ...] = ()
    matches: tuple[SkillMatch, ...] = ()
    proposals: tuple[SkillGapProposal, ...] = ()
    previous_run_id: str | None = None


Rung = Literal["skill", "deterministic"]
CandidateStatus = Literal[
    "new", "accumulating", "insufficient_data", "ready", "accepted",
    "snoozed", "rejected", "promoted", "stale",
]
DecisionAction = Literal["accept", "reject", "snooze", "reopen", "promote"]


class Candidate(_Frozen):
    """The persistent ladder record for one in-scope cluster (mirrors `candidates`)."""

    candidate_id: str  # "<cap>:s:<cluster_id>" (rung 1) | "<cap>:d:<cluster_id>" (rung 2)
    capability_id: str
    rung: Rung
    subtype: str = ""  # rung "skill": "new_skill" | "strengthen_skill"
    cluster_id: str
    title: str  # representative prompt, trimmed
    signature: str
    matched_skill: str | None = None
    status: CandidateStatus = "new"
    first_seen_run_id: str
    first_seen_at: datetime
    last_seen_run_id: str
    last_seen_at: datetime
    ready_at: datetime | None = None
    promoted_at: datetime | None = None
    promoted_artifact_paths: tuple[str, ...] = ()
    snooze_until_run: int | None = None  # run ordinal to unsnooze at
    dismiss_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    current_evidence: dict[str, Any] = Field(default_factory=dict)


class CandidateObservation(_Frozen):
    """One candidate's evidence for one run (mirrors `candidate_observations`)."""

    candidate_id: str
    run_id: str
    observed_at: datetime
    count: int = 0
    n_users: int = 0
    n_sessions: int = 0
    total_cost_usd: float = 0.0
    score: float | None = None  # rung 1: gap strength; rung 2: determinism_score
    signals: dict[str, Any] = Field(default_factory=dict)
    met_evidence_bar: bool = False
    crossed_threshold: bool = False  # met the bar this run, had not last run


class CandidateDecision(_Frozen):
    """One row of the append-only decision log (mirrors `candidate_decisions`)."""

    candidate_id: str
    action: DecisionAction
    actor: str
    created_at: datetime
    id: int | None = None  # AUTOINCREMENT — None until read back
    run_id: str | None = None
    note: str = ""


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
    skipped: int = 0  # dropped + duplicates, kept as the headline number
    # A duplicate is a healthy re-scrape of a span we already hold; a dropped row
    # is one Phoenix sent that we could not read at all. Only the second is loss.
    dropped: int = 0
    duplicates: int = 0
    watermark_before: datetime | None = None
    watermark_after: datetime | None = None
    # True when a pull came back full and could not be split any further, so
    # Phoenix still holds spans this scrape never saw.
    truncated: bool = False


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
    search_any: tuple[str, ...] = ()  # OR-ed substrings, AND-ed with `search`
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
