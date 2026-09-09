# pheonix backend — Phoenix scraper, prompt miner & promotion ladder

Python service: scrape Arize Phoenix observability data into a local SQLite
store, validate answers and prompts with offline CODE checks, mine the most
frequent prompt patterns, match them to a skills catalog, and run a two-rung
promotion ladder. Ships a Typer CLI (`pheonix`) and a FastAPI service.

> **All commands here run from `backend/`** (or via the root `Makefile`, which
> `cd`s in for you). Paths like `config/`, `certs/`, `data/`, `.env` are relative
> to this directory.

The React UI that consumes this API lives in [`../frontend`](../frontend/README.md);
the root [README](../README.md) covers how the two run together.

## Run it — two commands

```bash
cd backend
pip install -e .          # 1 · deps + the `pheonix` command  (Python 3.11+)
pheonix serve            # 2 · API + job worker on http://localhost:8000  (docs: /docs)
```

That's the whole CLI too: `pheonix demo`, `pheonix scrape`, `pheonix capability …`.

**No editable install?** `pip install -r requirements.txt` then `python run.py`
— `run.py` serves the same thing (`--host`, `--port`, `--reload`) without
installing the package. (The `pheonix` subcommands still need `pip install -e .`.)

**Externally-managed Python** (Homebrew / system): make a venv first —
`python -m venv .venv && source .venv/bin/activate` (`.venv\Scripts\activate` on
Windows).

**Sample data:** the store starts empty — `pheonix demo` seeds synthetic
P&L-agent traffic, analyzes it, writes `data/exports/report.md`.

**Live Phoenix:** `pip install -e '.[live]'` (or `-r requirements-live.txt`),
fill in `backend/.env` (below), then `pheonix scrape`.

## Install

| Requirement | Check |
| --- | --- |
| Python **3.11+** | `python3 --version` (3.9/3.10 use 3.11 syntax and will not work) |
| `uv` *or* plain `pip` | `uv --version` |

**uv (preferred):** `uv sync --all-extras`

**One-shot script (pip only, no uv):**
```bash
./scripts/office_setup.sh          # offline analysis only
./scripts/office_setup.sh --live   # + arize-phoenix-client for live scraping
```
Windows: `scripts\office_setup.bat [--live]`. Finds a Python 3.11+, creates
`.venv`, installs pinned deps, installs the `pheonix` command, runs the demo.

**Manual pip:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or requirements-live.txt for live scraping
pip install -e . --no-deps             # installs `pheonix`
```
With pip, call `pheonix ...` directly (no `uv run` prefix).

### Corporate proxy / internal PyPI mirror

```bash
export UV_INDEX_URL=https://<mirror>/api/pypi/pypi-remote/simple    # uv
export PIP_INDEX_URL=https://<mirror>/api/pypi/pypi-remote/simple   # pip
```
TLS-inspecting proxy: `export SSL_CERT_FILE=/path/corp-ca.pem
REQUESTS_CA_BUNDLE=/path/corp-ca.pem` (uv: also `export UV_NATIVE_TLS=true`).

## Connecting to a live Phoenix instance

Edit `backend/.env` in place (it ships as a placeholder; `.env.example` is only a
template and is never loaded). **After entering a real key:**

```bash
git update-index --skip-worktree backend/.env    # from the repo root
```

so the key can never be committed (the repo is public).

| Variable | Where to get it |
| --- | --- |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix base URL, e.g. `https://phoenix.<domain>` (no trailing `/`, no `/graphql`) |
| `PHOENIX_API_KEY` | Phoenix UI → Settings → API Keys → create a **System** key |
| `PHEONIX_PROJECT` | the Phoenix project your agent traces land in |

Then:
```bash
uv run pheonix scrape      # one incremental watermark cycle
uv run pheonix analyze
uv run pheonix report
```

Scraping is incremental and idempotent — a per-project watermark in
`scrape_state`, a 15-minute overlap re-read for late spans, `span_id` primary key
makes re-inserts no-ops. Uses `Client().spans.get_spans_dataframe(query=SpanQuery(), …)`
(the legacy `px.Client().query_spans` is gone from modern Phoenix). No network
path? Export spans as JSONL elsewhere and `uv run pheonix ingest spans.jsonl`.

