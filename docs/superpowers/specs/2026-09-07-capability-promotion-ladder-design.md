# Capability Promotion Ladder — Design

- **Date:** 2026-09-07
- **Status:** Approved (design); implementation plan pending
- **Repo:** `pheonix` — evolves the existing `phoenix_scraper` package (Approach 1)
- **Supersedes:** nothing; extends the existing prompt-miner POC

---

## 1. Summary

`phoenix_scraper` today scrapes Arize Phoenix spans, frequency-clusters user
prompts, matches them against a skills catalog, proposes new skills for uncovered
frequent clusters, measures per-file coverage, runs 13 offline validation checks,
and diffs runs over time. It serves a single bundled HTML dashboard from the same
FastAPI app.

This design adds a **capability** as a first-class entity and a **two-rung
promotion ladder** that runs daily against live Phoenix and turns repetitive
agent work into systematic work:

- **Rung 1 — prompt → skill:** a prompt pattern recurring across multiple users
  with no skill covering it becomes a proposed skill.
- **Rung 2 — skill/cluster → deterministic:** a cluster whose LLM answers and
  route barely change between occurrences becomes a proposed deterministic
  handler (no LLM call).

The tool is **advisory**: it detects candidates, tracks their lifecycle across
daily runs, and writes draft artifacts (a `SKILL.md`, a Python stub, a decision
table) into a capability-owned directory for a human to review and wire in. It
never sits in the request path. The UI becomes a separate React SPA.

---

## 2. Problem statement

Analyst-facing agents answer the same questions the same way, over and over, at
LLM cost and latency, with LLM variance. Two transformations recover
determinism:

1. When many users ask the same thing and the agent has no dedicated skill, it
   re-derives the approach each time. A skill fixes the approach.
2. When a skill exists (or the raw behaviour is already stable) and the agent's
   reasoning does not actually vary — same inputs, same answer shape, same tool
   route — the LLM call is ceremony. Deterministic code removes the cost, the
   latency, and the variance.

The tool must find both, per capability (FOBO, PLEX, flash-vs-formal, or any use
case), with evidence strong enough to act on, and must keep finding them as
traffic evolves — hence daily runs and lifecycle tracking.

---

## 3. Goals / non-goals

### Goals

- A capability is created, filtered, and analysed independently; many capabilities
  share one span pool.
- Daily run per capability: incremental scrape → scoped analyse → recompute both
  rungs → advance candidate lifecycle.
- Every candidate is a persistent record with a status machine, an evidence
  trend, and an audit log of human decisions.
- Promotion writes real draft files into `capabilities/<id>/`.
- A separate React SPA drives the whole loop; the API stops serving HTML.
- All 538 existing tests stay green throughout; new work lands in phases.

### Non-goals (v1)

