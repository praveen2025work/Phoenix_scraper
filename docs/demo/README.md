# MD demo pack — Phoenix / FOBO guided run

Materials for a **10–15 minute** Managing Director (or similar) walkthrough.

| Artifact | Use |
| --- | --- |
| [md-demo-script-10-15.md](./md-demo-script-10-15.md) | Timed speaker script: problem → solution → live demo → ask |
| [md-slide-deck.md](./md-slide-deck.md) | Slide outline (paste into PowerPoint / Google Slides / Marp) |
| [gap-analysis.md](./gap-analysis.md) | Have we solved the right problem? Covered vs open gaps |
| [one-pager.md](./one-pager.md) | Single page leave-behind |

## Supporting design docs (already in repo)

Bring or link these if MD wants depth after the demo:

- [BRD](../brd.md) — problem, goals, success criteria  
- [Guided run design](../superpowers/specs/2026-09-10-guided-run-workflow-design.md)  
- [Promotion ladder design](../superpowers/specs/2026-09-07-capability-promotion-ladder-design.md)  
- [Architecture](../architecture.md) + [Flows](../flows.md) (Mermaid)  
- [Skills](../skills.md) · [Span scrape & filter](../span-scrape-and-filter.md) · [Processing logic](../processing-logic.md)

## Pre-demo checklist

1. API + UI running (`make api` / `make ui`); FOBO capability seeded with skill MDs.  
2. Closed window with known FOBO traffic (or `pheonix demo` / fixture data).  
3. One completed run with **skill gaps** + at least one Decide card per lane if possible.  
4. Hard-refresh UI so full-width shell + skill side-by-side diff are live.  
5. Tab ready: Setup → Running → Results → Decide → (optional) Usage / History.
