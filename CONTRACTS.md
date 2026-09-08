# Module Contracts

Frozen interfaces for parallel implementation. `models.py`, `storage.py`, `config.py` are
already written — read them first, do not modify them. All functions return NEW objects
(no mutation of inputs). Type hints everywhere. Files stay under 400 lines.

## normalize.py
```python
def mask_volatile(text: str) -> str
    # casefold, collapse whitespace, mask volatile tokens with placeholders:
    # numbers/amounts -> <num>, dates -> <date>, currency pairs (EURUSD, EUR/USD) -> <ccy>,
    # ISO currency codes -> <ccy>, ids like ADJ-1234 / trade refs -> <id>, book codes -> <book>.
    # The one masker shared by prompt_signature (input) and Rung 2 (answer text).
def normalize_prompt(text: str) -> str      # backwards-compatible alias for mask_volatile
def prompt_signature(text: str) -> str
    # mask_volatile + strip punctuation; the cluster grouping key. "" for empty input.
```

## cluster.py
```python
def build_clusters(spans_df: pd.DataFrame, fuzz_threshold: int = 90) -> list[PromptCluster]
    # spans_df columns: span_id, session_id, user_id, input_text, cost_usd, latency_ms,
    # start_time, workflow_stage, asset_class (as produced by Store.spans_frame()).
    # 1) group rows by prompt_signature(input_text); drop empty signatures
    # 2) merge groups whose signatures score >= fuzz_threshold on rapidfuzz token_set_ratio
    # 3) cluster_id = hashlib.sha1(signature.encode()).hexdigest()[:12]
    # representative = most frequent raw input_text; aggregate count/sessions/users/cost/
    # latency/first_seen/last_seen/span_ids/asset_classes/workflow_stages.
    # Sorted by count desc.
```

## costs.py
```python
def load_pricing(path: Path) -> tuple[dict[str, ModelPricing], ModelPricing]
    # parse config/pricing.yaml -> ({model_prefix: ModelPricing}, default_pricing)
def price_for(model_name: str | None, pricing: dict[str, ModelPricing], default: ModelPricing) -> ModelPricing
    # longest key that is a prefix of model_name (case-insensitive); else default
def compute_span_costs(spans_df: pd.DataFrame, pricing: dict[str, ModelPricing], default: ModelPricing) -> dict[str, float]
    # for LLM rows where cost_usd is null and token counts exist:
    # cost = tokens_prompt/1000*input + tokens_completion/1000*output. Existing cost_usd kept.
    # returns {span_id: cost} for the newly computed rows only.
def cost_summary(spans_df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame
    # group_by subset of [model_name, workflow_stage, asset_class, user_id, session_id];
    # returns columns group_by + [n_spans, total_tokens, total_cost_usd] sorted by cost desc.
```

## sessions.py
```python
def derive_sessions(spans_df: pd.DataFrame) -> list[SessionRecord]
    # group by session_id (drop null/empty); user_id = first non-null; n_traces = distinct
    # trace_id; n_llm_spans = span_kind == "LLM"; n_user_turns = LLM rows with non-empty
    # input_text; total_tokens = sum tokens_total (fill 0); total_cost_usd = sum cost_usd;
    # models = sorted distinct model_name; first_prompt = input_text of earliest LLM row.
```

## skills.py
```python
def load_catalog(path: Path) -> list[SkillEntry]                  # config/skills_catalog.yaml
def scan_skill_dirs(dirs: list[Path]) -> list[SkillEntry]
    # find **/SKILL.md, parse YAML frontmatter (--- ... ---) name/description;
    # keywords = distinctive words from name+description; source="skill_md", path set.
    # Tolerate malformed files (skip with warning via logging).
def scan_skill_files(paths: list[Path]) -> list[SkillEntry]
    # parse an explicit list of loose markdown skill files (one skill per file) —
    # a capability's skills/<name>.md. Same parse as scan_skill_dirs; skip missing/malformed.
def load_all_skills(settings: Settings) -> list[SkillEntry]        # catalog + dirs, de-dup by name
```

