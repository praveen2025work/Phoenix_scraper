# equity-recon-break — deterministic candidate

Source candidate: `fobo:d:b381d904a9df`  ·  determinism_score **0.9496**  ·  34 answer spans

## Signals

| signal | value |
|---|---|
| template_concentration | 1.0 |
| route_invariance | 1.0 |
| output_self_similarity | 0.9057 |
| slot_stability | 0.9118 |

## Observed templates

| # | answers | masked text |
|---|---|---|
| T1 | 31 | `the recon break on that book traces to an unsettled trade awaiting confirmation.` |
| T2 | 1 | `as an ai model i do not have access to your firm's p&l systems.` |
| T3 | 1 | `i cannot access the ledger data needed to answer this.` |
| T4 | 1 | `the break is <num>against a tolerance of <num>, driven by <num>unmatched tickets.` |

## Open decisions

- Slot extraction: which fields does `handle` pull from the prompt?
- Classifier input: what does `context` need to carry to pick the template?
- Error handling: what does `handle` do when no template fits?
