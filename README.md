# pheonix — Phoenix Prompt Miner (POC)

Scrapes **Arize Phoenix** observability data (traces, spans, sessions, prompts, token
usage/cost), **validates what the LLM answered and what users asked**, identifies the
**most frequently asked user prompts**, matches them against your **existing skills
catalog**, and proposes **new skills** slotted at the right level:

- **global** — cross-desk utility (glossary, export help, …)
- **asset_class** — FX / rates / equities / credit / commodities
- **capability** — workflow stage (fobo_recon, plex, flash_vs_formal, adjustments, commentary_signoff, …)

POC constraints honored: everything runs against a **local SQLite file + filesystem
exports** — no external services. Live Phoenix scraping is optional and env-gated.

## Quick start (offline — works right now)

```bash
make setup    # uv sync (creates .venv, Python 3.11+)
make demo     # seed synthetic P&L-agent traffic -> analyze -> report
make api      # FastAPI on http://localhost:8100 (interactive docs at /docs)
```

`make demo` prints the top prompts table and writes `data/exports/report.md` — top
prompts with frequency/session/user/cost evidence, matched skills, and proposed new
skills grouped by level.

## Running on your office machine

### 1. Prerequisites

| Requirement | Check | Notes |
| --- | --- | --- |
| Python **3.11+** | `python3 --version` | 3.9/3.10 will not work (uses 3.11 syntax) |
| `uv` *or* plain `pip` | `uv --version` | uv preferred; pip path below if uv isn't approved |
| Network to Phoenix | `curl -s $PHOENIX_COLLECTOR_ENDPOINT/healthz` | only needed for live scraping — the demo is fully offline |

Get the code onto the machine via your internal git remote, or copy the folder as a
zip (exclude `.venv/` and `data/`).

### 2. Corporate proxy / internal PyPI mirror

If your machine routes pip through an internal mirror (Artifactory/Nexus):

```bash
export UV_INDEX_URL=https://<your-mirror>/api/pypi/pypi-remote/simple   # uv
export PIP_INDEX_URL=https://<your-mirror>/api/pypi/pypi-remote/simple  # pip
```

If you hit SSL errors from TLS-inspecting proxies, point Python at the corporate CA
bundle: `export SSL_CERT_FILE=/path/to/corp-ca.pem REQUESTS_CA_BUNDLE=/path/to/corp-ca.pem`
(for uv add `export UV_NATIVE_TLS=true`).

### 3. Install

**Option A — one-shot script (pip only, no uv needed):**

```bash
./scripts/office_setup.sh            # offline analysis only
./scripts/office_setup.sh --live     # + Phoenix client for live scraping
```

Windows: `scripts\office_setup.bat [--live]`. Either variant finds a Python 3.11+,
creates `.venv`, installs pinned deps, installs the `pheonix` CLI, and runs the
offline demo to verify everything works.

**Option B — uv (if approved on your machine):**

```bash
make setup                 # = uv sync --all-extras (creates .venv, fetches Python 3.11 if needed)
```

**Option C — manual pip:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # pinned runtime deps
                                         # (use requirements-live.txt instead for live scraping)
pip install -e . --no-deps               # installs the `pheonix` command
```

With pip, skip the Makefile (it shells out to uv) and call `pheonix ...` directly —
same commands, no `uv run` prefix.

### 4. Verify offline before touching Phoenix

```bash
pheonix demo        # or: make demo
```

This must print a top-prompts table and write `data/exports/report.md`. If it does,
the whole pipeline works; everything after this is just pointing it at real data.

### 5. Connect to your Phoenix instance

The repo ships a placeholder `.env` — edit it in place (no need to copy
`.env.example`). **After entering a real API key, run:**

```bash
git update-index --skip-worktree .env
```

This tells git to ignore your local edits so the key can never be committed or
pushed (the repo is public). Undo later with `--no-skip-worktree` if you ever
need to pull upstream changes to the file.

Fill in:

| Variable | Where to get it |
| --- | --- |
| `PHOENIX_COLLECTOR_ENDPOINT` | your Phoenix base URL, e.g. `https://phoenix.<internal-domain>` (no trailing `/`) |
| `PHOENIX_API_KEY` | Phoenix UI → **Settings → API Keys** → create a **System** key (survives user changes; ask a Phoenix admin if the menu is missing) |
| `PHEONIX_PROJECT` | the Phoenix project name your agent traces land in (visible in the Phoenix UI project list) |

