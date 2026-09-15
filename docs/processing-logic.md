# Processing logic

Clustering, prompt shape, Rung 1 / Rung 2 detection, candidate lifecycle,
promotion, and thresholds — as implemented.

---

## 1. Pipeline order (per capability after scrape)

Inside `run_capability_analysis`:

1. Load in-scope spans (`capability_query_filters` + window, limit 100k).
2. Optional span cost update; optional code evaluations (`evaluate_on_analyze`).
3. **`build_clusters`** — lexical signatures + fuzzy merge.
4. **`load_capability_skills`** + **`match_clusters`** + **`annotate_coverage`**.
5. Cluster efficiency (route length signals).
6. **`detect_rung1`** → **`update_rung1`** (lifecycle).
7. **`detect_rung2`** → **`update_rung2`**.
8. **`record_capability_run`** (snapshots + members + `skill_hashes`).
9. **`build_analytics_snapshot`** (or overview-only fallback).

---

## 2. Clustering

`cluster.build_clusters(spans_df, fuzz_threshold)`:

1. Map `input_text` → `extract_user_prompt` (strip Bedrock / USER QUERY wrappers).
2. `prompt_signature` normalize; drop empty signatures.
3. Group by exact signature; merge groups whose signatures have
   `token_set_ratio ≥ cluster_fuzz_threshold` (default **90**).
4. Canonical signature = most frequent variant (tie: lexical).
5. Cluster id = `sha1(signature)[:12]`; sort by count descending.

Metrics per cluster: count, n_users, n_sessions, cost, latency, span_ids,
asset_classes, workflow_stages, representative prompt (modal extracted text).

**Lane split** (`prompt_shape.filter_*` inside `run_capability_analysis`):

| Lane | Input spans | Downstream |
| --- | --- | --- |
| Prompt → skill | `filter_user_ask_spans` — `LLM` + skill-shaped extracted text | match, coverage, Rung 1, snapshot |
| Skill → deterministic | `filter_deterministic_source_spans` — TOOL/RETRIEVER, MCP/SQL/params, non-ask LLM | Rung 2 (members expanded to same trace) |

---

## 3. Prompt shape

`prompt_shape` (mirrored in `frontend/src/lib/promptShape.ts`):

| Function | Role |
| --- | --- |
| `extract_user_prompt` | Prefer `USER QUERY:` / messages[].user / known keys over raw JSON |
| `display_title` | Truncated extracted prompt for cards |
| `is_deterministic_shaped` | MCP tools, SQL heads, file_path blobs, Bedrock wrappers, param dicts |
| `is_skill_shaped` | Not deterministic-shaped (and non-empty) |
| `filter_user_ask_spans` | LLM spans with skill-shaped extracted text (prompt→skill) |
| `filter_deterministic_source_spans` | TOOL/MCP/analysis spans (skill→deterministic) |

Rung 1 **skips** non–skill-shaped representatives so promote-to-skill stays on
user questions. Decide UI re-homes mislabeled skill-rung titles that still look
like payloads.

---

## 4. Skill match & gaps

See [skills.md](./skills.md). Defaults:

| Knob | Default |
| --- | --- |
| `skill_match_threshold` | 0.55 |
| `skill_coverage_threshold` | 0.70 |
| Gap proposal `min_evidence` | 2 |

---

## 5. Rung 1 detection (`detect_rung1`)

For each cluster:

| Gate | Rule |
| --- | --- |
| Volume floor | `count ≥ max(3, rung1_min_count // 3)` |
| Shape | `is_skill_shaped(representative)` |
| New skill | no match or score &lt; match threshold |
| Strengthen | matched but coverage &lt; coverage threshold |
| Skip | matched and coverage ≥ threshold |
| Evidence bar | `n_users ≥ rung1_min_users` **and** `count ≥ rung1_min_count` |

Signal score: gap strength (`1 - best_match` or normalized coverage gap).

