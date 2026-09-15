# Skills

How skills work in pheonix: where files live, how they are uploaded and matched,
how Rung 1 promotes gaps, how hashes validate across runs, and how the Decide
**skill lane** differs from the deterministic lane.

---

## 1. What a “skill” is

A skill is a markdown file. Matching fields come from **YAML frontmatter** when
present (`name` required there; `description`, `keywords`, `example_prompts`
optional). If frontmatter is missing, the same fields are derived from Markdown:

- **name** — first `#` heading (slugified), else the file stem
- **description** — first paragraph after the title
- **example_prompts** — bullets under Example / Prompt / Question headings, else
  question-like lines
- **keywords** — bullets under a Keywords heading, else distinctive words

Matching and coverage are **classical ML / pattern matching** by default —
keyword + rapidfuzz + BM25 + TF-IDF, with optional **local MiniLM** assist. No
generative LLM and no remote embedding API.

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
- Must yield a usable skill `name` (YAML frontmatter, `#` heading, or filename);
  otherwise **422** and the write is rolled back (miner would skip empty files).
- Setup UI (`SkillFiles`) is the operator surface for upload before **Run now**.

Unusable files already on disk are skipped with a warning at scan time
(`skills.parse_skill_markdown`).

Results **suggested skill updates** include `current_content`, `proposed_content`,
and `upload_filename` so operators can diff left/right, copy, and download a full
`.md` to re-upload.

### Strengthen ≠ rewrite

Suggested updates for an **existing** capability-local skill are **incremental merges**,
not a blank-file rewrite (`skill_coverage.propose_skill_markdown` → `_merge_skill_md`):

1. Read the current on-disk `.md`.
2. Parse YAML frontmatter when present; for plain Markdown, derive fields then
   prepend frontmatter. Keep every existing key and the **entire markdown body**
   after the closing `---` (or the original body for plain MD).
3. **Append only missing** `example_prompts` / `keywords` (case-insensitive dedupe).
4. Re-serialize frontmatter; concatenate the **unchanged body**.

So procedure text, tables, and hand-written guidance stay intact. Only coverage
examples/keywords grow. If frontmatter cannot be parsed, merge falls back to a
scaffold (catalog-only skills with no local file also scaffold a new uploadable MD).

**Decide → strengthen_skill** goes further: promote writes a **paste-ready YAML
block** only — it does **not** overwrite the hand-authored skill file
(`artifacts.render_strengthen_block`). Operators paste or re-upload deliberately.

**new_skill** is the only path that creates a **new** draft file (`status: draft`).

---

## 3. Matching clusters → skills

After clustering (`cluster.build_clusters`), `skills_mapper.match_clusters`:

- **Classical (default):** stem + FOBO synonym expand, near-dup collapse, then
  score ≈ `0.20 keyword + 0.25 fuzzy + 0.55 (BM25 + word TF-IDF + char n-gram TF-IDF)`.
  Method label: `keyword+fuzzy+bm25+tfidf`.
- **Semantic (optional):** same classical score blended with local MiniLM cosine
  (`0.70 classical + 0.30 semantic`). Method label adds `+semantic`.
  Requires `pip install 'phoenix-scraper[semantic]'`; otherwise falls back to classical.
- Setup UI **Matcher** radio chooses the mode per run (`match_mode` on the job).
  Env default: `PHEONIX_MATCH_MODE=classical`.
- **Match** if best score ≥ `skill_match_threshold` (default **0.55**).
- Else if cluster `count ≥ 2`, emit a **SkillGapProposal** (deduped by proposed name).

No generative LLM and no cloud embedding API in either mode.

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
