# Phoenix Scraper — product & engineering docs

Operator-facing and engineering documentation for **pheonix** (`phoenix_scraper`).
Design history and phased plans live under [`superpowers/`](./superpowers/); this
folder is the current product/engineering reference.

| Doc | What it covers |
| --- | --- |
| [brd.md](./brd.md) | Business requirements: problem, goals, users, guided run workflow, success criteria |
| [skills.md](./skills.md) | Skills upload/match, FOBO skill path, hashing, Rung 1 promote-to-skill, Decide skill lane |
| [architecture.md](./architecture.md) | System architecture (Mermaid): UI, API, JobWorker, Store, Phoenix client, ladder |
| [flows.md](./flows.md) | End-to-end run flow + Decide skill vs deterministic lanes (Mermaid) |
| [span-scrape-and-filter.md](./span-scrape-and-filter.md) | Closed windows, `filter.project` SoT, scrape subdivision, in-scope vs raw spans |
| [processing-logic.md](./processing-logic.md) | Clustering, prompt shape, Rung 1/2 detection, candidates, promotion, thresholds |
| [demo/](./demo/) | MD demo pack: 10–15 min script, slide outline, one-pager, gap analysis |

## Related (existing)

- [`../README.md`](../README.md) — repo overview and how to run the stack
- [`../backend/README.md`](../backend/README.md) — CLI, API, config, mining model
- [`../backend/CONTRACTS.md`](../backend/CONTRACTS.md) — storage / API contracts
- [`superpowers/specs/`](./superpowers/specs/) — approved design specs (ladder, async jobs, guided run)
- [`superpowers/plans/`](./superpowers/plans/) — phase implementation plans
