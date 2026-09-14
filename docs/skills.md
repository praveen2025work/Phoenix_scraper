# Skills

How skills work in pheonix: where files live, how they are uploaded and matched,
how Rung 1 promotes gaps, how hashes validate across runs, and how the Decide
**skill lane** differs from the deterministic lane.

---

## 1. What a “skill” is

A skill is a markdown file with YAML frontmatter (`name` required; `description`,
`keywords`, `example_prompts` optional). Matching and coverage are **lexical**
(keyword + rapidfuzz) — no embeddings.

Sources, in load order for a capability:

1. **Capability-local** loose files: `capabilities/<id>/skills/*.md`
2. Shared **catalog**: `config/skills_catalog.yaml`
3. Optional trees from `PHEONIX_SKILLS_DIRS` (`**/SKILL.md`)

Capability-local files **override** same-named catalog entries
(`capability_skills.load_capability_skills`). Catalog-first loading would make
local fixes a silent no-op.

FOBO path: `backend/capabilities/fobo/skills/` (created on scaffold; upload via API/UI).

---

## 2. Upload & validation

| API | Behavior |
| --- | --- |
| `GET /capabilities/{id}/skills` | List files with `valid`, `name`, `n_example_prompts` |
| `POST /capabilities/{id}/skills` | Write `{filename, content}`; filename must match `^[a-z][a-z0-9-]{0,63}\.md$` |
| `DELETE /capabilities/{id}/skills/{filename}` | Remove one file |

Validation rules (`api_capabilities`):

- Max ~1 MB per file.
- Must parse YAML frontmatter with at least `name:`; otherwise **422** and the
  write is rolled back (miner would skip invalid files silently).
- Setup UI (`SkillFiles`) is the operator surface for upload before **Run now**.

Malformed files already on disk are skipped with a warning at scan time
(`skills._parse_skill_md`).

---

## 3. Matching clusters → skills

After clustering (`cluster.build_clusters`), `skills_mapper.match_clusters`:

- Score = `0.5 * keyword_ratio + 0.5 * fuzzy_ratio` against each skill.
- Keyword ratio: fraction of skill keywords found in signature + representative.
- Fuzzy ratio: best `token_set_ratio` vs `example_prompts` + description.
- **Match** if best score ≥ `skill_match_threshold` (default **0.55**).
- Else if cluster `count ≥ 2`, emit a **SkillGapProposal** (deduped by proposed name).

Coverage (`skill_coverage.annotate_coverage`): a matched cluster is **covered**
when it resembles that skill’s `example_prompts` (or description) at
`skill_coverage_threshold` (default **0.70**). Below that → “strengthen skill”
gap (skill owns the topic by keyword but lacks an example).

Results API filters uncovered rows to **skill-shaped** text only so tool/SQL
blobs do not dominate the skill-gap column.

---

## 4. Rung 1 — promote to skill

`ladder.detect_rung1` emits signals for clusters that need a skill they do not have:

1. Count ≥ creation floor `max(3, rung1_min_count // 3)`.
2. Representative must be **skill-shaped** (`prompt_shape.is_skill_shaped`) —
   tool/SQL/MCP/file_path/Bedrock blobs are excluded (they belong on Rung 2).
3. If no match (or score &lt; match threshold) → subtype `new_skill`.
4. If matched but coverage below threshold → subtype `strengthen_skill`.
5. Evidence bar: `n_users ≥ rung1_min_users` and `count ≥ rung1_min_count`.

Lifecycle (`ladder_run.update_rung1` + `next_status`): observations accumulate
across runs; consecutive runs meeting the bar for `rung1_sustained_runs` →
`ready`. Humans accept / reject / snooze; promote writes drafts.

**Promotion artifacts** (`artifacts`):

- `new_skill` → draft `capabilities/<id>/skills/<stem>.md` (`status: draft`).
- `strengthen_skill` → paste-ready example_prompts / keywords block (no overwrite
  of hand-authored skill files).

SPA: **Write file** / **Write all skill files** on accepted skill-lane candidates
(`POST /candidates/{id}/promote`).

---

## 5. Hashing & validation across runs

Each capability run records `skill_hashes`: sha256 of every
`capabilities/<id>/skills/*.md` keyed by filename
(`capability_run.capability_skill_file_hashes`).

Uses:

- Prove which skill set produced a version’s gaps.
- **Run compare** (`_skill_hash_diff`): added / removed / changed / unchanged
  filenames between two `run_id`s.
- Operator loop: edit or re-upload the same filename → next run → gaps shrink
  while History shows hash changes.

Hashes are content hashes only; they do not re-validate frontmatter (upload path
already rejects invalid content).

---

## 6. Decide — skill lane

`PromotionQueue` splits live candidates with `effectiveRung(rung, title)`:

| Effective lane | Rule |
| --- | --- |
| **deterministic** | Stored `rung === "deterministic"`, **or** skill rung whose title is deterministic-shaped |
| **skill** | Skill rung (or skill-shaped title) otherwise |

Skill lane columns (finish order):

1. **Decide** — status `ready` (accept / reject / snooze)
2. **Write file** — status `accepted` (materialize draft); bulk write for ≥2 accepted skills
3. **Done** — status `promoted`

Deterministic lane is parallel (Write draft) and must not mix cards into skill
Decide. See [flows.md](./flows.md) and [processing-logic.md](./processing-logic.md).

---

## 7. FOBO defaults

From `capabilities/fobo/capability.yaml`:

```yaml
filter:
  project: pnl-agent          # scrape + in-scope SoT
  workflow_stage: fobo_recon
thresholds:
  rung1_min_count: 5
  rung1_min_users: 2
  rung1_sustained_runs: 2
```

`filter.project` must stay set on PATCH/FilterEditor saves so FOBO does not fall
back to `PHEONIX_PROJECT` and empty the in-scope set. See
[span-scrape-and-filter.md](./span-scrape-and-filter.md).