- The tool does not serve traffic or route requests (advisory only).
- No LLM-as-judge for Rung 2 (lexical signal only; seam left for one).
- No embedding-based clustering (stays lexical: normalize + rapidfuzz).
- No SSO / user accounts (`actor` is an operator name in the request).
- No background job queue (runs are synchronous, like today's `/analyze/run`).
- No notifications (Slack/email).
- No multi-Phoenix-instance support.
- The runtime that consumes the artifacts (Rung-1-B / Rung-2-B) is out of scope,
  but artifact formats are designed so it is buildable later.

---

## 4. Decisions locked in

| # | Decision |
|---|----------|
| 1 | **Capability model** = a named record: a saved query (Phoenix project, `workflow_stage`, `asset_class`, `model_name`, prompt `search`, default time window) + an owned directory `capabilities/<id>/` (`capability.yaml` + `skills/*.md`). Scope = spans matching the filter within the run window. |
| 2 | **Rung 2 signal** = lexical determinism score: output-template concentration + route invariance + output self-similarity + slot stability. No LLM judge in v1. |
| 3 | **Tool owns files** — scaffolds the capability dir; writes draft `SKILL.md` (Rung 1) and `deterministic/*` stubs (Rung 2) into it for review in place; never edits hand-authored files. Skill format = `SKILL.md` + YAML frontmatter (the existing scanner). |
| 4 | **Frontend** = new `frontend/` SPA, React + Vite + TypeScript, HTTP-only to the API, served independently. Centered on the capability + ladder loop; existing analytics carried over as scoped panels. API stops serving HTML. |
| 5 | **Live-first**, designed to run daily against real Phoenix; fixtures / JSONL kept for dev, tests, demo. |
| 6 | **Full candidate lifecycle** — persistent records, status machine (`new → accumulating → ready → accepted / rejected / snoozed → promoted`), first-seen date, evidence trend, decision + actor. |
| 7 | **v1 = full vertical slice**, thin — every piece above, end to end. |
| 8 | **Approach 1** — evolve `phoenix_scraper` in place; do not re-layer or rebuild. Package name stays for v1; a rename is a later, separate change. |
| — | **Users:** no SSO in v1. `actor` comes from the decision request payload (default from `Settings.operator_name`). API auth stays the shared `X-API-Key`. |

---

## 5. Current state (context for the implementer)

Key modules (all pure functions, DataFrame-in/out where analytical; files < 400
lines; frozen pydantic models; TDD):

- `phoenix_client.py` — the **only** module that talks to Phoenix.
- `scraper.py` — watermarked incremental scrape (watermark keyed
  `phoenix:<project>`), OpenInference flattening, JSONL ingest.
- `storage.py` — single-writer SQLite. Analysis tables
  (`prompt_clusters`, `cluster_members`, `skill_matches`, `skill_proposals`,
  `sessions`) are **replaced wholesale** per `run_analysis`. `span_evaluations`
  keyed `(span_id, name, source)`. `analysis_runs` + `cluster_snapshots` hold a
  bounded run history for diffing.
- `normalize.py` — `normalize_prompt` / `prompt_signature`: mask volatile tokens
  (`<num> <date> <ccy> <id> <book> <desk>`).
- `cluster.py` — `build_clusters(spans_df, fuzz_threshold)`; `cluster_id =
  sha1(signature)[:12]` (stable across runs for the same signature).
- `skills.py` — `load_all_skills(settings)` = catalog YAML + scanned `SKILL.md`
  trees, de-duped by name.
- `taxonomy.py` — keyword maps; `suggest_level(text) -> (level, asset_class,
  capability)`.
- `skills_mapper.py` — `score_match` (0.5 keyword + 0.5 fuzzy); `match_clusters`
  → `SkillMatch` (≥ `skill_match_threshold`, default 0.55) or `SkillGapProposal`.
- `skill_coverage.py` — `coverage_score` vs a skill's own `example_prompts`;
  `annotate_coverage` (covered when ≥ `skill_coverage_threshold`, default 0.70);
  `cluster_deltas` (NEW/GROWING/STABLE/SHRINKING/GONE); `suggested_updates`
  (paste-ready `example_prompts` / `keywords` per file).
- `evaluations.py` — 13 CODE checks (`PASS_SCORE = 0.5`, higher is better),
  applicability-gated.
- `insights*.py` — `trace_profiles`, `question_taxonomy`, `session_friction`,
  `cluster_efficiency` (`route_len_avg`, `long_route`, `opportunity_score`),
  `skill_health`, `agent_flows` (`_flow_signature` collapses consecutive kinds,
  e.g. `LLM → TOOL ×3 → LLM`), `tool_usage`, `model_usage`, `user_profiles`,
  quality rollups.
- `pipeline.py` — `run_analysis(store, settings, filters)`.
- `cli.py` — Typer app `pheonix` (`demo seed scrape ingest analyze evaluate
  coverage report export serve doctor`).
- `api.py` — `create_app(settings)` factory; ~30 routes under a `protected`
  router (X-API-Key via `APIKeyHeader`); CSRF origin guard middleware; serves
  `static/dashboard.html` at `GET /`.

`SpanRecord` fields the ladder relies on: `span_id, trace_id, session_id,
project, span_kind, start_time, latency_ms, status_code, model_name, user_id,
workflow_stage, asset_class, input_text, output_text, tokens_*, cost_usd,
attributes`.

---

## 6. Architecture overview

```
                       ┌──────────────────────────────────────────────┐
   Phoenix (live)  ───► │  scrape (incremental, watermark per PROJECT) │
                       └───────────────────────┬──────────────────────┘
                                               ▼
                                    ┌────────────────────┐
                                    │  spans (SHARED)    │   one pool, one DB
                                    └─────────┬──────────┘
                     capability.yaml          │  filter + window
                  (disk = source of truth)    ▼
   capabilities/<id>/  ◄─── sync ───►  ┌───────────────────────────┐
     capability.yaml                   │  run_capability_analysis  │  per capability, daily
     skills/*.md         ◄──scan──     │  costs→clusters→sessions  │
     deterministic/*     ◄──write──    │  →skills→matches→coverage │
                                       │  →efficiency→evaluate     │
                                       └───────────┬───────────────┘
                                                   ▼
                          ┌──────────────────┐         ┌──────────────────────┐
                          │  Rung 1 detect   │         │  Rung 2 determinism  │
                          │  (ladder.py)     │         │  (determinism.py)    │
                          └────────┬─────────┘         └──────────┬───────────┘
                                   └───────────┬──────────────────┘
                                               ▼
                              ┌─────────────────────────────────┐
                              │  candidates / observations /    │  persistent, per capability
                              │  decisions  +  state machine    │
                              └───────────────┬─────────────────┘
                                              ▼
                             FastAPI (headless)  ◄──HTTP──  React SPA (frontend/)
```

Everything derived is keyed by `capability_id`. Spans, `span_evaluations`, and
the scrape watermark are shared and capability-agnostic.

---

## 7. Section 1 — Storage & domain model

### 7.1 Unchanged

- **Scraping**: incremental, watermarked per Phoenix *project*
  (`phoenix:<project>`), `span_id` PK. Capabilities never scrape.
- **`spans`**, **`span_evaluations`**, **`scrape_state`** tables: unchanged.
- **Legacy path**: `run_analysis` + `prompt_clusters`/`skill_matches`/… +
  `analysis_runs`/`cluster_snapshots` + the unscoped API routes keep working
  (effectively an implicit "all spans" capability) for one release, marked
  legacy. Removed in a follow-up after the SPA Analytics tab reaches parity.

### 7.2 New tables

Column lists are indicative; the implementer follows existing `storage.py`
conventions (ISO strings for timestamps, JSON-encoded lists/dicts, `INSERT OR
REPLACE`, per-request `Store`).

**`capabilities`** — a synced mirror of `capability.yaml` (disk is source of truth):

```
capability_id      TEXT PRIMARY KEY      -- slug, e.g. "fobo"
name               TEXT NOT NULL
description        TEXT NOT NULL DEFAULT ''
filter_project     TEXT                  -- all nullable
filter_workflow_stage TEXT
filter_asset_class TEXT
filter_model_name  TEXT
filter_search      TEXT
window_days        INTEGER NOT NULL DEFAULT 30
thresholds_json    TEXT NOT NULL DEFAULT '{}'   -- per-capability overrides of §10 defaults
status             TEXT NOT NULL DEFAULT 'active'  -- active | paused
created_at         TEXT NOT NULL
updated_at         TEXT NOT NULL
```

**`capability_runs`** — one row per capability per daily run:

```
run_id             TEXT NOT NULL         -- ISO timestamp of the run
capability_id      TEXT NOT NULL
started_at         TEXT NOT NULL
finished_at        TEXT
window_start       TEXT NOT NULL
window_end         TEXT NOT NULL
n_spans            INTEGER NOT NULL DEFAULT 0
n_in_scope_spans   INTEGER NOT NULL DEFAULT 0
n_clusters         INTEGER NOT NULL DEFAULT 0
n_rung1_candidates INTEGER NOT NULL DEFAULT 0
n_rung2_candidates INTEGER NOT NULL DEFAULT 0
status             TEXT NOT NULL DEFAULT 'ok'   -- ok | partial | failed
notes_json         TEXT NOT NULL DEFAULT '[]'   -- ["scrape failed, used stored spans", "Rung 2: 4 clusters skipped (no output text)"]
PRIMARY KEY (capability_id, run_id)
```

**`capability_cluster_snapshots`** — generalises today's `cluster_snapshots`
(adds `capability_id`); feeds `cluster_deltas` and the Analytics tab:

```
capability_id  TEXT NOT NULL
run_id         TEXT NOT NULL
cluster_id     TEXT NOT NULL
signature      TEXT NOT NULL DEFAULT ''
representative TEXT NOT NULL DEFAULT ''
count          INTEGER NOT NULL DEFAULT 0
n_users        INTEGER NOT NULL DEFAULT 0
matched_skill  TEXT
covered        INTEGER NOT NULL DEFAULT 0     -- 0/1
in_scope       INTEGER NOT NULL DEFAULT 1
route_len_avg  REAL
long_route     INTEGER NOT NULL DEFAULT 0
first_seen     TEXT
last_seen      TEXT
PRIMARY KEY (capability_id, run_id, cluster_id)
```

Pruned to `run_history_limit` runs per capability (existing prune logic,
generalised).

**`candidates`** — the persistent ladder record:

```
candidate_id       TEXT PRIMARY KEY
capability_id      TEXT NOT NULL
rung               TEXT NOT NULL            -- 'skill' | 'deterministic'
subtype            TEXT NOT NULL DEFAULT '' -- rung 'skill': 'new_skill' | 'strengthen_skill'
cluster_id         TEXT NOT NULL            -- the stable anchor
title              TEXT NOT NULL            -- representative prompt (trimmed)
signature          TEXT NOT NULL
matched_skill      TEXT                     -- for strengthen_skill / rung 2
status             TEXT NOT NULL DEFAULT 'new'
  -- new | accumulating | insufficient_data | ready | accepted | snoozed
  -- | rejected | promoted | stale   (transitions: §10.1)
first_seen_run_id  TEXT NOT NULL
first_seen_at      TEXT NOT NULL
last_seen_run_id   TEXT NOT NULL
last_seen_at       TEXT NOT NULL
ready_at           TEXT                     -- first time it reached 'ready'
promoted_at        TEXT
promoted_artifact_paths_json TEXT NOT NULL DEFAULT '[]'
snooze_until_run   INTEGER                  -- run ordinal to unsnooze at (§10.1)
dismiss_reason     TEXT
decided_by         TEXT
decided_at         TEXT
current_evidence_json TEXT NOT NULL DEFAULT '{}'  -- latest metrics snapshot
```

`candidate_id`:
- Rung 1: `f"{capability_id}:s:{cluster_id}"`
- Rung 2: `f"{capability_id}:d:{cluster_id}"`

`cluster_id` is `sha1(signature)[:12]` — stable while the signature is stable.
Signature drift from fuzzy-merge changes causes identity churn; accepted for v1,
listed in §16.

**`candidate_observations`** — one row per candidate per run (the evidence trend):

```
candidate_id       TEXT NOT NULL
run_id             TEXT NOT NULL
observed_at        TEXT NOT NULL
count              INTEGER NOT NULL DEFAULT 0
n_users            INTEGER NOT NULL DEFAULT 0
n_sessions         INTEGER NOT NULL DEFAULT 0
total_cost_usd     REAL NOT NULL DEFAULT 0
score              REAL                    -- rung 1: gap strength; rung 2: determinism_score
signals_json       TEXT NOT NULL DEFAULT '{}'  -- rung 2 sub-signals + n_answer_spans; rung 1 route stats
met_evidence_bar   INTEGER NOT NULL DEFAULT 0  -- 0/1 (§9.1)
crossed_threshold  INTEGER NOT NULL DEFAULT 0  -- 0/1: met the bar this run, hadn't last run
PRIMARY KEY (candidate_id, run_id)
```

Pruned with the run history.

**`candidate_decisions`** — append-only audit log:

```
id           INTEGER PRIMARY KEY AUTOINCREMENT
candidate_id TEXT NOT NULL
run_id       TEXT                       -- run in effect when decided, if any
action       TEXT NOT NULL              -- accept | reject | snooze | reopen | promote
actor        TEXT NOT NULL
note         TEXT NOT NULL DEFAULT ''
created_at   TEXT NOT NULL
```

### 7.3 Models (`models.py`, frozen)

`Capability`, `CapabilityFilter`, `CapabilityRun`, `Candidate`,
`CandidateObservation`, `CandidateDecision`, plus enums/`Literal`s for `rung`,
`subtype`, candidate `status`, decision `action`.

---

## 8. Section 2 — The capability workspace

### 8.1 Directory layout

```
capabilities/
  fobo/
    capability.yaml
    skills/
      fobo-break-triage.md          # hand-authored (yours) — never modified
      recon-break-explain.md        # Rung-1 draft, frontmatter status: draft
    deterministic/
      recon-break-explain.py        # Rung-2 stub
      recon-break-explain.md        # the case: evidence, templates, route, open decisions
      test_recon_break_explain.py   # real observed (prompt -> output) pairs as fixtures
```

Root is `Settings.capabilities_dir` (default `capabilities/`).

### 8.2 `capability.yaml`

```yaml
id: fobo
name: FOBO reconciliation
description: Front-office/back-office recon break triage across asset classes.
filter:
  project: pnl-agent          # optional; omit/null = all projects
  workflow_stage: fobo_recon  # optional
  asset_class: null           # optional
  model_name: null            # optional
  search: null                # optional substring on input_text
window_days: 30
thresholds:                   # optional; omitted keys fall back to §10 defaults
  rung1_min_users: 3
  rung1_min_count: 15
  rung1_sustained_runs: 5
  rung2_min_answer_spans: 10
  rung2_determinism_score: 0.8
  rung2_sustained_runs: 3
status: active                # active | paused
```

`capability.py`:
- `load_capability(dir) -> Capability` — parse + validate (tolerant of missing
  optional keys; clear errors on malformed).
- `write_capability(capability, dir)` — used by `POST /capabilities` and
  `PATCH`.
- `scaffold_capability(id, ...) -> Path` — create the dir, `skills/`,
  `deterministic/`, and `capability.yaml`.
- `sync_capability(store, dir)` — upsert the `capabilities` row from yaml.
- `capability_skill_dirs(capability) -> list[Path]` — `[<dir>/skills]`, merged
  into the skill scan for that capability's run (in addition to
  `Settings.skills_catalog` and `PHEONIX_SKILLS_DIRS`).

