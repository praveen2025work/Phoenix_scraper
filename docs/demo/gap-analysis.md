# Solution coverage & gap analysis

**Question:** For the FOBO / Phoenix mining problem, have we identified solutions properly, or are there gaps?

**Short answer:** The **problem framing and solution shape are correct** for an *advisory operator loop*. Several **execution and platform gaps** remain; a few **adjacent problems** are intentionally out of scope and should not be sold as done.

---

## 1. Problem identification — solid

| Problem element | Status | Evidence |
| --- | --- | --- |
| Repeat LLM cost on same FOBO asks | Identified | BRD §1; ladder design |
| Two promotion levers (skill vs deterministic) | Identified & productized | Rung 1 / Rung 2 lanes |
| Need closed-window, versioned evidence | Identified & implemented | Guided run + `capability_runs` |
| Operator UX was wrong shape (filters > decisions) | Identified & largely fixed | Setup → Running → Results → Decide |
| Wrong artifacts in skill queue | Identified & fixed | Prompt-shape segregation + UI lanes |

No major *misdiagnosis* of the core problem.

---

## 2. Solutions identified — map

| Solution | Fit | Implemented? | Residual risk |
| --- | --- | --- | --- |
| Guided run workflow | Right primary product | Yes | Polish / empty-funnel messaging |
| Lexical cluster + skill match | Right for v1 speed/cost | Yes | Misses paraphrases |
| Skill gap–first Results | Right outcome | Yes | Depends on scrape/filter quality |
| Promote to skill MD | Right artifact type | Yes | Human edit quality varies |
| Old/new skill diff + copy/download | Right operator affordance | Yes | Side-by-side needs wide viewport |
| Promote to deterministic drafts | Right second lever | Partial | Draft ≠ production cutover |
| Closed window + truncation honesty | Right reliability | Yes | Phoenix API limits still bite |
| Job stage progress | Right trust signal | Yes | Coarse mid-scrape progress |
| Usage snapshots per version | Right secondary view | Yes | Snapshot lag / partial runs |
| Capability YAML + skill MD split | Right packaging | Yes | Operators confuse YAML vs MD |

---

## 3. Gaps (prioritized)

### P0 — Say explicitly in the MD room

1. **Not in the live path** — Promotions are drafts/advice. Serving traffic needs a separate runtime / agent change programme.  
2. **Matching is lexical** — Paraphrase and multi-lingual asks can be under-detected. Embeddings / LLM-as-judge are a known next phase, not missing from the *problem* list — missing from *delivery*.  
3. **Deterministic lane stops at drafts** — No automatic replacement of tool calls in FOBO agent.

### P1 — Product / ops gaps

4. **Scrape dependency** — Wrong `filter.project` / env → 0 in-scope (we mitigated with SoT + UI, but ops mistakes still happen).  
5. **Single job worker** — Long scrapes queue; no cancel.  
6. **Evidence thresholds** — Demo FOBO thresholds are lowered; production thresholds need governance.  
7. **Skill propose → file write → agent reload** — Loop requires human re-upload / deploy discipline; not fully closed-loop.

### P2 — Platform / enterprise

8. SSO, audit export beyond run history, notifications.  
9. Multi-capability roll-out playbook (beyond FOBO).  
10. Multi-Phoenix / multi-region.

### Intentionally out of scope (not gaps in identification)

- Building a second analysis stack  
- LLM clustering in v1  
- Job distributed queue  
- Auto-merging skills without review  

---

## 4. “Have we identified all solutions properly?”

| Lens | Verdict |
| --- | --- |
| **Operator discovery loop** | Yes — solutions match the problem |
| **Cost reduction end-to-end** | Partially — discovery yes; runtime cutover no |
| **Matching quality at bank scale** | Partially — v1 approach correct; quality ceiling known |
| **Enterprise readiness** | No — not claimed; list as follow-on |

**Recommendation for MD narrative:**  
Frame this as **Phase 1: see and decide**. Phase 2 is **match quality**. Phase 3 is **serve promotions in the agent**. Do not present Phase 1 as full cost takeout.

---

## 5. Suggested pilot success metrics (2–4 weeks)

- # skill gaps reviewed / closed via MD re-upload  
- # skill files written from Decide  
- # deterministic drafts accepted into eng backlog  
- Operator time on guided path vs log diving  
- (Leading) reduction candidates estimated from gap volume — not realized $ until runtime

---

## 6. How to fix the gaps (remediation plan)

### P0 — name in the room, then schedule

| Gap | Fix approach | Owner shape | Horizon |
| --- | --- | --- | --- |
| **Not in live path** | Define a “promotion cutover” contract: skill MD / deterministic stub → FOBO agent reload path (config flag, skill pack version, or CI publish). Pilot: 1–2 skills served from miner drafts. | Agent platform + FOBO eng | Phase 3 |
| **Lexical match only** | Keep lexical as default. Add optional embedding nearest-neighbour (or LLM-as-judge behind flag) for “near miss” gaps; evaluate precision/recall on a labeled FOBO week. Do not replace v1 overnight. | Miner eng | Phase 2 |
| **Deterministic = draft only** | Pair each accepted Rung-2 card with a ticket template (handler signature, fixtures from templates, owner). Track “draft → merged → flagged in agent” in History notes or external board. | FOBO eng + miner | Phase 3 |

### P1 — product / ops

| Gap | Fix approach |
| --- | --- |
| **Wrong project / 0 in-scope** | Keep `filter.project` SoT; Setup warning when preview in-scope = 0; refuse Run or hard-warn if env/capability project mismatch. |
| **Single worker / no cancel** | Job cancel API + cooperative abort in scrape loop; later: multi-worker queue. |
| **Demo thresholds in prod** | Capability-level “profile”: `demo` vs `production` threshold presets; gate ready bar on production profile for FOBO sign-off. |
| **Skill propose → reload** | After upload, show “skills frozen for next run” + one-click “Run next version”; document agent-side reload if skills are also consumed live. |

### P2 — platform

SSO, richer audit export, Slack/email on `ready` candidates, multi-capability playbook, multi-Phoenix.

### Skill update integrity (related concern)

**Already mitigated:** strengthen / suggested updates **merge** prompts & keywords into existing frontmatter and **preserve body** — they are not a full rewrite of the skill essay. Diff UI (current vs proposed) + copy/download lets operators verify before re-upload. Decide `strengthen_skill` does not auto-overwrite files.

**Further hardening (optional):**

1. UI badge: “N prompts added · body unchanged”.  
2. API field `merge_mode: merge | scaffold`.  
3. Reject upload if body hash changed unexpectedly when operator intended merge-only.  
4. Unit/contract tests already around `_merge_skill_md`; keep golden fixtures for FOBO skills.

---

## 7. Doc pointers

- BRD out-of-scope: `docs/brd.md` §8  
- Guided run non-goals: `docs/superpowers/specs/2026-09-10-guided-run-workflow-design.md`  
- Ladder non-goals: `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`  
- Skill merge semantics: `docs/skills.md` (§ Strengthen ≠ rewrite)
