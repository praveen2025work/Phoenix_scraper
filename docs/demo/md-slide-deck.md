# MD slide deck outline (10–12 slides)

Use as PowerPoint / Google Slides / [Marp](https://marp.app/) source.  
One idea per slide. Speaker notes = bullets under each slide.

---

## Slide 1 — Title

**Phoenix Prompt Miner**  
FOBO guided runs: find what to skill, what to make deterministic  

_Subtitle:_ Advisory mining of Phoenix spans — not the live agent path  

**Notes:** Name, date, your role. “Demo + decision framing, 15 minutes.”

---

## Slide 2 — The problem

**Same FOBO questions. Same LLM cost. Every time.**

- Users ask recurring reconciliation questions  
- Agent re-derives answers via LLM + tools  
- Cost ↑ · Latency ↑ · Answer variance ↑  

**Notes:** Ground in MD’s world (ops cost / control). Avoid Phoenix jargon here.

---

## Slide 3 — Two fixes we already know

| Pattern | Signal | Action |
| --- | --- | --- |
| Prompt → **Skill** | Same question, many users, no skill | Write / strengthen skill MD |
| Stable path → **Deterministic** | Same tools/SQL/route every time | Draft deterministic handler |

**Notes:** “Product finds candidates; humans decide; eng owns cutover.”

---

## Slide 4 — What was broken

**We had engines; we lacked an operator loop.**

- Filters / analytics dominated  
- No clear session → scrape status → results → decide  
- Skill gaps buried  
- SQL/MCP noise in “promote to skill”  

**Notes:** Honesty builds trust. Then: “So we reshaped the product.”

---

## Slide 5 — Solution shape

**Guided capability run (FOBO)**

```
Setup → Running → Results → Decide → History
```

- Versioned runs (closed window + skill hashes)  
- Results lead with **skill gaps**  
- Decide: **Skill lane** \| **Deterministic lane**  

**Notes:** Point to live UI for next slides; this is the map.

---

## Slide 6 — Architecture (one diagram)

**Keep simple:**

UI → API → Job worker → Phoenix scrape → Cluster / match → Store → Results / Decide  

_Optional Mermaid from `docs/architecture.md` — only if MD wants tech._

**Notes:** “Advisory. Lexical NLP. No parallel analysis stack.”

---

## Slide 7 — Live demo agenda

1. Setup window + skills  
2. Run stages  
3. Skill gaps + old/new MD diff  
4. Decide lanes  

**Notes:** Switch to browser. Don’t stay on this slide.

---

## Slide 8 — Demo screenshot placeholders

| Panel | Capture |
| --- | --- |
| Setup | Window + skill list |
| Running | Stage progress |
| Results | Skill gaps + side-by-side diff |
| Decide | Skill vs Deterministic queues |

**Notes:** Prefer live UI; screenshots are backup if scrape fails.

---

## Slide 9 — Value

- **Visibility:** which questions skills miss this week  
- **Control:** promote deliberately, with evidence  
- **Efficiency:** path to lower LLM spend on FOBO repeats  
- **Audit:** versioned runs, skill hashes, gap closed vs new  

**Notes:** Tie to cost and operational discipline, not “cool AI.”

---

## Slide 10 — Coverage vs gaps

**Solved for pilot**

- Guided loop, segregation, scrape honesty, skill diff/copy  

**Open by design / next**

- Paraphrase matching (embeddings/LLM later)  
- Runtime that serves promotions  
- Scale workers, SSO, notifications  

**Notes:** Use `gap-analysis.md`. Don’t oversell.

---

## Slide 11 — Ask

**Recommended:** FOBO weekly gap review pilot  

Metrics in 2 weeks:

- Skills updated from gaps  
- Deterministic drafts accepted for eng backlog  
- Operator hours on guided path (vs ad-hoc logs)  

**Notes:** One clear ask.

---

## Slide 12 — Appendix (hold)

- BRD / design doc links  
- Skill upload = `.md`; capability = YAML scaffold  
- Glossary: span, cluster, rung, capability  

---

## Marp front matter (optional)

```markdown
---
marp: true
paginate: true
title: Phoenix FOBO guided runs
---
```

Paste each slide as `# Title` + bullets.
