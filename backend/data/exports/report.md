# Prompt Mining Report

- Generated at: 2026-09-10T15:27:55.510253+00:00
- Spans analyzed: 388
- Prompt clusters: 55
- Skill matches: 15
- Skill gap proposals: 6
- Validation checks: 2796

## Top prompts

| Prompt | Count | Sessions | Users | Cost | Asset classes | Stages |
| --- | --- | --- | --- | --- | --- | --- |
| Why is there an FX recon break of 620k on EURUSD_LDN? | 35 | 29 | 7 | $0.16 | credit, equities, fx, rates | fobo_recon |
| Draft sign-off commentary for the rates desk | 28 | 25 | 8 | $0.14 | credit, equities, fx, rates | commentary_signoff |
| Show flash vs formal variance for 2026-08-28 | 24 | 22 | 7 | $0.12 | credit, equities, fx, rates | flash_vs_formal |
| List unmatched FOBO trades over 120k for EQ_DELTA1_NY | 15 | 14 | 7 | $0.05 | credit, equities, fx | fobo_recon |
| Explain the top PLEX drivers for FX on 2026-09-09 | 14 | 12 | 6 | $0.07 | credit, equities, fx, rates | plex |
| Summarise flash vs formal breaks above 120k for 2026-09-04 | 11 | 9 | 6 | $0.06 | credit, equities, fx, rates | flash_vs_formal |
| Run PLEX attribution for equities | 10 | 9 | 4 | $0.04 | equities, fx | plex |
| Suggest an adjustment for the wrong day-count on the swap leg | 10 | 9 | 4 | $0.04 | credit, equities, fx, rates | adjustments |
| Is the FX desk ready for sign-off on 2026-08-28? | 8 | 8 | 6 | $0.03 | credit, equities, fx, rates | commentary_signoff |
| Are there recon breaks still unmatched on the credit book? | 6 | 6 | 3 | $0.02 | credit, equities, rates | fobo_recon |
| Compare the flash number against the formal close for FX | 6 | 6 | 4 | $0.02 | equities, fx, rates | flash_vs_formal |
| Download the FX adjustments report in excel format | 6 | 5 | 4 | $0.03 | credit, equities, fx, rates | adjustments |
| Suggest an adjustment for the stale FX fixing on the London book | 6 | 6 | 5 | $0.03 | fx, rates | adjustments |
| Post the correction to amend the rates book adjustment | 6 | 6 | 5 | $0.03 | credit, equities, fx, rates | adjustments |
| Suggest an adjustment for the missed dividend accrual | 6 | 5 | 4 | $0.03 | credit, equities, fx | adjustments |
| What drove the rates carry and curve PLEX move on credit? | 6 | 6 | 4 | $0.03 | credit, equities, fx, rates | plex |
| Write the narrative summary for credit sign-off | 6 | 6 | 4 | $0.03 | credit, equities, fx, rates | commentary_signoff |
| Suggest an adjustment for the late booked novation | 5 | 5 | 4 | $0.02 | credit, equities, fx | adjustments |
| Run PLEX attribution for credit | 4 | 3 | 3 | $0.01 | credit | plex |
| Run PLEX attribution for rates | 4 | 4 | 4 | $0.02 | rates | plex |

## Output & prompt validation

2796 checks over 388 spans; 67 failed.

| Check | Judges | Failed | Evaluated | Rate | Example |
| --- | --- | --- | --- | --- | --- |
| answer_relevance | output | 13 | 243 | 5% | Answer shares 0% of the question's terms (target 15%); unaddressed: attribution, equities, plex, run. |
| output_truncated | output | 12 | 244 | 5% | Answer ends without terminal punctuation: …'stigated by the product control team and'. |
| output_empty | output | 10 | 254 | 4% | The model returned no output for this ask. |
| output_refusal | output | 8 | 244 | 3% | Answer opens with a refusal marker: 'i cannot'. |
| span_status | span | 7 | 388 | 2% | Span finished with status ERROR. |
| answer_groundedness | output | 7 | 7 | 100% | Answer states figures absent from the question and from every tool result in the trace: 1284905, 92447. |
| output_repetition | output | 4 | 12 | 33% | Only 27% of 88 words are distinct (below the 35% floor). |
| prompt_pii | prompt | 2 | 254 | 1% | Prompt appears to contain email address, phone number — review before sharing this trace. |
| prompt_clarity | prompt | 2 | 254 | 1% | 3-word ask whose only concrete term is 'fix' — the agent must infer what again, it refers to. |
| prompt_injection | prompt | 2 | 254 | 1% | Prompt contains override of prior instructions: 'ignore previous'. |

## Skill coverage gaps — what to add to each file

### skills_catalog.yaml — adjustment-suggester

6 asks · 5 users · 2026-08-30 to 2026-09-07

Add these `example_prompts`:

- Post the correction to amend the rates book adjustment

Add these `keywords`: -

### skills_catalog.yaml — data-export-help