### HTTPS: `CERTIFICATE_VERIFY_FAILED`

Python uses its own CA list (`certifi`), not the OS trust store, so an internal
Phoenix cert needs the **corporate root CA** in PEM.

**Always start with `uv run pheonix doctor`** — it prints the endpoint, whether a
CA bundle was picked up, the certs inside it (flagging a self-signed `[ROOT]`),
and a live TLS probe with hints. Re-run after each step; when the probe says
`OK`, TLS is solved.

1. **Host/port** from `PHOENIX_COLLECTOR_ENDPOINT`: `https://phoenix.corp.example`
   → `phoenix.corp.example:443`.
2. **Extract the chain** (run from `backend/` so the file lands right):
   ```bash
   openssl s_client -showcerts -connect phoenix.corp.example:443 </dev/null 2>/dev/null \
     | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/' > certs/phoenix-ca.pem
   ```
3. **Check the root is present** (subject == issuer):
   ```bash
   openssl crl2pkcs7 -nocrl -certfile certs/phoenix-ca.pem | openssl pkcs7 -print_certs -noout
   ```
4. `uv run pheonix doctor` → `CA bundle:` shows `certs/phoenix-ca.pem`,
   `connection probe: OK`.
5. `uv run pheonix scrape`.

**Other ways to get the root CA** (put the PEM at `certs/phoenix-ca.pem`, then
re-run doctor): ask IT for the "corporate root CA in PEM/Base64"; export the
**top-most** cert from the browser padlock → Details → Export (Base64); Windows
`Cert:\LocalMachine\Root` via PowerShell; macOS Keychain → System → Export as
`.pem`. Exporting a lower entry gives the intermediate — verification then fails
with *"unable to get issuer certificate"*; append the root to the bundle.

Different location: `PHEONIX_CA_BUNDLE=/path/ca.pem` in `.env` (`certs/*.pem` is
gitignored). Last resort on a trusted network: `PHEONIX_TLS_VERIFY=false` (logs a
warning, never silent).

### Serving on a shared machine

Scraped prompts can hold client/P&L data — `data/` is gitignored, keep it off
shared drives. The server binds `127.0.0.1`; to expose it you **must** set a key:

```bash
export PHEONIX_API_KEY=<long-random-string>
uv run pheonix serve --host 0.0.0.0 --port 8000
# clients: curl -H "X-API-Key: ..." http://<host>:8000/prompts/frequent?fmt=csv
```
Without `PHEONIX_API_KEY`, `serve` refuses non-loopback by design.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `SyntaxError` on install | Python < 3.11 — install 3.11+ or let `uv sync` fetch it |
| SSL errors during `pip install` | corporate TLS inspection — set `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` |
| `CERTIFICATE_VERIFY_FAILED` from `scrape` | `uv run pheonix doctor`, drop the root CA at `certs/phoenix-ca.pem` |
| `unable to get issuer certificate` | bundle has only the intermediate — append the root; doctor must show `[ROOT (self-signed)]` |
| `Phoenix is not available` | endpoint unset/wrong (edited `.env.example` by mistake?) or `arize-phoenix-client` missing (`uv sync --extra live`) |
| `401` from Phoenix | key expired/revoked — issue a fresh System key |
| Scrape succeeds, 0 spans | wrong `PHEONIX_PROJECT`, or the watermark window — wait a cycle |
| Scrape read-timeout after 3 retries | slow first full-history scan — raise `PHEONIX_HTTP_TIMEOUT`, lower `PHEONIX_SCRAPE_LIMIT`, or `--since 2026-08-01T00:00:00` |
| Prompts cluster poorly | tune `PHEONIX_` cluster/match thresholds (see `src/phoenix_scraper/config.py`) |

## How the mining works