The app reads a file named exactly `.env` from the directory you run it in —
`.env.example` is only a template and is never loaded. If `pheonix scrape` says
*"Phoenix is not available: set PHOENIX_COLLECTOR_ENDPOINT"* after you filled in
values, check you edited `.env` (not `.env.example`) and that you are running
from the project root.

Then:

```bash
pheonix scrape      # one incremental watermark cycle
pheonix analyze
pheonix report
```

#### HTTPS endpoint: `SSL: CERTIFICATE_VERIFY_FAILED`

Your browser trusts the internal Phoenix cert via the OS trust store, but Python
uses its own bundled CA list (`certifi`), which doesn't include your corporate CA.
The fix is to give the app your corporate **root CA** certificate.

**Always start with `pheonix doctor`.** It prints exactly what the app sees —
endpoint, whether a CA bundle was picked up, the certificates inside it (up to
the first 10, with whether a self-signed **root** is present), and a live TLS
probe against your endpoint with hints when it fails. Re-run it after every
step below; when the probe says `OK`, the TLS problem is solved and
`pheonix scrape` will no longer fail with `CERTIFICATE_VERIFY_FAILED`
(authentication or project-name issues are separate — see Troubleshooting).

##### Extract and install the certificate, one step at a time

1. **Find your host and port** from `PHOENIX_COLLECTOR_ENDPOINT`:
   `https://phoenix.corp.example` → host `phoenix.corp.example`, port `443`
   (use the explicit port if the URL has one, e.g. `https://host:8443`).

2. **Extract the certificate chain the server presents** (run from the project
   root so the file lands in the right place):

   ```bash
   openssl s_client -showcerts -connect phoenix.corp.example:443 </dev/null 2>/dev/null \
     | awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/' > certs/phoenix-ca.pem
   ```

   Expected: `certs/phoenix-ca.pem` containing one or more
   `-----BEGIN CERTIFICATE-----` blocks. If your original error said
   *"self-signed certificate in certificate chain"*, the server **does** send its
   root, so this command captures it. (No `openssl` on Windows? Git Bash ships
   one — or use the browser/PowerShell exports below.)

3. **Check the root is in the file:**

   ```bash
   openssl crl2pkcs7 -nocrl -certfile certs/phoenix-ca.pem | openssl pkcs7 -print_certs -noout
   ```

   Expected: at least one entry whose `subject` and `issuer` are **identical** —
   that's the root. `pheonix doctor` shows the same thing as `[ROOT (self-signed)]`
   and warns when it's missing.

4. **Verify pickup and connectivity:**

   ```bash
   pheonix doctor
   ```

   Expected: the `CA bundle:` line shows `certs/phoenix-ca.pem` with your certs
   listed, and `connection probe: OK`. If the bundle line says `none`, you're
   not running from the directory containing `certs/`.

5. **Run the scraper:**

   ```bash
   pheonix scrape
   ```

**Other ways to obtain the certificate** (if the `openssl` extraction isn't
possible — however you get the file, put it at `certs/phoenix-ca.pem` and go
back to step 4). You want the corporate **root CA** — the top of the chain —
in **PEM** format (text starting with `-----BEGIN CERTIFICATE-----`;
`.pem`/`.crt`/`.cer` extensions are all fine, and concatenating several PEM
blocks into one file works):

- **Ask IT** for the "corporate root CA certificate in PEM / Base64 format".
- **Export from your browser** (works because the Phoenix UI already loads):
  open the Phoenix URL → click the padlock → *Connection is secure* →
  *Certificate is valid* → **Details** tab → select the **top-most** entry in
  the certificate hierarchy (the root) → **Export** → save as
  *Base64-encoded ASCII / single certificate*. Exporting a lower entry gives
  you the intermediate — verification then fails with *"unable to get issuer
  certificate"*. If that happens, export the top entry too and **append** it
  to the bundle: `type root.cer >> certs\phoenix-ca.pem` (Windows) or
  `cat root.pem >> certs/phoenix-ca.pem` (macOS/Linux).