## capability.py  (the capabilities/<id>/ disk layer — capability.yaml is source of truth)
```python
CONFIG_NAME = "capability.yaml"

def validate_id(cap_id: str) -> str
    # 1-64 chars, ^[a-z][a-z0-9-]{0,63}$; returns it or raises ValueError.
def config_path(root: Path, cap_id: str) -> Path        # <root>/<id>/capability.yaml
def load_capability(root: Path, cap_id: str) -> Capability
    # FileNotFoundError if absent; ValueError if not a mapping / bad YAML / bad section / bad id.
    # Unknown status -> "active". Blank filter values -> None.
    # window_days: absent/blank -> 30; <= 0 -> ValueError.
def dump_capability(capability: Capability) -> str      # yaml text; load round-trips
def write_capability(root: Path, capability: Capability) -> Path
    # mkdir <id>/skills, <id>/deterministic; write capability.yaml; return its path
def scaffold_capability(root, cap_id, *, name="", description="",
                        cap_filter=None, window_days=30) -> Capability
    # FileExistsError if capability.yaml already there; ValueError on bad id
def list_capability_ids(root: Path) -> list[str]        # sorted; only dirs with a yaml
def load_all_capabilities(root: Path) -> list[Capability]   # skips malformed (warns)
def capability_skill_dirs(root: Path, cap_id: str) -> list[Path]   # [<id>/skills] or []
def capability_query_filters(capability, *, start=None, end=None,
                             limit=100_000) -> QueryFilters
```

## capability_run.py  (scoped pipeline run + orchestration; does NOT touch the global run_analysis)
```python
def load_capability_skills(settings, capability) -> list[SkillEntry]
    # load_all_skills(settings) + scan of loose <capabilities_dir>/<id>/skills/*.md,
    # de-duped by name (earlier source wins).
def run_capability_analysis(store, settings, capability, *, window_start=None,
        window_end=None, replace_today=False, notes=None, now=None) -> CapabilityRunResult
    # NO scrape. window defaults to [now - capability.window_days, now].
    # in-scope = capability_query_filters(...); costs ->
    # evaluate_spans + store.upsert_evaluations (when settings.evaluate_on_analyze
    # and in-scope non-empty; idempotent; a broken checker logs + adds a
    # "validation skipped" note, never aborts) -> build_clusters ->
    # load_capability_skills -> match_clusters -> annotate_coverage ->
    # cluster_efficiency -> ladder.detect_rung1/detect_rung2 ->
    # ladder_run.update_rung1/update_rung2.
    # Records capability_runs + capability_cluster_snapshots +
    # capability_cluster_members; prunes to settings.run_history_limit per
    # capability. Only scrape `notes` force status='partial'; ladder notes are
    # informational. n_rung1_candidates and n_rung2_candidates are both set.
def run_capabilities(store, settings, *, capability_ids=None, all_active=False,
        client=None, window_start=None, window_end=None, replace_today=False,
        now=None) -> list[CapabilityRunResult]
    # sync each capability.yaml -> DB; scrape each distinct project once
    # (client is None / unavailable -> note "offline", status partial);
    # loop run_capability_analysis; a capability that raises is recorded as a
    # status='failed' run and never aborts the others.
```

New tables (Phase B): `capability_runs`, `capability_cluster_snapshots` (column
`skill_name`, not `matched_skill`, for `cluster_deltas` compatibility),
`capability_cluster_members`. Pruned per capability to `run_history_limit`.

## ladder.py  (pure: threshold resolution, Rung-1 detection, §10.1 state machine)
```python
def resolve_thresholds(capability, settings) -> LadderThresholds
    # Settings defaults, overridden by capability.thresholds for the rung1_* keys.
def detect_rung1(clusters, matches, annotated, efficiency, *, thresholds) -> list[Rung1Signal]
    # one signal per in-scope cluster at/above the creation floor
    # (max(3, rung1_min_count//3)) that is new_skill (no match >= skill_match_threshold)
    # or strengthen_skill (matched but coverage_score < skill_coverage_threshold).
    # score = gap strength; met_evidence_bar = n_users>=rung1_min_users AND count>=rung1_min_count.
def readiness_met(recent_observations, *, sustained_runs, capability_run_count) -> bool
def is_material_change(candidate, observation, *, thresholds) -> bool
def detect_rung2(clusters, matches, in_scope, *, thresholds) -> list[Rung2Signal]
    # determinism.score_cluster per cluster; stamps met_evidence_bar
    # (eligible AND determinism_score >= rung2_determinism_score).
def next_status(candidate, observation, recent_observations, *, run_ordinal,
        capability_run_count, thresholds, eligible=True, rung="skill") -> LadderTransition
    # observed this run. eligible=False + new/accumulating -> insufficient_data;
    # insufficient_data + eligible -> accumulating. rung picks the sustained-runs
    # threshold (skill: rung1_sustained_runs, deterministic: rung2_sustained_runs).
def advance_unobserved(candidate, *, run_ordinal, last_seen_ordinal,
        history_limit) -> LadderTransition | None                    # not observed this run
```

