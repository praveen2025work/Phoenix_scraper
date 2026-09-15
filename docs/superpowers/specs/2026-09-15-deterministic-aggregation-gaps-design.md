# Deterministic gaps: offload LLM aggregation

## Problem

Skill→deterministic (Rung 2) today scores answer stability only. It does not ask
whether the **LLM is doing aggregation** (sums, counts, rollups, rankings) that
should live outside the model.

Aggregation in the LLM costs tokens and latency. The deterministic layer should
either:

1. **Precompute** the aggregate at session start and inject it into context, or
2. Expose an **MCP / SQL** call that returns the already-aggregated result

so the LLM narrates or decides — it does not recompute.

## Goal

When identifying Make-deterministic gaps, flag traces where aggregation happens
**in the LLM** and recommend offloading it.

## Detection (lexical, no LLM judge)

On each cluster’s same-trace member spans:

| Signal | Meaning |
| --- | --- |
| `llm_output_aggregates` | LLM `output_text` has aggregation language + figures |
| `llm_input_has_row_data` | LLM `input_text` looks like row-level / SELECT-without-GROUP-BY data |
| `tool_rows_llm_rollup` | TOOL returned a large/tabular payload; LLM answer is a shorter rollup |
| `no_agg_tool_on_trace` | Aggregation language present, but no TOOL/SQL with SUM/GROUP BY/COUNT on the trace |

`aggregation_offload_score` ∈ [0, 1] blends these. Gap when score ≥ **0.55** and
enough answer spans for a soft floor.

**Not a gap:** TOOL/SQL already performs `GROUP BY` / `SUM` / `COUNT` and the LLM
only narrates — aggregation is already deterministic.

## Ladder wiring

- Score **deterministic-lane** clusters as today.
- Also score **prompt→skill** clusters whose traces show `aggregation_in_llm`.
- Candidate subtype `offload_aggregation` when that is the primary reason.
- Creation / evidence bar can be met via classic determinism **or** strong
  aggregation-offload evidence.
- Deterministic draft `.md` lists recommended action:
  `precompute_session` or `mcp_aggregate`.

## Non-goals

- Generating the SQL/MCP implementation automatically
- Changing Rung 1 promote-to-skill matching