```
spans ─▶ normalize ─▶ cluster ─▶ match vs skills catalog ─▶ matches + gap proposals
        (mask <num>,   (group by    (keyword + fuzzy score;
         <date>, <ccy>, signature,   unmatched frequent clusters
         <book>, <id>)  fuzzy-merge) become proposed skills)
```

Normalization makes frequency honest: *"FX recon break of 100k on EURUSD_LDN"* and
*"fx recon break of 250k on USDJPY_NY"* share one signature. Clusters seen across
multiple asset classes never become asset-class skills — they slot at capability
or global level.

## How validation works

Phoenix judges an agent with **span annotations** (`label` + `score` +
`explanation`), tagged `HUMAN` / `LLM` / `CODE`. This tool speaks all three:

```
stored spans ─▶ code checks ───────▶ span_evaluations ◀─── Phoenix annotations
                (CODE, offline)      (one table)          (HUMAN + LLM, pulled)
                                          ├─▶ quality panels / API / CSV
                                          └─▶ pushed back to Phoenix (opt-in)
```

Code checks run **offline over every span** — no model calls, no sampling. Scores
are 0-1, higher is better, a check fails below 0.5, and every failure states its
evidence.

| Check | Judges | Fails when |
| --- | --- | --- |
| `output_empty` | output | a user turn produced no answer |
| `output_refusal` | output | the answer *opens* with a refusal |
| `output_truncated` | output | `finish_reason=max_tokens` / no terminal punctuation / unclosed brackets |
| `output_repetition` | output | degenerate looping (low distinct-word ratio, 4×+ phrase repeat) |
| `output_format_valid` | output | JSON asked for / attempted and does not parse |
| `answer_relevance` | output | the answer shares almost none of the question's vocabulary |
| `answer_groundedness` | output | states figures absent from the question **and** every tool result |
| `span_status` | span | status is `ERROR` |
| `latency_outlier` | span | latency exceeds the outlier cut for that span kind |
| `prompt_injection` | prompt | instruction-override / prompt-extraction / jailbreak patterns |
| `prompt_pii` | prompt | email / phone / IBAN / SSN / account-number patterns |
| `prompt_clarity` | prompt | a short ask whose object is only a pronoun |
| `prompt_length` | prompt | length exceeds the corpus outlier cut |

Checks that don't apply emit nothing (not a pass). Thresholds via `PHEONIX_EVAL_*`
in `.env` — see `src/phoenix_scraper/config.py`.

**Deliberate limits.** `answer_relevance` is lexical — its bar is low, it only
catches answers sharing *nothing* with the question. `answer_groundedness`
abstains when any tool ran in the trace. Neither replaces an LLM judge for
semantic correctness; the next step is `phoenix.evals` on a sample, pulled back in
via `--pull-annotations`.

```bash
uv run pheonix evaluate                      # validate stored spans, print the scoreboard
uv run pheonix evaluate --user analyst-priya # scoped like every other filter
uv run pheonix evaluate --pull-annotations   # + fetch HUMAN/LLM annotations from Phoenix
uv run pheonix evaluate --push               # write failing CODE checks back to Phoenix
```

`analyze` / `demo` run the checks by default (`PHEONIX_EVALUATE_ON_ANALYZE=false`
to skip). `--push` sends **failing** local checks as `annotator_kind=CODE`,
`identifier=pheonix` — upserts, never overwrites a human's annotation.
`--push-all` mirrors passing checks too. Pulled rows are keyed `source='phoenix'`
and survive local re-analysis.

## Skill coverage — what your skill files miss

Matching says *which skill owns this question*. Coverage says *does the skill file
actually demonstrate it* — a cluster can match on keywords while none of the
skill's `example_prompts` shows the phrasing users type. Measured **per skill
file** (the thing someone edits).

```bash
uv run pheonix coverage           # per-file coverage + the lines to add
uv run pheonix coverage --write   # ... to data/exports/skill_updates.md
```

```
skill                     file                  asks  shown  gap  cover  top gap
signoff-commentary-draft  skills_catalog.yaml     34     28    6   82%  Write the narrative summary for credit sign-off
fobo-break-triage         skills_catalog.yaml      6      0    6    0%  Are there recon breaks still unmatched on the credit book?
```

