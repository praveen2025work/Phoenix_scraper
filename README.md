# pheonix — Phoenix Prompt Miner (POC)

Scrapes **Arize Phoenix** observability data (traces, spans, sessions, prompts, token
usage/cost), identifies the **most frequently asked user prompts**, matches them against
your **existing skills catalog**, and proposes **new skills** slotted at the right level:

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

**Option A — uv (preferred):**

```bash
make setup                 # = uv sync --all-extras (creates .venv, fetches Python 3.11 if needed)
```

**Option B — pip only:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # pinned runtime deps
pip install -e . --no-deps               # installs the `pheonix` command
pip install arize-phoenix-client~=2.13   # only if you'll scrape live Phoenix
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

```bash
cp .env.example .env
```

Fill in:

| Variable | Where to get it |
| --- | --- |
| `PHOENIX_COLLECTOR_ENDPOINT` | your Phoenix base URL, e.g. `https://phoenix.<internal-domain>` (no trailing `/`) |
| `PHOENIX_API_KEY` | Phoenix UI → **Settings → API Keys** → create a **System** key (survives user changes; ask a Phoenix admin if the menu is missing) |
| `PHEONIX_PROJECT` | the Phoenix project name your agent traces land in (visible in the Phoenix UI project list) |

Then:

```bash
pheonix scrape      # one incremental watermark cycle
pheonix analyze
pheonix report
```

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
| SSL certificate errors | corporate TLS inspection — set `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` (step 2) |
| `Phoenix is not available` from `pheonix scrape` | endpoint unset/wrong, or `arize-phoenix-client` not installed (`uv sync --extra live`) |
| `401` from Phoenix | key expired/revoked — issue a fresh System key in Phoenix Settings |
| Scrape succeeds but 0 spans | wrong `PHEONIX_PROJECT` name, or the time window: the watermark starts from your first run — wait a cycle or check the project has recent traces |
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

## Skills catalog inputs

Two sources, merged (catalog wins on name collisions):

1. `config/skills_catalog.yaml` — explicit entries with level/asset_class/capability/keywords/example_prompts.
2. `PHEONIX_SKILLS_DIRS` — comma-separated directories scanned recursively for
   `SKILL.md` files with YAML frontmatter (`name:` / `description:`), i.e. the format
   Claude-style skills already use.

## CLI

```bash
uv run pheonix demo|seed|scrape|ingest|analyze|report|serve
uv run pheonix export --what spans|clusters|matches|proposals|sessions \
                      --fmt csv|json|parquet \
                      [--project X] [--start ...] [--end ...] [--stage ...] \
                      [--asset-class ...] [--min-count N] [--search TEXT] [--limit N]
```

## API (downloadable, filterable)

| Route | Purpose |
| --- | --- |
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
  costs/sessions  token->cost from pricing.yaml, session derivation
  storage         SQLite store (spans, state, analysis results)
  pipeline/cli/api        orchestration, Typer CLI, FastAPI service
tests/            203 tests, ~91% coverage (`make test`)
```

## POC limitations (deliberate)

- Clustering is lexical (normalize + rapidfuzz), not embedding-based — good enough to
  demonstrate the mechanism; swap in embeddings for semantic grouping later.
- Cost falls back to `config/pricing.yaml` when spans carry no cost attribute — the
  prices are illustrative, not your negotiated Bedrock rates.
- Single-writer SQLite; fine for a POC, not for concurrent production jobs.
- Stage/asset-class attribution relies on span `metadata.workflow_stage` /
  `metadata.asset_class` attributes when scraping live (fixtures set them).