## determinism.py  (pure: the Rung-2 lexical determinism signal; no LLM)
```python
# mask_volatile now lives in normalize.py — shared with prompt_signature.
def build_templates(answers, *, fuzz_threshold) -> list[(masked_rep, count)]
def template_concentration(answers, *, fuzz_threshold) -> (concentration, k)   # k covers >=90%
def route_invariance(flows) -> float                                          # modal / n
def output_self_similarity(answers, *, sample=200, max_pairs=5000) -> float
def slot_stability(pairs, templates, *, fuzz_threshold) -> float
def blend_determinism(signals: DeterminismSignals) -> float   # 0.4/0.3/0.2/0.1, route N/A renormalises
def score_cluster(cluster_id, title, signature, matched_skill, member_spans, *,
        min_answer_spans, fuzz_threshold) -> Rung2Signal
    # answer span = LLM member span with non-empty output_text; < min -> eligible=False, score=0.
```

## ladder_run.py  (store-touching: persist a run's Rung-1 / Rung-2 candidates)
```python
def update_rung1(store, capability, *, run_id, run_ordinal, capability_run_count,
        observed_at, signals, thresholds, history_limit) -> Rung1RunOutcome
    # upsert candidates (create at 'new'), one observation row each (crossed_threshold
    # flag), run next_status, persist status/ready_at + auto 'reopen' decision, prune
    # observations to history_limit; then advance_unobserved for every other
    # rung-'skill' candidate.
def update_rung2(store, capability, *, run_id, run_ordinal, capability_run_count,
        observed_at, signals, thresholds, history_limit) -> Rung2RunOutcome
    # parallel to update_rung1: <cap>:d:<cluster> ids, rung='deterministic',
    # creation floor determinism_score >= 0.5, insufficient_data holding state,
    # "Rung 2: N clusters skipped" note.
```

## artifacts.py  (render / write the ladder's draft artifacts; never edits hand-authored files)
```python
def render_new_skill_md(candidate, *, capability, member_prompts, today) -> (filename, markdown)
    # frontmatter: name (kebab from signature), description, level, capability,
    # keywords, example_prompts, status: draft, source_candidate, evidence. Body:
    # scaffold comment + "## When to use" + "## Procedure\n1. TODO".
def render_strengthen_block(candidate, skill, *, member_prompts, member_signatures) -> (target_path, yaml_block)
    # reuses skill_coverage._yaml_block / _suggested_keywords; writes nothing.
def render_rung2_stub(candidate, *, latest_observation_signals, pairs) -> [(filename, body) x3]
    # <name> = _module_name(_skill_stem(candidate)) — a valid snake_case module,
    # so test_<name>.py's `from .<name> import handle` imports. Files:
    # <name>.py (TEMPLATES, DECISION_TABLE when slot_stability>=0.8, handle raises
    # NotImplementedError), test_<name>.py (parametrized over the real observed
    # (input_text, output_text) pairs, ships red), <name>.md.
def promote_candidate(store, capability, candidate, *, now, actor, settings,
        dry_run=False) -> PromoteResult
    # rung 'skill' new_skill -> writes capabilities/<cap>/skills/<name>.md (dedup);
    # strengthen_skill -> returns the paste block + target path, no file;
    # rung 'deterministic' -> writes deterministic/<name>.{py,md} + test_<name>.py
    #   (<name> snake_case; pairs are real member (input,output) via _member_pairs,
    #    falling back to (prompt, prompt) only when a cluster has no recorded members).
    # Records a 'promote' decision; sets status='promoted' + promoted_artifact_paths.
```