`cover` is the share of **asks** (not clusters) routed to that skill that its
examples already demonstrate. Suggested keywords come from the **normalized
signature** so volatile tokens never leak; words already in the skill's
name/description/keywords (and their plurals) are skipped.

Every `analyze` snapshots its clusters so consecutive runs diff (`new` / `growing`
/ `stable` / `shrinking` / `gone`; >20% move to count). History bounded by
`PHEONIX_RUN_HISTORY_LIMIT` (default 20).

## Skills catalog inputs

Three sources, merged (catalog wins on name collisions):

1. `config/skills_catalog.yaml` — explicit entries
   (level / asset_class / capability / keywords / example_prompts).
2. `PHEONIX_SKILLS_DIRS` — comma-separated dirs scanned recursively for `SKILL.md`
   with YAML frontmatter. `example_prompts` in frontmatter is what coverage
   measures against — a file that declares none shows 0%.
3. **The capability's own `capabilities/<id>/skills/*.md`** — loose markdown files,
   read fresh on every run, and they **override a catalog entry of the same name
   for that capability**. Add them by dropping a file in that directory, by
   `pheonix promote`-ing a ready Rung-1 candidate, or from the SPA's **Skills**
   tab (upload or paste — `POST /capabilities/<id>/skills`). A file without
   usable YAML frontmatter is rejected by the API and skipped by a run, so the
   upload tells you instead of silently doing nothing.

### Closing a gap

The loop, end to end:

```bash
pheonix run --capability fobo
# GET /skills/coverage?capability=fobo   ->  fobo-break-triage  asks=6  covered=0%
# GET /skills/updates?capability=fobo    ->  the paste-ready example_prompts block
#   ... drop that block into capabilities/fobo/skills/fobo-break-triage.md
#       (or upload it from the SPA's Skills tab)
pheonix run --capability fobo --replace-today
# GET /skills/coverage?capability=fobo   ->  fobo-break-triage  asks=6  covered=100%
```

`?capability=<id>` on `/skills/{coverage,uncovered,updates}` scopes the answer to
that capability's latest run **and its own skill set** — without it you get the
global `pheonix analyze` picture, which never sees a capability's `skills/`
directory. (`/skills/gaps` — proposed *new* skills — is still global only.)

Replace the sample `config/skills_catalog.yaml` with your catalog and update
`config/pricing.yaml` with your Bedrock token rates so cost numbers are real.

## Capabilities

A **capability** is a named analysis scope — a saved span filter + an owned
directory of skill files — for one workflow (FOBO recon, PLEX, …).
`capabilities/<id>/capability.yaml` on disk is the source of truth; the
`capabilities` table mirrors it (`window_days > 0` and `status ∈ {active,paused}`
are enforced).

```bash
uv run pheonix capability new fobo --name "FOBO reconciliation" \
    --project pnl-agent --stage fobo_recon --window-days 30
uv run pheonix capability list
uv run pheonix capability show fobo
uv run pheonix capability sync            # re-read every capability.yaml into the DB
```

`new` scaffolds `capabilities/fobo/` with `capability.yaml`, `skills/`,
`deterministic/`. `PHEONIX_CAPABILITIES_DIR` relocates the root.

## Daily runs

`pheonix run` scrapes the capability's Phoenix project (once, even for `--all`),
restricts to its filter + `[from, to]` window (default: the last `window_days`),
runs the mining pipeline **and the CODE validators** over just those spans, and
records the run so consecutive runs diff.

```bash
uv run pheonix run --capability fobo
uv run pheonix run --capability fobo --days 90                 # window = last 90 days
uv run pheonix run --capability fobo --from 2026-08-01 --to 2026-09-01
uv run pheonix run --all --replace-today          # re-run without adding a history point
uv run pheonix capability runs fobo               # recorded runs, newest first
```

`--days` / `--from` / `--to` override the capability's default `window_days` for
that run; in the SPA, the "days" field next to **Run now** does the same. The
window only selects from spans **already in the store** — to analyse further
back than you've scraped, backfill first:

```bash
uv run pheonix scrape --reset --since 2026-05-01T00:00:00   # forget the watermark, re-pull
```

Schedule `pheonix run --all` with cron (no built-in daemon). Offline / Phoenix
unreachable → the run still executes against stored spans, marked `partial`.

### Background runs (API)

The API runs a capability without blocking the request:

```
POST /capabilities/<id>/jobs {from?,to?,replace_today?}  → 202 {job_id, state:"queued"}
GET  /capabilities/<id>/jobs/<job_id>                    → {state, run_id, error, ...}
GET  /capabilities/<id>/jobs                             → history
```

A single worker thread inside the API process drains the queue one run at a time
(`src/phoenix_scraper/jobs.py`). It starts with `pheonix serve` / the uvicorn
factory (`create_app(settings, run_jobs=True)`); a restart marks any interrupted
job `error`. `pheonix capability jobs <id>` lists the history. The `pheonix run`
CLI stays synchronous. The SPA's "Run now" uses this flow.

## The promotion ladder

**Rung 1 — prompt → skill.** Each run updates candidates: an in-scope cluster
recurring across users that has no skill (`new_skill`) or matched one that
doesn't demonstrate it (`strengthen_skill`). `ready` after `rung1_sustained_runs`
(default 5) consecutive runs meeting `rung1_min_users` AND `rung1_min_count`.

```bash
uv run pheonix candidates fobo                    # active board
uv run pheonix candidates fobo --all              # + rejected / snoozed / stale
uv run pheonix decide fobo:s:abc123 --action reject --actor you --note "covered by X"
uv run pheonix promote fobo:s:abc123 --actor you  # writes capabilities/fobo/skills/<name>.md
uv run pheonix promote fobo:s:abc123 --dry-run
```

`promote` writes a **draft** `skills/<name>.md` (`status: draft`) for `new_skill`,
or prints the paste-ready block for `strengthen_skill`. pheonix never edits a
hand-authored file. A rejected candidate reopens only on a **material change** in
volume.

**Rung 2 — make it deterministic.** The same run scores every eligible cluster
(`rung2_min_answer_spans`, default 10) on four lexical signals — template
concentration, route invariance, output self-similarity, slot stability — blended
into a `determinism_score`. At `rung2_determinism_score` (0.8) over
`rung2_sustained_runs` (3) runs the `<cap>:d:<cluster>` candidate is `ready`;
`promote` writes a `deterministic/<name>.py` stub (snake_case module) + a red,
importable `test_<name>.py` parametrized over the **real observed
`(prompt, answer)` pairs** + a `<name>.md` write-up. A low score is a real "keep
the model" answer.

```bash
uv run pheonix candidates fobo --rung deterministic
uv run pheonix candidate fobo:d:abc123           # signals, templates, trend, decisions
```

The analytics live in the [SPA](../frontend/README.md)'s Analytics tab
(`/c/<id>/analytics`), scoped per capability. Every panel is also a plain
endpoint (`/overview`, `/insights/*`, `/quality/*`, `/skills/*`), filterable,
`fmt=csv`-downloadable, and takes `?capability=<id>`.

## CLI

```
pheonix demo|seed|scrape|ingest|analyze|evaluate|coverage|report|serve|serve-ui|doctor
pheonix run  (--capability <id> | --all) [--from --to --replace-today]
pheonix capability  new | list | show | sync | runs | jobs
pheonix candidates <id> [--rung --status --all]   ·   pheonix candidate <cid>
pheonix decide <cid> --action accept|reject|snooze|reopen --actor --note [--snooze-runs]
pheonix promote <cid> [--accept] [--dry-run]
pheonix export --what spans|clusters|matches|proposals|sessions|evaluations|coverage|uncovered
               --fmt csv|json|parquet [filter options]
```

## API

`create_app(settings, *, run_jobs=False)` builds the app; `create_app_default()`
(the uvicorn factory) and `pheonix serve` pass `run_jobs=True`. `GET /` is a JSON
notice; `GET /health` is unauthenticated. Every list route accepts filter params
and `fmt=json|csv`; every analytics route takes `?capability=<id>`.
`PHEONIX_CORS_ORIGINS` (comma-separated) allows a cross-origin SPA.