### 8.3 Rung-1 artifact — `skills/<name>.md`

Written on **promote** for `subtype: new_skill`. Name = the proposal's
kebab-case `proposed_name` (from `skills_mapper`), de-collided against existing
files.

```markdown
---
name: recon-break-explain
description: Explain the cause of a reconciliation break given book and amount.
level: capability
capability: fobo
keywords: [recon, break, explain, cause, unmatched]
example_prompts:
  - "why is there a recon break of 100k on the credit book"
  - "explain the fx recon break on EURUSD_LDN"
status: draft
source_candidate: fobo:s:a1b2c3d4e5f6
evidence:
  first_seen: 2026-08-10
  asks: 214
  users: 7
  runs_sustained: 6
---

# recon-break-explain

<!-- Draft scaffolded by pheonix from candidate fobo:s:a1b2c3d4e5f6.
     Fill in the procedure, then set status: active. pheonix stops proposing
     this candidate once a skill matches and demonstrates it. -->

## When to use
Recurring across 7 analysts; <N> asks over <first_seen>–<today>.

## Procedure
1. TODO
```

- `keywords`: `distinctive_words(signature)` minus placeholder tokens and words
  already in the name/description (reuse `skill_coverage.suggested_updates`
  logic).
- `example_prompts`: up to `max_suggested_prompts` real cluster members, most
  frequent first, lightly de-duplicated.