### Lifecycle (shared machine)

Statuses of interest: `new` → `accumulating` → `ready` → (`accepted` → `promoted`)
or `rejected` / `snoozed` / `stale` / `insufficient_data`.

- **Ready** when the last `rung1_sustained_runs` observations all meet the
  evidence bar **and** the capability has at least that many runs total.
- **Rejected** auto-reopens on material change:
  `count ≥ 1.5 × count_at_rejection` or `n_users ≥ users_at_rejection + 2`.
- Unobserved for `run_history_limit` runs → `stale`.

Human actions (`DECISION_TRANSITIONS`): accept, reject, snooze, reopen.

---

## 6. Rung 2 detection (`detect_rung2` / `determinism.score_cluster`)

For each cluster’s member spans (deterministic lane, plus skill-lane clusters
that show LLM-side aggregation):

1. Collect LLM spans with non-empty `output_text` → `n_answer_spans`.
2. **Eligible** iff `n_answer_spans ≥ rung2_min_answer_spans` (default **10**).
3. Lexical signals (volatile tokens masked):

| Signal | Weight |
| --- | --- |
| `template_concentration` | 0.4 |
| `slot_stability` | 0.3 |
| `output_self_similarity` | 0.2 |
| `route_invariance` | 0.1 (dropped + renormalized if N/A) |

4. `determinism_score = blend(...)`; classic evidence bar when eligible and
   `score ≥ rung2_determinism_score` (default **0.8**).
5. Sustained runs to ready: `rung2_sustained_runs` (default **3**).

### Aggregation offload (cost/latency gap)

`detect_llm_aggregation` flags when the **LLM is doing aggregation** (sums,
counts, rollups, rankings from row-level data) that should instead be:

- **precompute_session** — compute at session start and inject into context, or
- **mcp_aggregate** — MCP/SQL returns the already-aggregated result

Not a gap when TOOL/SQL already runs `GROUP BY` / `SUM` / `COUNT` and the LLM
only narrates. Subtype `offload_aggregation`; creation/evidence can also be met
via `aggregation_offload_score` thresholds (0.55 create / 0.70 evidence).

No LLM judge — a low score means “keep the model.”

---

## 7. Candidates & promotion

`ladder_run` upserts candidates keyed by capability + cluster (+ rung), appends
observations, applies `next_status` / `advance_unobserved`.

Promote (`artifacts.promote_candidate` via `POST /candidates/{id}/promote`):

| Rung / subtype | Artifact |
| --- | --- |
| Skill `new_skill` | Draft `skills/<stem>.md` |
| Skill `strengthen_skill` | Suggested prompts/keywords (no silent overwrite) |
| Deterministic | Draft under `capabilities/<id>/deterministic/` (module + notes / tests as implemented) |

Draft files carry `status: draft`. pheonix never edits hand-authored skill bodies
in place for strengthen flows.

---

## 8. Threshold reference

### Settings defaults (`config.Settings`)

| Key | Default |
| --- | --- |
| `cluster_fuzz_threshold` | 90 |
| `skill_match_threshold` | 0.55 |
| `skill_coverage_threshold` | 0.70 |
| `rung1_min_users` | 3 |
| `rung1_min_count` | 15 |
| `rung1_sustained_runs` | 5 |
| `material_change_count_factor` | 1.5 |
| `material_change_users_delta` | 2 |
| `rung2_min_answer_spans` | 10 |
| `rung2_determinism_score` | 0.8 |
| `rung2_sustained_runs` | 3 |
| `run_history_limit` | 20 |

### Capability overrides

`capability.thresholds` may override the `rung1_*` / `rung2_*` keys
(`ladder.resolve_thresholds`). FOBO demo overrides:

```yaml
rung1_min_count: 5
rung1_min_users: 2
rung1_sustained_runs: 2
```

Match/coverage/fuzz thresholds remain settings-global unless extended later.