New Store methods (Phase C): `upsert_candidate` / `get_candidate` /
`candidates_frame(cap, *, rung, status)`; `record_candidate_observation` /
`candidate_observations_frame` / `recent_candidate_observations(cid, n)` /
`prune_candidate_observations(cid, keep)`; `record_candidate_decision -> id` /
`record_candidate_decision_now` / `candidate_decisions_frame`;
`capability_run_ordinal(cap, run_id=None)`. New tables: `candidates`,
`candidate_observations`, `candidate_decisions`.

New `Settings` (Phase C/D): `rung1_min_users` (3), `rung1_min_count` (15),
`rung1_sustained_runs` (5), `material_change_count_factor` (1.5),
`material_change_users_delta` (2), `rung2_min_answer_spans` (10),
`rung2_determinism_score` (0.8), `rung2_sustained_runs` (3).

## taxonomy.py
```python
ASSET_CLASS_KEYWORDS: dict[str, tuple[str, ...]]   # fx, rates, equities, credit, commodities
CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]]    # fobo_recon, plex, flash_vs_formal,
                                                   # adjustments, commentary_signoff,
                                                   # break_investigation, data_retrieval
def infer_asset_class(text: str) -> str | None
def infer_capability(text: str) -> str | None
def suggest_level(text: str) -> tuple[str, str | None, str | None]
    # (level, asset_class, capability): asset_class match -> ("asset_class", ac, cap);
    # capability only -> ("capability", None, cap); neither -> ("global", None, None)
```

## skills_mapper.py
```python
def score_match(cluster: PromptCluster, skill: SkillEntry) -> float
    # 0-1: 0.5 * keyword-hit-ratio (skill.keywords found in cluster signature/representative)
    # + 0.5 * max rapidfuzz token_set_ratio/100 vs skill.example_prompts + description
def match_clusters(clusters: list[PromptCluster], skills: list[SkillEntry], threshold: float = 0.55,
                   min_evidence: int = 2) -> tuple[list[SkillMatch], list[SkillGapProposal]]
    # best skill per cluster; >= threshold -> SkillMatch. Unmatched clusters with
    # count >= min_evidence -> SkillGapProposal using taxonomy.suggest_level(representative);
    # proposed_name = kebab-case from top signature words; description auto-generated;
    # sample_span_ids = first 5.
```

## phoenix_client.py  (invariant: the ONLY module that talks to Phoenix)
```python
class PhoenixClientWrapper:
    def __init__(self, settings: Settings): ...
    def available(self) -> bool      # endpoint configured AND arize-phoenix-client importable
    def fetch_spans(self, project: str, start: datetime | None, end: datetime | None,
                    limit: int) -> pd.DataFrame
    # Uses CURRENT client API (arize-phoenix-client ~=2.13):
    #   from phoenix.client import Client
    #   from phoenix.client.types.spans import SpanQuery
    #   Client(base_url=..., api_key=...).spans.get_spans_dataframe(
    #       query=SpanQuery(), start_time=..., end_time=..., limit=..., project_identifier=...)
    # Import phoenix.client lazily inside the method; raise RuntimeError with an
    # actionable message if unavailable. 3 retries with backoff on connection errors.
```

## scraper.py
```python
def flatten_phoenix_row(row: dict, project: str) -> SpanRecord | None
    # Map OpenInference columns/attributes -> SpanRecord. Handle both flattened column
    # names (context.span_id, attributes.llm.model_name) and nested attributes dicts:
    #   span_id <- context.span_id; trace_id <- context.trace_id
    #   session_id <- attributes.session.id; user_id <- attributes.user.id
    #   span_kind <- attributes.openinference.span.kind (or span_kind column)
    #   model <- attributes.llm.model_name; tokens <- attributes.llm.token_count.{prompt,completion,total}
    #   input_text <- attributes.input.value; output_text <- attributes.output.value
    #   cost <- attributes.llm.cost.total if present
    #   workflow_stage <- attributes.metadata.workflow_stage; asset_class <- attributes.metadata.asset_class
    # None if span_id/trace_id/start_time missing.
def scrape_once(store: Store, client: PhoenixClientWrapper, settings: Settings) -> ScrapeReport
    # watermark = store.get_watermark(f"phoenix:{project}"); pull from
    # watermark - overlap_minutes (dedup via span_id PK); insert; new watermark =
    # max(start_time) of pulled spans (never move backwards); source="live".
def ingest_jsonl(store: Store, path: Path, project: str) -> ScrapeReport
    # offline path: one JSON span per line -> flatten_phoenix_row -> upsert. source="jsonl".
```