- `level` / `capability` / `asset_class`: from `taxonomy.suggest_level` on the
  representative, but `capability` defaults to this capability's id.

For **`subtype: strengthen_skill`** (cluster matched a skill but
`coverage_score < skill_coverage_threshold`): promote does **not** write a new
file — it returns the paste-ready `example_prompts` / `keywords` block for the
matched skill's file (today's `skill_updates.md` behaviour) and records the
target path in `promoted_artifact_paths`.

### 8.4 Rung-2 artifact — `deterministic/<name>.{py,md}` + `test_<name>.py`

```python
"""Deterministic replacement for the LLM step behind `recon-break-explain`.

Scaffolded by pheonix from candidate fobo:d:a1b2c3d4e5f6.
Evidence (run 2026-09-07): determinism_score 0.86.
  template_concentration 0.75 (41 answers -> 2 templates)
  route_invariance       0.93 (LLM -> fetch_breaks -> LLM)
  output_self_similarity 0.91
  slot_stability         0.88

Observed output templates:
  T1 (34/41): "The <ccy> break of <num> on <book> is caused by an unsettled
              trade. Recommend posting an adjustment."
  T2 (7/41):  "The <ccy> break of <num> on <book> matches a missing dividend
              accrual. Recommend accruing <num>."
"""
from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "unsettled_trade": "The {ccy} break of {amount} on {book} is caused by an unsettled trade. Recommend posting an adjustment.",
    "missing_dividend": "The {ccy} break of {amount} on {book} matches a missing dividend accrual. Recommend accruing {accrual}.",
}

# Present only when slot_stability is high: masked input signature -> template key.
DECISION_TABLE: dict[str, str] = {
    "why is there a recon break of <num> on <book>": "unsettled_trade",
    # ...
}


def handle(prompt: str, breaks: list[dict]) -> str:
    """TODO: extract ccy/amount/book from `prompt`; classify the cause from
    `breaks`; return TEMPLATES[key].format(...). The test file has all 41 real
    cases as a green-bar target."""
    raise NotImplementedError
```

- `test_<name>.py`: `pytest.mark.parametrize` over the real observed
  `(input_text, output_text)` pairs, asserting the (once implemented) `handle`
  output matches modulo whitespace. Ships red.
