---
name: fx-recon-break-triage
description: Triage FX front-office/back-office reconciliation breaks and classify causes.
keywords:
  - fx
  - break
  - recon
  - reconciliation
  - fobo
  - mismatch
example_prompts:
  - Why is there an FX recon break on the EURUSD book?
  - Classify today's FX FOBO breaks
---

# fx-recon-break-triage

Use this skill when the desk asks why an FX FOBO recon break exists or how to classify open breaks.

## Procedure

1. Confirm the currency pair / book from the question.
2. Pull open FOBO breaks for that book.
3. Classify cause (timing, SSI, trade amend, cash vs position).
4. Propose next action (investigate, adjust, or close as noise).
