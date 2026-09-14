# Phoenix / FOBO — one-pager

**What it is:** An advisory tool that mines Phoenix spans for a capability (FOBO first), shows which user questions skills miss, and queues promotions to **skills** or **deterministic** drafts.

**What it is not:** The live FOBO agent, an auto-router, or a guaranteed LLM cost cut without eng cutover.

## Problem

Repeated FOBO questions hit the LLM every time → cost, latency, variance. We need a repeatable way to find (1) skill gaps and (2) stable tool paths.

## Solution

Guided run: **Setup → Running → Results → Decide → History**

- Closed time window + skill `.md` uploads  
- Versioned results with **skill gaps first**  
- Decide lanes: Skill (questions) vs Deterministic (SQL/tools)  
- Skill update **old | new** diff with copy/download  

## Demo (minutes)

Setup & run → gaps + diff → Decide lanes → (optional) version compare / Usage.

## Ask

FOBO weekly gap-review pilot; measure skills updated and deterministic drafts in 2 weeks.

## Gaps to name

Lexical match only · drafts not served live · job scale / SSO later.

**Docs:** `docs/demo/` · BRD · guided-run + ladder specs under `docs/superpowers/specs/`.