- `<name>.md`: full case write-up — evidence table, all templates with counts,
  the route-flow distribution, the sample-span ids, and an "Open decisions"
  section (what a human must still choose: the slot extraction, the classifier
  input, error handling).

### 8.5 CRUD

- CLI: `pheonix capability new <id> [--name --project --stage --asset-class
  --search --window-days]`, `pheonix capability list`, `pheonix capability show
  <id>`, `pheonix capability sync [<id>|--all]`.
- API: §11.
- `DELETE /capabilities/{id}` removes the DB row only; `?purge=true` also removes
  the directory.

---

## 9. Section 3 — The two rungs

New pure modules: `ladder.py` (Rung 1 + lifecycle), `determinism.py` (Rung 2
signal). DataFrame-in style matching `insights.py`. Both operate on the
**in-scope frame** = `store.spans_frame(capability_filter + window)`.

### 9.1 Rung 1 — prompt → skill

Reuse: `build_clusters` → `load_all_skills` (catalog + `PHEONIX_SKILLS_DIRS` +
the capability's `skills/`) → `match_clusters` → `annotate_coverage` →
`cluster_efficiency`.

A **Rung-1 candidate** is an in-scope cluster that is either:
- **`new_skill`**: no skill scored ≥ `skill_match_threshold` (0.55); or
- **`strengthen_skill`**: matched a skill but `coverage_score <
  skill_coverage_threshold` (0.70).

**Candidate creation floor:** a `candidates` row is created once `count ≥
max(3, rung1_min_count // 3)` — earlier than the evidence bar, so the trend is
visible while it builds, but not for one-off asks. Below the floor the cluster
is analysed and snapshotted as normal but no candidate record exists.

Observation metrics: `count` (asks), `n_users`, `n_sessions`, `total_cost_usd`,
`route_len_avg`, `long_route`, plus `score` = the gap strength:
- `new_skill`: `1 - best_match_score` (0 when a skill nearly matched, →1 when
  nothing is close).
- `strengthen_skill`: `(skill_coverage_threshold - coverage_score) /
  skill_coverage_threshold`, clamped `[0, 1]`.

**Evidence bar** (`met_evidence_bar`, per run): `n_users ≥ rung1_min_users` AND
`count ≥ rung1_min_count`.

**Readiness** (`accumulating → ready`): the last `rung1_sustained_runs`
observations ALL have `met_evidence_bar = 1`. A capability with fewer than
`rung1_sustained_runs` recorded runs cannot yet have `ready` candidates.

### 9.2 Rung 2 — cluster/skill → deterministic

Eligibility for scoring: the cluster has `n_answer_spans ≥
rung2_min_answer_spans` (10) where an answer span is a member span with
`span_kind == "LLM"` and non-empty `output_text`. Below that → candidate exists
but status is pinned at `insufficient_data` (a terminal-ish holding state; it
resumes the normal machine once eligible) and the run note records the count.

Rung 2 runs on **every** eligible in-scope cluster — a covered cluster (the
skill "works") and an uncovered high-frequency cluster alike; determinism is
orthogonal to whether a skill exists.

**`mask_volatile(text)`** — extracted from `normalize.py` so `prompt_signature`
and output-masking share it. Same token classes (`<num> <date> <ccy> <id>
<book> <desk>`), lexical.

**Sub-signals** (each 0–1, all recorded in `signals_json`):

| Signal | Definition |
|---|---|
| `template_concentration` | Mask every answer with `mask_volatile`; group identical masked strings; greedily merge groups whose representatives score `token_set_ratio ≥ cluster_fuzz_threshold` (same merge as `build_clusters`) into templates. `k` = distinct templates needed to cover ≥ 90% of answers. `concentration = max(0, 1 - (k - 1) * 0.25)` → k=1→1.0, k=2→0.75, k=3→0.5, k≥5→0. |
| `route_invariance` | Map member span ids → trace ids (as `cluster_efficiency` does), compute `_flow_signature` per trace. `= modal_flow_count / n_traces`. **N/A** (excluded from the blend, noted) when no member trace has any `TOOL`/`RETRIEVER`/`AGENT`/`CHAIN` span. |
| `output_self_similarity` | Mean pairwise `token_set_ratio / 100` over masked answers (sample ≤ 200 answers / ≤ 5000 pairs). |
| `slot_stability` | For each distinct masked-*input* signature within the cluster, the modal output template's share; frequency-weighted mean across input signatures. 1.0 = every input phrasing always yields the same template. |

**`determinism_score`** = `Σ(wᵢ·sᵢ) / Σ(wᵢ)` over available signals, weights:
`template_concentration 0.4, slot_stability 0.3, output_self_similarity 0.2,
route_invariance 0.1`.

**Candidate creation floor:** a Rung-2 `candidates` row is created the first run
`determinism_score ≥ 0.5`. Below that there is real reasoning variance and no
record is kept — this keeps the table proportional to signal, not to cluster
count.

**Evidence bar** (per run): `determinism_score ≥ rung2_determinism_score` (0.8)
AND `n_answer_spans ≥ rung2_min_answer_spans`.

**Readiness**: last `rung2_sustained_runs` (3) observations ALL met the bar. A
capability with fewer than `rung2_sustained_runs` recorded runs cannot yet have
`ready` Rung-2 candidates.

**Reported non-signals:** low score is a real "keep the LLM" answer, not a
failure; `insufficient_data` is never silently dropped — the `capability_run`
note carries `"Rung 2: N clusters skipped (no output text)"`.

---

## 10. Section 4 — Daily run & candidate lifecycle

### 10.1 Status machine

| From → To | Trigger |
|---|---|
| — → `new` | first detected in a run (Rung 2: and `determinism_score ≥ 0.5`) |
| `new` → `accumulating` | detected again in a later run |
| `new`/`accumulating` → `insufficient_data` | Rung 2 only: `n_answer_spans < rung2_min_answer_spans` this run |
| `insufficient_data` → `accumulating` | Rung 2 only: became eligible again |
| `accumulating` → `ready` | readiness met (§9.1 / §9.2) |
| `ready` → `accepted` | human `accept` (records `actor`, `decided_at`) |
| `accepted` → `promoted` | human `promote` → artifact written, paths recorded |
| `ready` → `promoted` | human `promote?accept=true` (one step) |
| `accumulating`/`ready` → `rejected` | human `reject` + reason; suppressed from the board's default view |
| `accumulating`/`ready` → `snoozed` | human `snooze` (N runs); suppressed until `capability_runs` count for this capability passes `snooze_until_run` |
| `snoozed` → `accumulating` | snooze expired (automatic, in the run) |
| `rejected` → `accumulating` | **material change** only: `count ≥ material_change_count_factor ×` count-at-rejection OR `n_users ≥ n_users-at-rejection + material_change_users_delta`. Emits a `reopen` decision row + a run note. |
| `ready` → `accumulating` | evidence fell below the bar this run (pattern faded) |
| any non-terminal → `stale` | not observed for `run_history_limit` consecutive runs; record kept |
| `stale` → `accumulating` | observed again |

`promoted` and `rejected` (absent material change) are the resting states.
`promoted` candidates stay visible on the board's `promoted` column.
`snooze_until_run` is an ordinal: `(count of this capability's `capability_runs`
at decision time) + snooze_runs`; runs are ordered by `started_at`.
`insufficient_data` is a holding state, not terminal — it never blocks a later
return to the normal machine.

### 10.2 Daily run algorithm

`pheonix run --capability <id>` | `--all`, or `POST /capabilities/{id}/runs`:

1. **Sync** each target `capability.yaml` → `capabilities` row. Skip `status:
   paused`.
2. **Scrape** — once per distinct `filter_project` across the capabilities being
   run (a null project → the default `Settings.project`). Incremental,
   watermarked. Offline / no Phoenix → skip, use stored spans, add a run note.
   Scrape failure → continue, `status: partial`, run note.
3. **Window** — `window_end = now`, `window_start = now - window_days`; override
   with `--from` / `--to` (or `{from, to}` in the API body).
4. **In-scope frame** — `store.spans_frame(QueryFilters(project, workflow_stage,
   asset_class, model_name, search, start=window_start, end=window_end,
   limit=ANALYSIS_SPAN_LIMIT))`.
5. **Scoped analyse** — costs → clusters → sessions → skills → matches →
   coverage → `cluster_efficiency`. Persist as this capability's current
   analysis (scoped replace) + a `capability_cluster_snapshots` row set for
   `run_id`.
6. **Evaluate** — CODE checks over in-scope spans not yet in `span_evaluations`
   (shared table; `replace_local_evaluations` stays global — scope the *reads*,
   not the writes, or add a scoped variant if a capability's window excludes
   spans another needs; v1: evaluate the union, it is idempotent).
7. **Rung 1** — detect candidates; for each: upsert `candidates`, write
   `candidate_observations`, then run the state machine.
8. **Rung 2** — score eligible clusters; upsert candidates + observations; state
   machine.
9. **Advance lifecycle globally** for this capability: auto-unsnooze, auto-reopen
   on material change, `stale` transitions, `crossed_threshold` flags.
10. **Record** `capability_runs` (counts, notes, status); prune snapshots +
    observations beyond `run_history_limit`.

**Idempotency:** a second run the same calendar day creates a new `run_id`
(another trend point); `--replace-today` reuses the latest `run_id` for the day.
Scrape is idempotent (`span_id` PK). One capability failing never aborts
`--all`.

**Trigger:** CLI (for cron / the `schedule` skill) and API. No embedded
scheduler, no daemon.

### 10.3 Decisions

`POST /candidates/{cid}/decision` `{action, actor, note, snooze_runs?}` appends a
`candidate_decisions` row and applies the transition. `actor` defaults to
`Settings.operator_name` when omitted. Invalid transitions → 409 with the
current status.

---

## 11. Section 5 — API surface

All under the existing `protected` router (X-API-Key). CSRF origin guard covers
new POSTs. `PHEONIX_CORS_ORIGINS` (comma-separated) is added; the origin guard
allows configured origins. FastAPI `/openapi.json` drives the typed client.

### Capabilities

| Method & path | Purpose |
|---|---|
| `GET /capabilities` | list — id, name, status, filter summary, last run + status, ready/accepted counts per rung |
| `POST /capabilities` | create — body `{id, name, description, filter, window_days, thresholds}`; writes `capability.yaml`, scaffolds the dir, upserts the row |
| `GET /capabilities/{id}` | yaml contents + last-run summary + skill-file list |
| `PATCH /capabilities/{id}` | update filter / window / thresholds / status; rewrites the yaml |
| `DELETE /capabilities/{id}` | remove the row; `?purge=true` deletes the dir |
| `POST /capabilities/{id}/sync` | re-read a hand-edited yaml into the DB |

### Runs (synchronous)

| Method & path | Purpose |
|---|---|
| `POST /capabilities/{id}/runs` | trigger a run now; body `{from?, to?, replace_today?}`; returns the run summary |
| `GET /capabilities/{id}/runs` | run history |
| `GET /capabilities/{id}/runs/{run_id}` | one run's detail + notes |
| `GET /capabilities/{id}/runs/delta?from=&to=` | `cluster_deltas` between two runs |

### Ladder

| Method & path | Purpose |
|---|---|
| `GET /capabilities/{id}/candidates?rung=&status=` | the board |
| `GET /candidates/{cid}` | evidence + observation trend + sample exchanges + (Rung 2) templates/flows/slot matrix + decision history |
| `POST /candidates/{cid}/decision` | `{action: accept\|reject\|snooze\|reopen, actor, note, snooze_runs?}` |
| `POST /candidates/{cid}/promote` | writes artifact(s); returns `{paths, contents}`; `?accept=true` allows `ready → promoted` |
| `GET /candidates/{cid}/artifact/preview` | render what promote *would* write, without writing |

### Scoped analytics

Every existing route (`/overview`, `/insights/*`, `/quality/*`, `/skills/*`,
`/prompts/frequent`, `/sessions`, `/costs/summary`, `/spans`, `/runs`,
`/runs/delta`) gains an **optional `capability` query param**. When present, the
capability's filter + default window merge into the `QueryFilters` (explicit
`start`/`end`/other params still win). When absent, behaviour is byte-for-byte
as today. Response conventions unchanged (`_frame_response`, `fmt=csv`).