## fixtures.py
```python
def generate_fixture_spans(n_sessions: int = 60, seed: int = 42,
                           project: str = "pnl-agent") -> list[SpanRecord]
    # Deterministic synthetic P&L-agent traffic: analyst sessions across asset classes
    # (fx/rates/equities/credit) and stages (fobo_recon/plex/flash_vs_formal/adjustments/
    # commentary_signoff). Frequency-skewed prompt pools (a few prompts asked MANY times,
    # with number/date/ccy variations so normalization matters + a long tail).
    # Each user turn: LLM span (input_text=prompt, tokens, bedrock claude model ids,
    # cost_usd=None) + occasional AGENT/TOOL child spans (tool.name in attributes).
    # Realistic timestamps over the last 14 days. user_id from a pool of ~8 analysts.
def seed_demo(store: Store, n_sessions: int = 60, seed: int = 42) -> ScrapeReport  # source="fixtures"
```

## export.py
```python
def export_frame(df: pd.DataFrame, out_dir: Path, name: str, fmt: str) -> Path
    # fmt in {csv, json, parquet}; returns written path (out_dir created if needed)
def write_markdown_report(result: AnalysisResult, out_path: Path) -> Path
    # human-readable: top prompts table, matched skills, proposed new skills grouped by
    # level (global / asset_class / capability), session + cost summary.
```

## evaluations.py  (the CODE annotator — pure, offline, no model calls)
```python
PASS_SCORE = 0.5          # scores are 0-1, HIGHER IS BETTER; below this the check failed
CHECKS: list[tuple[str, EvalTarget, Checker]]   # registry, populated by @_register

def evaluate_spans(spans_df, settings, now=None) -> list[SpanEvaluation]
    # one row per (span, APPLICABLE check). A checker returns None when it does not
    # apply (prompt check on a tool span, groundedness on a tool-backed trace) so
    # rollups never dilute fail rates with spans that were never in scope.
def build_context(spans_df, settings) -> EvalContext
    # corpus stats a single-span check cannot compute: per-span-kind latency outlier
    # thresholds, prompt-length threshold, per-trace reference text, traces with tools.
def check_names() -> tuple[tuple[str, EvalTarget], ...]
def evaluations_frame(evaluations) -> pd.DataFrame     # adds derived `passed`

# Every checker: (span_mapping, EvalContext) -> EvalOutcome | None, and every
# EvalOutcome MUST carry an explanation naming its evidence — a heuristic that
# cannot be audited is noise.
```

## annotations.py  (round-trip with Phoenix; uses phoenix_client, never httpx directly)
```python
def pull_annotations(store, client, settings, filters=None) -> AnnotationSyncReport
    # fetch Phoenix annotations for the STORED spans; drop any whose span_id is
    # unknown locally (it would break the join every quality view rests on).
def push_annotations(store, client, settings, filters=None, only_failures=True) -> AnnotationSyncReport
    # send source='local' checks only — echoing Phoenix's own rows back would
    # duplicate its data. Opt-in: it writes to a shared system.
def annotation_to_evaluation(annotation: dict) -> SpanEvaluation | None
    # tolerate nested result{label,score,explanation} AND flattened columns;
    # scores > 1.5 are read as percentages; unknown annotator_kind -> HUMAN.
def to_phoenix_annotation(evaluation: dict) -> dict     # /v1/span_annotations shape
```

