# MD demo script (10–15 minutes)

**Audience:** Managing Director / senior stakeholder  
**Product:** Phoenix Prompt Miner — FOBO capability (guided run)  
**Tone:** Business outcome first; one technical slide max; live product does the proof.

---

## Timing overview

| Min | Block | Goal |
| --- | --- | --- |
| 0:00–2:00 | Problem | Why this burns money and trust |
| 2:00–4:30 | Solution framing | Capability runs → gaps → promote skill vs deterministic |
| 4:30–12:00 | Live demo | Setup → Run → Results → Decide (+ skill diff) |
| 12:00–14:00 | Impact & gaps | What we ship vs what’s still open |
| 14:00–15:00 | Ask / close | Decision or next checkpoint |

---

## 0:00 – Problem (≈2 min)

**Opening line:**  
“Our FOBO agent answers the *same* reconciliation questions again and again — every time through the LLM. That means cost, latency, and answer drift. We already know two fixes; we lacked an operator loop to *find* them from production traces.”

**Two transformation stories (plain language):**

1. **Question → Skill** — Many users ask the same thing; no skill covers it → agent re-derives the approach each time. A skill locks the approach.  
2. **Stable LLM path → Deterministic** — Same tool/SQL/route every time → LLM is ceremony. Code should own it.

**Pain we hit before this product:**  
Filters and dashboards dominated. Operators couldn’t see: *this window → scrape with status → questions skills miss → decide what to promote.* Wrong items (SQL, MCP payloads) polluted “promote to skill.”

**One sentence:**  
“This tool does not run the agent — it *mines* Phoenix spans and tells operators what to promote next.”

---

## 2:00 – Solution (≈2.5 min)

**What we built:** a **guided capability run** for FOBO:

```
Setup → Running → Results → Decide → History
```

| Piece | Stakeholder meaning |
| --- | --- |
| Capability | FOBO owned folder: filter + skills + versions |
| Versioned run | Closed `from`/`to`; skill file hashes frozen; funnel counts |
| Results | **Skill gaps first** — questions not covered by uploaded skills |
| Decide | Two lanes: **Skill (Rung 1)** vs **Deterministic (Rung 2)** |
| Skill update | Old vs new MD (side-by-side), Copy / Download → re-upload if they like it |
| Usage | Cost/volume for *this version’s window* — secondary |

**Engine (one breath):** lexical NLP only this phase — cluster similar questions, match to skills, score stability for deterministic. No LLM-in-the-loop for matching.

**Show slide:** “Loop” diagram (Setup → Scrape → Cluster/Match → Gaps → Promote → Next version).

---

## 4:30 – Live demo (≈7.5 min)

### Prep (before MD enters)

- FOBO open on Setup.  
- Skills already uploaded (or one MD ready to show upload).  
- Short closed window that will return gaps (known good demo data).  
- Prior run ready if live scrape is slow — then still show Running stages on a quick re-run *or* walk a finished version and narrate stages.

### Demo beats

**1. Setup (≈1.5 min)**  
- “Closed window only — no open-ended first pull.”  
- Point at skill files (`.md` with frontmatter — not YAML skills).  
- “Capability YAML is scaffolded; operators upload skill markdown.”  
- Collapse Advanced filter: “Project comes from FOBO config / env — don’t wipe it.”  
- Click **Run now**.

**2. Running (≈1 min)**  
- Stages: queued → scraping → analyzing → matching.  
- “If truncated, we say so — we don’t silently empty Results.”  
- Stay on progress; don’t bounce to an empty board.

**3. Results — skill gaps (≈2 min)**  
- Lead with **Skill gaps**: clustered user questions not covered.  
- Funnel line: spans → in-scope → clusters → gaps (explain a zero if it happens).  
- Open a **suggested skill update**: left **Current (uploaded)** | right **Proposed (latest)**.  
- **Copy proposed** / **Download .md** — “Operator can take this file straight back into Setup.”

**4. Decide (≈2 min)**  
- **Skill lane:** user questions → Accept / Write skill file.  
- **Deterministic lane:** SQL / MCP / params — *not* promote-to-skill.  
- “Segregation was a real bug; we fixed the product so Decide matches the ladder.”  
- Optional: Accept → Write (show draft path under capability skills / deterministic).

**5. Optional 30s:** History / version compare — gaps closed vs new after skill re-upload; Usage for this version.

### Demo don’ts

- Don’t deep-dive analytics charts unless asked.  
- Don’t debug Phoenix connectivity live — have offline/demo path ready.  
- Don’t show raw Bedrock JSON as a “question” — if it appears, say it’s filtered as deterministic-shaped.

---

## 12:00 – Impact & honesty on gaps (≈2 min)

**Covered well today**

- Guided loop and versioned runs  
- Skill-gap-first Results  
- Rung 1 vs Rung 2 segregation + skill MD diff/copy/download  
- Closed-window scrape honesty and job progress  
- Usage snapshots for the run window  

**Still open (say this before they ask)**

| Gap | Why it matters | Direction |
| --- | --- | --- |
| Lexical match only | Paraphrases may miss | Embeddings / LLM-judge later (explicit non-goal for v1) |
| Advisory only | Drafts don’t auto-serve traffic | Runtime consumer is a separate programme |
| Single worker / no cancel | Long scrapes queue | Scale jobs when FOBO volume demands |
| No SSO / notifications | Fine for ops pod; not bank-wide rollout | Platform follow-on |
| Deterministic “write” ≠ production cutover | Drafts need eng ownership | Process + runtime |

**Line:** “We’ve identified the *right* two levers and built the operator loop. We have not claimed to replace the agent runtime or solve paraphrase matching — those are next-horizon.”

---

## 14:00 – Ask / close (≈1 min)

Pick one:

1. **Endorse FOBO as pilot capability** for weekly gap reviews.  
2. **Checkpoint** in 2 weeks: X skills updated from gaps; Y deterministic drafts handed to eng.  
3. **Priority call** on next investment: matching quality vs runtime cutover vs more capabilities.

**Close:**  
“Same questions → skills. Stable routes → deterministic. This product finds both from real Phoenix traffic — and makes the operator the decision-maker.”

---

## Backup answers (30s each)

| Question | Answer |
| --- | --- |
| Does this call the LLM? | Matching is lexical. Agent traffic is already in Phoenix; we read spans. |
| YAML or MD for skills? | Skills are **`.md`**. Capability config is YAML (auto-created). |
| Is cloud a different build? | Same `main`; UI must hard-refresh after deploys (full-width + diffs). |
| Security? | Operator API key / actor; advisory; no live request path. |
| Why FOBO first? | Clear filter, high repeat questions, strong cost story. |