| Route group | |
| --- | --- |
| `GET /quality/{overview,checks,by,failures,by-prompt,evaluations,catalog}` | validation rollups |
| `POST /annotations/{pull,push}` | round-trip HUMAN/LLM ↔ CODE with Phoenix |
| `GET /skills/{coverage,uncovered,updates,updates.md,matches,gaps}` | skill-file gaps + proposals |
| `GET /overview`, `/insights/*`, `/sessions`, `/costs/summary`, `/spans`, `/prompts/frequent` | analytics |
| `GET /runs`, `/runs/delta` · `POST /scrape/run`, `/analyze/run`, `/report/run`, `/demo/seed` | global pipeline |
| `GET/POST /capabilities` · `GET/PATCH/DELETE /capabilities/{id}` (`?purge=`) · `POST /capabilities/{id}/sync` | capability CRUD |
| `POST /capabilities/{id}/runs` (sync) · `GET /capabilities/{id}/runs[/{run_id}]` · `.../runs/delta` | scoped runs |
| `POST/GET /capabilities/{id}/jobs` · `GET /capabilities/{id}/jobs/{job_id}` | async runs (job worker) |
| `GET/POST /capabilities/{id}/skills` · `DELETE /capabilities/{id}/skills/{filename}` | the capability's own `skills/*.md` — upload, list, remove |
| `GET /capabilities/{id}/candidates` · `GET /candidates/{cid}` | ladder board / detail |
| `POST /candidates/{cid}/decision` (409 on invalid) · `.../promote?accept=` · `.../artifact/preview` | ladder actions |

Full frozen interface: [`CONTRACTS.md`](CONTRACTS.md).

## Layout

```
config/           skills_catalog.yaml, pricing.yaml
capabilities/     one dir per capability: capability.yaml + skills/ + deterministic/  (runtime)
data/             SQLite store + exports  (gitignored, runtime)
src/phoenix_scraper/
  phoenix_client    the ONLY module that talks to Phoenix (auth, retries, TLS)
  scraper           OpenInference attr flattening + watermark scrape + jsonl ingest
  normalize/cluster prompt signatures (mask_volatile) + frequency clustering
  skills/taxonomy/skills_mapper   catalog loading, level inference, matching + proposals
  evaluations       the CODE annotator — offline output & prompt validators
  annotations       pull HUMAN/LLM annotations, push CODE ones back
  skill_coverage    per-file blind spots + run-over-run diffs
  insights*         analytics: traces, users, LLM behaviour, quality rollups
  costs/sessions    token→cost from pricing.yaml, session derivation
  storage           SQLite store (context manager; WAL + busy_timeout)
  capability/capability_run   the capability entity + scoped per-capability runs
  ladder/ladder_run/determinism   Rung 1 (prompt→skill) + Rung 2 (lexical determinism)
  artifacts         draft skills/<name>.md + deterministic/<name>.{py,md} writers
  jobs              background JobWorker for async capability runs
  pipeline/cli/api  orchestration, Typer CLI, FastAPI service
  api_capabilities/api_ladder   capability CRUD / run / job / ladder HTTP routes
tests/            797 tests — `uv run pytest`  (or `make test` from the repo root)
scripts/          gen_openapi.py, office_setup.{sh,bat}
```

## Testing

```bash
uv run pytest -q                    # or: make test  (from the repo root, with coverage)
uv run ruff check src tests         # or: make lint
```

Exit code 0 is the pass signal — the summary line is suppressed by
`addopts = -q`.

## POC limitations (deliberate)

- Lexical clustering (normalize + rapidfuzz), not embeddings.
- Code-only validation — no bundled LLM judge.
- Illustrative pricing in `config/pricing.yaml`.
- Single-writer SQLite (WAL + `busy_timeout`); the job worker runs one at a time.
- Live stage/asset-class attribution relies on span `metadata.workflow_stage` /
  `metadata.asset_class` (fixtures set them).
