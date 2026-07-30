# Module Contracts

Frozen interfaces for parallel implementation. `models.py`, `storage.py`, `config.py` are
already written — read them first, do not modify them. All functions return NEW objects
(no mutation of inputs). Type hints everywhere. Files stay under 400 lines.

## normalize.py
```python
def normalize_prompt(text: str) -> str
    # casefold, collapse whitespace, mask volatile tokens with placeholders:
    # numbers/amounts -> <num>, dates -> <date>, currency pairs (EURUSD, EUR/USD) -> <ccy>,
    # ISO currency codes -> <ccy>, ids like ADJ-1234 / trade refs -> <id>.
def prompt_signature(text: str) -> str
    # normalize_prompt + strip punctuation; the cluster grouping key. "" for empty input.
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
def load_all_skills(settings: Settings) -> list[SkillEntry]        # catalog + dirs, de-dup by name
```

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

## pipeline.py  (owned by the cli/api implementer)
```python
def run_analysis(store: Store, settings: Settings) -> AnalysisResult
    # spans_frame -> compute+persist costs -> build_clusters -> derive_sessions ->
    # load_all_skills -> match_clusters -> store.replace_analysis -> AnalysisResult
```

## cli.py (typer app named `app`) + api.py (fastapi app factory `create_app(settings)`)
CLI commands: demo (seed fixtures + analyze + report), seed, scrape, ingest, analyze,
report, export (--what spans|clusters|matches|proposals|sessions --fmt csv|json|parquet
+ filter options), serve. API routes: GET /health, POST /demo/seed, POST /scrape/run,
GET /prompts/frequent, GET /skills/matches, GET /skills/gaps, GET /sessions,
GET /costs/summary, GET /spans — all list endpoints accept filter query params and
`fmt=json|csv` where csv returns a downloadable file response.

## Testing rules (all modules)
- TDD: write tests first in `tests/test_<module>.py`, then implement to green.
- Use fixtures from `tests/conftest.py` (sample_spans, tmp_store, catalog paths).
- No network, no live Phoenix in tests; PhoenixClientWrapper tested via monkeypatched module.
- Run: `uv run pytest tests/test_<module>.py -q` from the repo root.