### Auth / identity

Unchanged X-API-Key. `actor` travels in decision/promote bodies. No new
middleware.

---

## 12. Section 6 — Frontend

**Stack:** React 18 + Vite + TypeScript in `frontend/`. TanStack Query; types
from `openapi-typescript` over a thin fetch wrapper. React Router. **No
component library** — components reuse the existing dashboard's design tokens
(CSS-variable palette, system fonts, light/dark-follows-system). Evidence trend
= inline-SVG sparkline, no charting dependency. API key in `sessionStorage`,
sent as `X-API-Key`.

**Serving:** Vite dev server proxies to the API on `:8000`; `npm run build` →
static bundle (any static host, or a `pheonix serve-ui` convenience). API stops
serving HTML (`GET /` removed or a JSON notice).

**Screens:**

1. **Capabilities index** (`/`) — one card per capability: filter summary, last
   run + status, a badge per rung (`Rung 1: 3 ready · Rung 2: 1`). "New
   capability" → form with filter dropdowns from `/filters/options`.
2. **Capability detail** (`/c/:id`) — filter + window; **Run now** (optional
   from/to); last-run summary (spans, in-scope, clusters, candidates by
   rung/status). Two lanes:
   - **Rung 1 — Promote to skill**: column board by status (`accumulating` /
     `ready` / `accepted` / `promoted`; rejected + snoozed behind a toggle).
     Card: representative prompt, asks, users, sustained progress (`5/5`),
     `long_route` flag, sparkline.
   - **Rung 2 — Make deterministic**: same board; card shows `determinism_score`
     with its 4 sub-signals as micro-bars, `41 → 2 templates`, route-invariance
     %.