## skill_coverage.py  (what each skill FILE misses; run-over-run diffs)
```python
NEW / GROWING / STABLE / SHRINKING / GONE   # cluster status vs the previous run

def coverage_score(representative: str, skill: SkillEntry) -> float
    # 0-1 similarity to the skill's OWN example_prompts (then description) — the
    # same reference set skills_mapper._fuzzy_ratio scores against, so "matched"
    # and "covered" are measured on one scale.
def source_file(skill: SkillEntry) -> str        # the artifact an owner edits
def annotate_coverage(clusters_df, matches_df, skills, threshold=0.70) -> pd.DataFrame
    # one row per matched cluster + covered flag. Carries `signature` so keyword
    # suggestions never see unmasked desks/amounts/dates.
def skill_coverage(annotated_df) -> pd.DataFrame       # coverage weighted by ASKS
def uncovered_queries(annotated_df, deltas_df=None) -> pd.DataFrame
def cluster_deltas(current_df, previous_df) -> pd.DataFrame
    # EMPTY previous_df => empty result. "No earlier run" is not "an earlier run
    # that saw nothing"; calling everything new on a first run would be a lie.
def suggested_updates(uncovered_df, skills, max_prompts=8) -> pd.DataFrame
    # per file: new_prompts, new_keywords, and a paste-ready yaml_block.
def updates_markdown(updates_df) -> str
```

## insights_quality.py  (rollups over Store.evaluations_frame)
```python
def with_pass_flag(evals_df) -> pd.DataFrame       # unscored annotations count as PASSING
def quality_summary(evals_df) -> pd.DataFrame      # per (check, source)
def quality_by_dimension(evals_df, column) -> pd.DataFrame
def failing_spans(evals_df, limit=200) -> pd.DataFrame
def quality_by_cluster(evals_df, clusters_df, members_df) -> pd.DataFrame
def quality_overview(evals_df) -> dict
```

## pipeline.py  (owned by the cli/api implementer)
```python
def run_analysis(store: Store, settings: Settings) -> AnalysisResult
    # spans_frame -> compute+persist costs -> build_clusters -> derive_sessions ->
    # load_all_skills -> match_clusters -> evaluate_spans (when
    # settings.evaluate_on_analyze) -> store.replace_analysis -> AnalysisResult
```

## cli.py (typer app named `app`) + api.py (fastapi app factory `create_app(settings)`)
CLI commands: demo (seed fixtures + analyze + report), seed, scrape, ingest, analyze,
evaluate (+ --pull-annotations / --push / --push-all / --user), coverage (+ --write),
report, export (--what spans|clusters|matches|proposals|sessions|evaluations|
coverage|uncovered --fmt csv|json|parquet + filter options), serve,
run (--capability | --all, --from, --to, --replace-today),
capability (new | list | show | sync | runs | jobs),
candidates (<id> --rung --status --all), candidate (<cid>),
decide (<cid> --action accept|reject|snooze|reopen --actor --note --snooze-runs),
promote (<cid> --accept --dry-run), serve-ui (--dist --port).
API routes: GET / (JSON notice: service/docs/health/frontend), GET /health,
POST /demo/seed, POST /scrape/run, POST /analyze/run,
POST /report/run, GET /prompts/frequent, GET /skills/matches, GET /skills/gaps,
GET /skills/{coverage,uncovered,updates,updates.md}, GET /runs, GET /runs/delta,
GET /sessions, GET /costs/summary, GET /spans,
GET /quality/{overview,checks,by,failures,by-prompt,evaluations,catalog},
POST /annotations/{pull,push} — all list endpoints accept filter query params and
`fmt=json|csv` where csv returns a downloadable file response.

Phase E — Capabilities: GET/POST /capabilities, GET/PATCH/DELETE
/capabilities/{id} (?purge=), POST /capabilities/{id}/sync. Runs: POST
/capabilities/{id}/runs {from?,to?,replace_today?} (synchronous), GET
/capabilities/{id}/runs, GET /capabilities/{id}/runs/{run_id}, GET
/capabilities/{id}/runs/delta?from=&to=. Async runs: POST
/capabilities/{id}/jobs {from?,to?,replace_today?} -> 202 {job_id, state},
GET /capabilities/{id}/jobs, GET /capabilities/{id}/jobs/{job_id}
{state: queued|running|done|error, run_id, error}.
Ladder: GET /capabilities/{id}/candidates?rung=&status=, GET /candidates/{cid},
POST /candidates/{cid}/decision {action,actor?,note?,snooze_runs?} (409 on
invalid transition), POST /candidates/{cid}/promote?accept=, GET
/candidates/{cid}/artifact/preview. Every analytics route takes an optional
`?capability=<id>` that seeds the filter + [now-window_days, now] window
(explicit params win). `PHEONIX_CORS_ORIGINS` (comma-separated) adds
`CORSMiddleware` + a CSRF-guard allowance for those origins.