- **Windows certificate store** (corp root is usually deployed there) — in
  PowerShell from the project root, replace `<YourCompany>` with a word from
  your company's CA name:

  ```powershell
  $cert = (Get-ChildItem Cert:\LocalMachine\Root | Where-Object Subject -match "<YourCompany>")[0]
  "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($cert.RawData,'InsertLineBreaks') + "`n-----END CERTIFICATE-----" |
    Set-Content certs\phoenix-ca.pem
  ```

  (Browse candidates first with `certmgr.msc` → *Trusted Root Certification
  Authorities* if you're not sure of the name.)
- **macOS Keychain**: Keychain Access → *System* keychain → find the corporate
  CA → File → Export Items… → format *Privacy Enhanced Mail (.pem)*.

**Different location or name?** Set `PHEONIX_CA_BUNDLE=/path/to/ca.pem` in
`.env`. The file stays local either way — `certs/*.pem` is gitignored. A shell
`SSL_CERT_FILE` export also works (shell only — in `.env` only
`PHEONIX_CA_BUNDLE` is read).

**Still failing?** Re-run `pheonix doctor` and read its hints. If the bundle
shows no `[ROOT (self-signed)]` entry, ask IT for the actual root CA PEM. As a
last resort **on a trusted internal network only**, set
`PHEONIX_TLS_VERIFY=false` in `.env` to disable certificate verification for
the Phoenix connection (the scraper logs a warning so it is never silent).

#### After TLS works: endpoint and project sanity checks

- `PHOENIX_COLLECTOR_ENDPOINT` must be the **base URL only** — no `/graphql`,
  no `/projects/...`. Those are the web UI's routes; the scraper calls the REST
  API under `/v1/` on the base URL.
- Quick API check from your browser (it already trusts the cert): open
  `https://<phoenix-host>/v1/projects`. JSON with your projects means the API
  works — copy the exact `name` (or `id`) into `PHEONIX_PROJECT`. A browser URL
  like `/projects/UHJvamVjdDox/spans` is the UI page; the token in the middle is
  the project **id**, which also works as `PHEONIX_PROJECT`.

No network path to Phoenix? Export spans from the Phoenix UI/API as JSONL on a
machine that has access, transfer the file, and run `pheonix ingest spans.jsonl`.

### 6. Point it at your real skills and pricing

- Replace the sample entries in `config/skills_catalog.yaml` with your actual catalog, **and/or**
- set `PHEONIX_SKILLS_DIRS=/path/to/skills,/other/path` to scan existing `SKILL.md` trees.
- Update `config/pricing.yaml` with your negotiated Bedrock token rates so cost
  numbers are real, not illustrative.

### 7. Serving the API on a shared machine

Scraped prompts can contain client and P&L data — treat `data/` as confidential
(it is gitignored; it must stay off shared drives). The server binds `127.0.0.1`
by default; to let colleagues reach it you **must** set an inbound key first:

```bash
export PHEONIX_API_KEY=<generate-a-long-random-string>
pheonix serve --host 0.0.0.0 --port 8100
# clients: curl -H "X-API-Key: ..." http://<host>:8100/prompts/frequent?fmt=csv
```

Without `PHEONIX_API_KEY`, `serve` refuses non-loopback hosts by design.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `SyntaxError` on install/run | Python is < 3.11 — install 3.11+ or let `uv sync` fetch it |
| SSL errors during `pip install` | corporate TLS inspection — set `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` (step 2) |
| `CERTIFICATE_VERIFY_FAILED` from `pheonix scrape` | run `pheonix doctor`, then drop the corporate root CA at `certs/phoenix-ca.pem` (walkthrough in the "HTTPS endpoint" section) |
| `certificate verify failed: unable to get issuer certificate` | your bundle has only the **intermediate** CA — append the **root** (top entry in the browser cert hierarchy) to `certs/phoenix-ca.pem`; `pheonix doctor` must show a `[ROOT (self-signed)]` entry |
| `Phoenix is not available` from `pheonix scrape` | endpoint unset/wrong (did you edit `.env.example` instead of `.env`?), or `arize-phoenix-client` not installed (`uv sync --extra live`, or `pip install -r requirements-live.txt`) |
| `401` from Phoenix | key expired/revoked — issue a fresh System key in Phoenix Settings |
| Scrape succeeds but 0 spans | wrong `PHEONIX_PROJECT` name, or the time window: the watermark starts from your first run — wait a cycle or check the project has recent traces |
| `pheonix scrape` retries 3× then fails with **read timeout** | TLS/network are fine — the server is slow answering a full-history first scan. Raise `PHEONIX_HTTP_TIMEOUT` (e.g. 180) and/or lower `PHEONIX_SCRAPE_LIMIT` (e.g. 1000) in `.env`, or bound the first pull: `pheonix scrape --since 2026-08-01T00:00:00`. Later runs are incremental and fast |
| Prompts cluster poorly on real data | tune `PHEONIX_` cluster/match thresholds in `.env` (see `src/phoenix_scraper/config.py` defaults) |

## How live scraping behaves

Scraping is **incremental and idempotent**: a watermark per project is kept in the
`scrape_state` table, each cycle re-reads a 15-minute overlap window to catch
late-arriving spans, and the `span_id` primary key makes re-inserts no-ops.
Uses the current client API (`Client().spans.get_spans_dataframe(query=SpanQuery(), ...)`);
the legacy `px.Client().query_spans` API is gone from modern Phoenix.

You can also ingest a Phoenix span export offline: `uv run pheonix ingest <file.jsonl>`.

## How the mining works

```
spans ──> normalize ──> cluster ──> match vs skills catalog ──> matches + gap proposals
          (mask <num>, <date>,      (group by signature,        (keyword + fuzzy score;
           <ccy>, <book>, <desk>,    fuzzy-merge near-dupes)     unmatched frequent clusters
           <id>)                                                 become proposed skills)
```

Normalization is what makes frequency counting honest: *"Why is there an FX recon break
of 100k on EURUSD_LDN?"* and *"why is there an fx recon break of 250k on USDJPY_NY?"*
share one signature, so they count as one prompt pattern. Clusters observed across
multiple asset classes are never proposed as asset-class skills — they slot at
capability (or global) level.

## How validation works

Phoenix judges an agent with **span annotations**: named verdicts attached to a span,
each carrying a `label`, a `score` and an `explanation`, tagged with who made them —
`HUMAN` (an analyst clicking thumbs up/down in the Phoenix UI), `LLM` (an
`phoenix.evals` llm-as-judge run), or `CODE` (a deterministic programmatic check).
This tool speaks all three:

```
stored spans ──> code checks ─────────> span_evaluations <──── Phoenix annotations
                 (CODE, offline)         (one table)           (HUMAN + LLM, pulled)
                                              │
                                              ├──> quality panels / API / CSV
                                              └──> pushed back to Phoenix (opt-in)
```

**Code checks run offline over every span** — no model calls, no network, no sampling.
That is the split production teams use: cheap deterministic checks on 100% of traffic,
expensive semantic judges on a sample. Scores are 0-1, **higher is better**, and a check
fails below 0.5. Every failure states its evidence (the matched phrase, the ungrounded
figures, the unaddressed terms), because a heuristic you cannot audit is noise.

| Check | Judges | Fails when |
| --- | --- | --- |
| `output_empty` | output | a user turn produced no answer |
| `output_refusal` | output | the answer *opens* with a refusal ("I cannot…", "As an AI…") |
| `output_truncated` | output | `finish_reason=max_tokens`, no terminal punctuation, or unclosed brackets |
| `output_repetition` | output | degenerate looping — low distinct-word ratio or a phrase repeating 4×+ |
| `output_format_valid` | output | JSON was asked for or attempted and does not parse |
| `answer_relevance` | output | the answer shares almost none of the question's vocabulary |
| `answer_groundedness` | output | the answer states figures absent from the question **and** from every tool result in the trace |
| `span_status` | span | the span status is `ERROR` |
| `latency_outlier` | span | latency exceeds the outlier cut **for that span kind** |
| `prompt_injection` | prompt | instruction-override / system-prompt-extraction / jailbreak patterns |
| `prompt_pii` | prompt | email, phone, IBAN, SSN or account-number patterns in the prompt |
| `prompt_clarity` | prompt | a short ask whose object is only a pronoun ("fix it again") |
| `prompt_length` | prompt | prompt length exceeds the corpus outlier cut |

Checks that do not apply to a span emit nothing rather than a pass, so a narrow check
(JSON validity) never dilutes the headline numbers. Thresholds are tunable via
`PHEONIX_EVAL_*` in `.env` — see `src/phoenix_scraper/config.py`.

**Deliberate limits.** `answer_relevance` is lexical: it cannot tell that "PLEX" and
"attribution" mean the same thing, so its bar is set low and it only reliably catches
answers sharing *nothing* with the question. `answer_groundedness` abstains whenever a
tool ran in the trace, since a tool may legitimately have supplied the figure. Neither
replaces an LLM judge for semantic correctness — they catch the failures a judge is too
expensive to look for on every span.

```bash
pheonix evaluate                      # validate stored spans, print the scoreboard
pheonix evaluate --user analyst-priya # ... scoped, like every other filter
pheonix evaluate --pull-annotations   # also fetch HUMAN/LLM annotations from Phoenix
pheonix evaluate --push               # write failing CODE checks back to Phoenix
```

`pheonix analyze` (and `demo`) runs the checks by default; set
`PHEONIX_EVALUATE_ON_ANALYZE=false` to skip them.

### Round-tripping with Phoenix

`--pull-annotations` calls `GET /v1/projects/{project}/span_annotations` (via
`Client().spans.get_span_annotations`) for the spans already scraped, so a thumbs-down
an analyst left in the Phoenix UI and a hallucination score an `phoenix.evals` run
logged both show up in the panels beside the local checks. Pulled rows are keyed by
`source='phoenix'` and are never dropped by a local re-analysis.

`--push` sends the **failing** local checks to `POST /v1/span_annotations` as
`annotator_kind=CODE` with `identifier=pheonix`, so they appear against the spans in
Phoenix for everyone, upsert on repeat runs, and can never overwrite a human's
annotation of the same name. Push is opt-in — it writes to a shared system. Add
`--push-all` to mirror passing checks too.

## Skill coverage — what your skill files miss

Matching answers *which skill owns this question*. Coverage answers the follow-up
an owner has to act on: **the skill owns it — does the skill file actually show
it?**

A prompt cluster can match a skill on keywords alone while none of that skill's
`example_prompts` demonstrates the phrasing users really type. That is what
happens to every catalog over time: people find new ways to ask the same thing,
the skill keeps getting selected, and its examples quietly stop describing what
it is used for. Those clusters are the file's blind spots.

Coverage is measured **per skill file**, because that is the artifact someone
edits — a `SKILL.md` tree gives one skill per file, a shared catalog YAML gives
many, so both the skill and its file are always shown.

```bash
pheonix coverage           # per-file coverage + the lines to add
pheonix coverage --write   # ... and write them to <export-dir>/skill_updates.md
```

```
skill                      file                    asks  shown  gap  cover  top gap
signoff-commentary-draft   skills_catalog.yaml       34     28    6   82%  Write the narrative summary for credit sign-off
flash-formal-variance      skills_catalog.yaml       30     24    6   80%  Compare the flash number against the formal close for FX
fobo-break-triage          skills_catalog.yaml        6      0    6    0%  Are there recon breaks still unmatched on the credit book?
```

`cover` is the share of **asks** (not clusters) routed to that skill which its own
examples already demonstrate — a blind spot asked 40 times matters more than one
asked twice.

Each gap comes with the exact edit, in `skill_updates.md` and on the dashboard:

```yaml
example_prompts:
  # keep the existing 2, add:
  - "Are there recon breaks still unmatched on the credit book?"
keywords:
  # add: unmatched
```

Suggested keywords are extracted from the **normalized signature**, so masked
volatile tokens never leak in: the desk, book, amount or date a question happened
to mention is the instance, not the topic. Words already in the skill's name,
description or keywords are skipped, as are plurals of existing ones — a keyword
the matcher cannot discriminate with is worse than none.

### What changed since the last run

Every `analyze` snapshots its clusters, so consecutive runs can be diffed:

```
prompt pattern                              was   now  change  status
Why is there a credit recon break of ...      0    49     +49  new
Draft sign-off commentary for the rates...   11    34     +23  growing
Post an adjustment of 620k to EQ_VOL_LDN      2     0      -2  gone
```

Statuses are `new`, `growing`, `stable`, `shrinking`, `gone`; a count must move
more than 20% to count as movement rather than noise. Gaps that are new since the
previous run are flagged in the update blocks, so you can tell "users just started
asking this" from "we have never covered this". The first run has nothing to
compare against and correctly reports nothing as new. History is bounded by
`PHEONIX_RUN_HISTORY_LIMIT` (default 20 runs).

## Skills catalog inputs

Two sources, merged (catalog wins on name collisions):

1. `config/skills_catalog.yaml` — explicit entries with level/asset_class/capability/keywords/example_prompts.
2. `PHEONIX_SKILLS_DIRS` — comma-separated directories scanned recursively for
   `SKILL.md` files with YAML frontmatter (`name:` / `description:`), i.e. the format
   Claude-style skills already use. Optional `example_prompts:` and `keywords:`
   in the frontmatter are read too — `example_prompts` is what the coverage
   report measures real questions against, so a file that declares none will
   show 0% coverage until you add some (which is the honest answer).

## Dashboard UI

`pheonix serve` and open **http://127.0.0.1:8000/** — a self-contained dashboard
(no CDN, works offline) over the analytics below.

- **Scrape / Analyze / Report buttons** — run the pipeline from the page. Each
  runs synchronously, reports what it did in the status line, and repaints every
  panel. Scrape needs a live Phoenix connection; the other two work offline.
- **Filter bar** — project, user, stage, asset class, model, date range, and
  prompt-text search; every panel refetches with the active filters (options are
  populated from your actual data via `/filters/options`).
- **CSV on every panel** — exports exactly what the panel shows, honoring the
  active filters.
- **Spans explorer** — the raw filtered spans at the bottom, for validating what
  the analytics are computed from; its CSV carries up to 100k rows.
- The **X-API-Key** field applies when `PHEONIX_API_KEY` is set (kept in
  sessionStorage only).

| Panel | What it answers |
| --- | --- |
| KPI row | volume, sessions, users, tokens, cost, error rate, **% of spans passing validation** |
| **Skill coverage** | per skill file: asks routed to it vs asks its examples demonstrate |
| **What to add to each skill** | the exact `example_prompts` / `keywords` to paste, with evidence |
| **What changed since the last run** | patterns that are new, growing, shrinking, or gone |
| **Validation** | every check, how often it applied and failed, with a failing example |
| **Answer quality by user / model** | who is getting bad answers; whether one model refuses or truncates more |
| **Prompt patterns answered badly** | frequency × failure — the strongest case for a new skill |
| **Failed spans** | each failing span with its prompt, answer, and the reason, to confirm or dismiss |
| What users are asking | every user turn classified by intent (why/what/how/check/request/…) |
| Activity by day | asks per day with sessions and cost |
| Users — who asks what | per-user asks, re-asks, errors, route length, spend, top intents and prompt patterns |
| Agent flows | the step sequences the agent runs per ask (`LLM → TOOL ×3 → LLM`) |
| Tool / model usage | which tools the agent calls (failure rate, latency); tokens and cost per model |
| Workflow stage × asset class | where asks come from, when spans carry those metadata attributes |
| Where the agent works too hard | prompt patterns ranked by opportunity; **long route** = far more steps than the median trace — build/fix a skill here first |
| High-friction sessions | users re-asking the same question, errors, empty answers |
| Skill health | matched skills whose clusters still take long routes are flagged **review** |
| Proposed new skills | frequent asks no existing skill covers |

Every panel's data is also an endpoint (`/overview`, `/users`, `/insights/...`),
all filterable (`user_id`, `stage`, `asset_class`, `model_name`, `start`, `end`)
and downloadable with `fmt=csv`.

## CLI

```bash
uv run pheonix demo|seed|scrape|ingest|analyze|evaluate|coverage|report|serve|doctor
uv run pheonix evaluate [--user U] [--stage S] [--asset-class A] [--start ...] [--end ...] \
                        [--pull-annotations] [--push [--push-all]]
uv run pheonix coverage [--write]          # skill gaps + paste-ready blocks
uv run pheonix export --what spans|clusters|matches|proposals|sessions|evaluations|coverage|uncovered \
                      --fmt csv|json|parquet \
                      [--project X] [--start ...] [--end ...] [--stage ...] \
                      [--asset-class ...] [--min-count N] [--search TEXT] [--limit N]
```

## API (downloadable, filterable)

| Route | Purpose |
| --- | --- |
| `GET /quality/overview` | headline validation numbers (spans passing, failed checks) |
| `GET /quality/checks` | per-check scoreboard: applied, failed, fail rate, example |
| `GET /quality/by` | fail rates by `dimension=user_id\|model_name\|workflow_stage\|asset_class` |
| `GET /quality/failures` | failing spans with prompt, answer, and reason (`top=N`) |
| `GET /quality/by-prompt` | prompt clusters ranked by how badly they are answered |
| `GET /quality/evaluations` | raw judgements — one row per (span, check) |
| `GET /quality/catalog` | the registered checks and what each judges |
| `POST /annotations/pull` | fetch HUMAN/LLM span annotations from Phoenix |
| `POST /annotations/push` | write failing CODE checks back to Phoenix (`only_failures=`) |
| `GET /skills/coverage` | per skill file: asks routed to it vs asks it demonstrates |
| `GET /skills/uncovered` | the blind spots themselves, with evidence and run status |
| `GET /skills/updates` | paste-ready `example_prompts`/`keywords` per file |
| `GET /skills/updates.md` | the same as one markdown document |
| `GET /runs`, `GET /runs/delta` | run history, and what changed since the previous run |
| `POST /scrape/run`, `POST /analyze/run`, `POST /report/run` | trigger the pipeline |
| `GET /prompts/frequent` | prompt clusters by frequency (`min_count`, `fmt=json\|csv`) |
| `GET /skills/matches` | clusters matched to existing skills |
| `GET /skills/gaps` | proposed new skills with level + evidence |
| `GET /sessions` | derived sessions (turns, tokens, cost, models) |
| `GET /costs/summary` | cost rollup (`group_by=model_name\|workflow_stage\|asset_class\|user_id`) |
| `GET /spans` | raw filtered spans |
| `POST /demo/seed`, `POST /scrape/run` | seed fixtures / trigger live scrape |

Every list endpoint accepts filter query params; `fmt=csv` returns a download
(`Content-Disposition: attachment`).

## Layout

```
config/           skills_catalog.yaml, pricing.yaml (illustrative token pricing)
src/phoenix_scraper/
  phoenix_client  the ONLY module that talks to Phoenix (auth, retries)
  scraper         OpenInference attr flattening + watermark scrape + jsonl ingest
  normalize/cluster       prompt signatures and frequency clustering
  skills/taxonomy/skills_mapper   catalog loading, level inference, matching + proposals
  evaluations     the CODE annotator: offline output and prompt validators
  annotations     pull HUMAN/LLM annotations from Phoenix, push CODE ones back
  skill_coverage  what each skill FILE is asked but doesn't show; run-over-run diffs
  insights*       analytics: traces, users, LLM behaviour, quality rollups
  costs/sessions  token->cost from pricing.yaml, session derivation
  storage         SQLite store (spans, state, analysis, evaluations, run history)
  pipeline/cli/api        orchestration, Typer CLI, FastAPI service
tests/            538 tests, ~94% coverage (`make test`)
```

## POC limitations (deliberate)

- Clustering is lexical (normalize + rapidfuzz), not embedding-based — good enough to
  demonstrate the mechanism; swap in embeddings for semantic grouping later.
- Validation is code-based only: no LLM judge is bundled, so nothing here scores
  *semantic* correctness. `answer_relevance` and `answer_groundedness` are proxies with
  the limits spelled out above. The natural next step is running `phoenix.evals`
  (`HallucinationEvaluator`, `QAEvaluator`, …) on a sample and logging the results back
  to Phoenix — `--pull-annotations` then brings those scores into these same panels
  with no further work.
- Cost falls back to `config/pricing.yaml` when spans carry no cost attribute — the
  prices are illustrative, not your negotiated Bedrock rates.
- Single-writer SQLite; fine for a POC, not for concurrent production jobs.
- Stage/asset-class attribution relies on span `metadata.workflow_stage` /
  `metadata.asset_class` attributes when scraping live (fixtures set them).