3. **Candidate detail** (`/c/:id/candidate/:cid`) — decision actions (Accept /
   Reject / Snooze / Reopen + note + actor, actor remembered in
   `sessionStorage`); evidence trend chart; Rung 1: sample prompts + why still a
   gap; Rung 2: observed templates with slots highlighted, route-flow
   breakdown, sample `(prompt → answer)` table, slot-stability matrix; artifact
   preview (exact file contents) + Promote.
4. **Analytics tab** (`/c/:id/analytics`) — carried-over panels (KPI row,
   coverage, "what to add to each skill", validation scoreboard, answer quality
   by user/model, agent flows, users, run deltas), each hitting the existing
   endpoints with `?capability=:id`. The old dashboard's migration path.

**Global:** API-key gate; light/dark follows system; error toasts; poll-on-focus
(no realtime).

**Out of v1:** drag-between-columns, realtime, any component kit.

---

## 13. Section 7 — Delivery plan

All 538 tests stay green throughout. Backend phases A–E ship and test behind the
CLI before any UI exists.

| Phase | Scope | Key tests |
|---|---|---|
| **A — Capability entity** | `Capability`/`CapabilityFilter` models; `capability.py` (yaml read/write, scaffold, sync, `capability_skill_dirs`); `capabilities` table + CRUD; `pheonix capability new\|list\|show\|sync`. No change to the existing pipeline. | yaml round-trip, scaffold, sync, CLI |
| **B — Scoped run** | `run_capability_analysis()` (existing `run_analysis` untouched); `capability_runs` + `capability_cluster_snapshots` + scoped current-analysis storage; `pheonix run --capability\|--all` (scrape once per project → analyse → record); generalise `cluster_deltas` with `capability_id`; partial-failure resilience. | scoping correctness, run recording, `--all` isolation, scrape-failure path |
| **C — Rung 1 + lifecycle** | `Candidate`/`CandidateObservation`/`CandidateDecision` models + tables; Rung-1 detection in `ladder.py`; the state machine (`advance_lifecycle`, material-change reopen, snooze/stale); Rung-1 `skills/<name>.md` writer + strengthen-skill block; `pheonix candidates\|decide\|promote`. | table-driven transitions, sustained-runs, reopen-on-material-change, draft file contents, idempotent re-runs |
| **D — Rung 2** | shared `mask_volatile()`; `determinism.py` (4 sub-signals, blend, guards, `insufficient_data`); wire into the run + state machine; the 3 `deterministic/` files. | each sub-signal on crafted frames, `insufficient_data` path, route-N/A renormalisation, stub + test-file generation |
| **E — API** | capability / run / ladder routes; `?capability=` on existing analytics routes; `PHEONIX_CORS_ORIGINS` + origin-guard allowance. | each route, auth, back-compat when param omitted, CORS + CSRF coexistence |
| **F — Frontend** | `frontend/` scaffold (Vite + React + TS), typed client, the 4 screens, key gate; `make ui` / `make ui-build`. | Vitest component tests (board, candidate detail, decision flow); one Playwright smoke on a seeded fixture capability |
| **G — Retire bundled dashboard** | move `static/dashboard.html` out once the Analytics tab reaches parity; drop `GET /` HTML; rewrite `README.md` + `CONTRACTS.md`; add the new `Settings` fields to `.env.example`. Legacy `run_analysis` + unscoped routes kept one release, marked legacy. | docs build; no dead routes |