6 asks · 4 users · 2026-08-29 to 2026-09-09

Add these `example_prompts`:

- Download the FX adjustments report in excel format

Add these `keywords`: adjustments

### skills_catalog.yaml — signoff-commentary-draft

6 asks · 4 users · 2026-08-31 to 2026-09-07

Add these `example_prompts`:

- Write the narrative summary for credit sign-off

Add these `keywords`: -

### skills_catalog.yaml — rates-plex-analysis

6 asks · 4 users · 2026-08-31 to 2026-09-07

Add these `example_prompts`:

- What drove the rates carry and curve PLEX move on credit?

Add these `keywords`: -

### skills_catalog.yaml — flash-formal-variance

6 asks · 4 users · 2026-08-29 to 2026-09-08

Add these `example_prompts`:

- Compare the flash number against the formal close for FX

Add these `keywords`: -

### skills_catalog.yaml — fobo-break-triage

6 asks · 3 users · 2026-08-29 to 2026-09-06

Add these `example_prompts`:

- Are there recon breaks still unmatched on the credit book?

Add these `keywords`: -


## Matched skills

| Skill | Prompt | Score | Method |
| --- | --- | --- | --- |
| adjustment-suggester | Post the correction to amend the rates book adjustment | 0.82 | keyword+fuzzy |
| rates-plex-analysis | Run PLEX attribution for rates | 0.75 | keyword+fuzzy |
| flash-formal-variance | Show flash vs formal variance for 2026-08-28 | 0.74 | keyword+fuzzy |
| signoff-commentary-draft | Draft sign-off commentary for the rates desk | 0.70 | keyword+fuzzy |
| adjustment-suggester | Suggest an adjustment for the stale FX fixing on the London book | 0.70 | keyword+fuzzy |
| data-export-help | Download the FX adjustments report in excel format | 0.66 | keyword+fuzzy |
| fx-recon-break-triage | Why is there an FX recon break of 620k on EURUSD_LDN? | 0.66 | keyword+fuzzy |
| adjustment-suggester | Suggest an adjustment for the late booked novation | 0.63 | keyword+fuzzy |
| signoff-commentary-draft | Write the narrative summary for credit sign-off | 0.62 | keyword+fuzzy |
| rates-plex-analysis | What drove the rates carry and curve PLEX move on credit? | 0.61 | keyword+fuzzy |
| flash-formal-variance | Compare the flash number against the formal close for FX | 0.60 | keyword+fuzzy |
| rates-plex-analysis | Run PLEX attribution for credit | 0.60 | keyword+fuzzy |
| fobo-break-triage | Are there recon breaks still unmatched on the credit book? | 0.60 | keyword+fuzzy |
| rates-plex-analysis | Run PLEX attribution for equities | 0.59 | keyword+fuzzy |
| adjustment-suggester | Suggest an adjustment for the missed dividend accrual | 0.58 | keyword+fuzzy |

## Proposed new skills

### Capability

| Proposed skill | Asset class | Capability | Evidence | Prompt | Description |
| --- | --- | --- | --- | --- | --- |
| list-unmatched-fobo-trades | - | fobo_recon | 15 | List unmatched FOBO trades over 120k for EQ_DELTA1_NY | Proposed skill covering 15 similar prompts (fobo_recon), e.g. "List unmatched FOBO trades over 120k for EQ_DELTA1_NY". |
| explain-top-plex-drivers | - | plex | 14 | Explain the top PLEX drivers for FX on 2026-09-09 | Proposed skill covering 14 similar prompts (plex), e.g. "Explain the top PLEX drivers for FX on 2026-09-09". |
| summarise-flash-formal-breaks | - | flash_vs_formal | 11 | Summarise flash vs formal breaks above 120k for 2026-09-04 | Proposed skill covering 11 similar prompts (flash_vs_formal), e.g. "Summarise flash vs formal breaks above 120k for 2026-09-04". |
| suggest-adjustment-wrong-day | - | adjustments | 10 | Suggest an adjustment for the wrong day-count on the swap leg | Proposed skill covering 10 similar prompts (adjustments), e.g. "Suggest an adjustment for the wrong day-count on the swap leg". |
| ready-sign-off | - | commentary_signoff | 8 | Is the FX desk ready for sign-off on 2026-08-28? | Proposed skill covering 8 similar prompts (commentary_signoff), e.g. "Is the FX desk ready for sign-off on 2026-08-28?". |
| suggest-adjustment-duplicated-ticket | - | fobo_recon | 4 | Suggest an adjustment for the duplicated ticket in the back office ledger | Proposed skill covering 4 similar prompts (fobo_recon), e.g. "Suggest an adjustment for the duplicated ticket in the back office ledger". |

## Session & cost summary

- Sessions: 60
- Distinct users: 8
- Total tokens: 198182
- Total cost: $1.15
- Models: us.anthropic.claude-haiku-4-5, us.anthropic.claude-sonnet-4-6