## api_capabilities.py / api_ladder.py
```python
def capability_router(settings) -> APIRouter   # capability CRUD + run + job routes
def ladder_router(settings) -> APIRouter       # board / candidate / decision / promote
# both mounted under the protected (X-API-Key) router in create_app.
# DECISION_TRANSITIONS lives in ladder.py, shared by the CLI and the API.
```

## jobs.py  (background capability-run worker — one daemon thread, one run at a time)
```python
class JobWorker(settings, *, poll_seconds=1.0)
    # start() / stop(timeout=5) / drain_once() -> job_id | None
    # _loop polls Store.claim_next_job every poll_seconds; each iteration wrapped
    # so the thread never dies. A capability that fails inside run_capabilities
    # ends the job 'done' (the run row carries status='failed'); only an escape
    # ends it 'error' (message on the row).
```
`api.create_app(settings, *, run_jobs=False)` — `run_jobs=True` (only
`create_app_default()` and the Playwright smoke) attaches a `lifespan` that
`Store.reset_orphaned_jobs()` on startup then runs a `JobWorker`; the worker is
on `app.state.job_worker` (or `None`).

Store queue methods (mirror `capability_jobs`): `enqueue_job(job_id,
capability_id, params: dict)`, `get_job(job_id) -> dict | None` (params back as a
dict), `capability_jobs_frame(capability_id, limit=50)` (newest first),
`claim_next_job() -> dict | None` (oldest 'queued' -> 'running'),
`finish_job(job_id, *, run_id, state, error=None)`, `reset_orphaned_jobs() ->
int`. `Store` is a context manager; its connection opens with
`journal_mode=WAL` + `busy_timeout=5000`.

## frontend/  (separate npm package — React 19 + Vite + TS + Tailwind v4 + shadcn/ui)
- Runs on its own dev server (`:5173`); talks to the API by absolute URL
  (`VITE_API_BASE`, default `http://localhost:8000`) + CORS (`PHEONIX_CORS_ORIGINS`).
- `src/api/client.ts` — `fetchJson` attaches `X-API-Key` from `sessionStorage`;
  `ApiError(status, detail)`. `src/api/hooks.ts` — TanStack Query hooks.
  `src/api/schema.ts` — `openapi-typescript` output (regenerate with `make ui-types`).
- Routes: `/` (capabilities index), `/c/:id` (detail + Rung 1/2 lane boards),
  `/c/:id/candidate/:cid` (trend, signals, decide, promote), `/c/:id/analytics`.
- `pheonix serve-ui [--dist] [--port]` serves the built `frontend/dist` (SPA
  fallback). `make ui` / `ui-build` / `ui-test` / `ui-types` / `ui-e2e`.

run_analysis snapshots its clusters into analysis_runs/cluster_snapshots before
returning, reading previous_run_id FIRST (once recorded, a run would be its own
predecessor). History is pruned to settings.run_history_limit.

Limit semantics: `Store.evaluations_frame` bounds CHECK ROWS, not spans (one span
yields a row per applicable check). The /quality/* routes therefore use
`EVALUATION_ROW_LIMIT`, not the span-sized analysis limit, or every rollup would
silently describe a truncated corpus while presenting itself as complete.

## Testing rules (all modules)
- TDD: write tests first in `tests/test_<module>.py`, then implement to green.
- Use fixtures from `tests/conftest.py` (sample_spans, tmp_store, catalog paths).
- No network, no live Phoenix in tests; PhoenixClientWrapper tested via monkeypatched module.
- Run: `uv run pytest tests/test_<module>.py -q` from the repo root.