**Fixtures:** extend `fixtures.py` with a deterministic-by-construction cluster
(N identical-shape answers differing only in masked slots, identical tool route)
and a genuinely-varying cluster, so Rung 2 has both a positive and a negative in
the offline demo. Add a `pheonix capability new demo-fobo` path to `make demo`.

**Sequencing:** A → B → C → D each a PR; E one or two; F two or three; G one.

---

## 14. New `Settings` fields

| Field | Env | Default | Purpose |
|---|---|---|---|
| `capabilities_dir` | `PHEONIX_CAPABILITIES_DIR` | `capabilities` | root of the owned dirs |
| `cors_origins` | `PHEONIX_CORS_ORIGINS` | `""` | comma-separated allowed SPA origins |
| `operator_name` | `PHEONIX_OPERATOR_NAME` | `""` | default `actor` for decisions |
| `rung1_min_users` | `PHEONIX_RUNG1_MIN_USERS` | `3` | Rung-1 evidence bar |
| `rung1_min_count` | `PHEONIX_RUNG1_MIN_COUNT` | `15` | Rung-1 evidence bar |
| `rung1_sustained_runs` | `PHEONIX_RUNG1_SUSTAINED_RUNS` | `5` | consecutive runs to `ready` |
| `rung2_min_answer_spans` | `PHEONIX_RUNG2_MIN_ANSWER_SPANS` | `10` | Rung-2 eligibility |
| `rung2_determinism_score` | `PHEONIX_RUNG2_DETERMINISM_SCORE` | `0.8` | Rung-2 evidence bar |
| `rung2_sustained_runs` | `PHEONIX_RUNG2_SUSTAINED_RUNS` | `3` | consecutive runs to `ready` |
| `material_change_count_factor` | `PHEONIX_MATERIAL_CHANGE_COUNT_FACTOR` | `1.5` | reopen threshold |
| `material_change_users_delta` | `PHEONIX_MATERIAL_CHANGE_USERS_DELTA` | `2` | reopen threshold |

`run_history_limit` (existing, default 20) also bounds per-capability snapshots
and observations.

---

## 15. CONTRACTS.md additions (to write in Phase A–D)

New frozen contracts for: `capability.py`, `ladder.py`, `determinism.py`, the
new `storage.py` methods, `pipeline.run_capability_analysis`, and the
`normalize.mask_volatile` extraction. Same format as the existing file.

---

## 16. Risks, limitations, open questions

1. **Cluster identity churn.** `candidate_id` is anchored on
   `sha1(signature)[:12]`. When fuzzy-merge reshapes a cluster, the anchor can
   move and a candidate's history splits. Mitigation for v1: none beyond noting
   it; a later fix could carry a `prev_signatures` set and reconcile.
2. **Lexical determinism is conservative.** `mask_volatile` + rapidfuzz will
   miss "PLEX" ≡ "attribution" style equivalence, so `template_concentration`
   can under-report determinism. That is the safe direction (fewer false
   "make it deterministic" calls). The LLM-judge seam (`signals_json` +
   `determinism_score` blend) is where a semantic confirmer slots in later.
3. **Output text availability on live Phoenix.** Rung 2 needs
   `attributes.output.value` and real `TOOL` spans. Unknown whether the target
   agent emits them. The `insufficient_data` state and explicit run notes make
   the gap visible rather than silent; if it is widespread, Rung 2 degrades to
   templates + self-similarity only (route N/A) and the score renormalises.
4. **Synchronous runs.** A 30-day window scrape + analyse for a large project
   could exceed a comfortable request timeout. v1 matches today's synchronous
   `/analyze/run`; a job queue is the noted follow-up. The CLI path (cron) is
   unaffected.
5. **Shared `span_evaluations` writes.** `replace_local_evaluations` is global.
   With per-capability windows, evaluating "the union of in-scope spans" each
   run is simplest and idempotent; revisit only if it becomes a hotspot.
6. **`workflow_stage` / `asset_class` attribution** still depends on the agent
   setting `metadata.*` span attributes (fixtures do). Capabilities filtered on
   those fields are only as good as that instrumentation.

---

## 17. Definition of done (v1)

- `pheonix capability new fobo` scaffolds `capabilities/fobo/`.
- `pheonix run --capability fobo` (or `--all`) scrapes, scopes, analyses, and
  updates both rungs' candidates, idempotently, daily.
- Candidates persist with a status machine, an evidence trend, and a decision
  log.
- Accept + promote writes a real draft `SKILL.md` / `deterministic/*` set.
- The React SPA drives create → run → review → decide → promote, and shows the
  carried-over analytics scoped to a capability.
- All existing tests green; new modules at the project's coverage bar (~80%+).
- README + CONTRACTS.md updated; `.env.example` carries the new settings.
