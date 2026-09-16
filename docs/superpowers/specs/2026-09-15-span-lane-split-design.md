# Span lane split: user asks vs LLM/MCP analysis

## Problem

Prompt→skill (Skill gaps / Promote to skill) mixes in MCP tool payloads and
LLM analysis blobs because `build_clusters` runs on every in-scope span.
Those belong on Make deterministic (skill→deterministic), not promote-to-skill.

Phoenix Sessions UI shows **Turns = Traces**: one `agent_request` root per
user prompt. Nested thinking/tool/LLM spans are not separate asks.

## Rule

| Lane | Span sources |
| --- | --- |
| **Prompt → skill** | **One ask per turn/trace**: turn-root span (`agent_request` / CHAIN/AGENT, else earliest LLM with input) whose extracted text is skill-shaped |
| **Skill → deterministic** | `TOOL` / `RETRIEVER`, deterministic-shaped text (MCP/SQL/params), and non-root LLM analysis blobs |

## Design

1. `turns.turn_root_spans` collapses each `trace_id` to the Phoenix turn root
   (`parent_id is None`, else `agent_request` / CHAIN).
2. Live scrape uses SpanQuery `parent_id is None` plus `sessions.get_session_turns`
   so Rung 1 sees the same Input the UI shows even when the full-span page truncates.
3. `filter_user_ask_spans` clusters **turn roots only** (skill-shaped).
4. `filter_deterministic_source_spans` uses in-turn TOOL/MCP/LLM children and
   **excludes turn roots**.
5. `turn_latency` rolls up thinking vs tool/query ms per turn for WIP stats and
   run notes (why a turn took 20 minutes).
6. In `run_capability_analysis`:
   - Cluster **user-ask** (turn) spans → skill match, coverage, Rung 1
   - Cluster **deterministic-source** spans → Rung 2
7. When scoring Rung 2, expand cluster members to **same-trace** spans so TOOL
   clusters still see LLM outputs for determinism signals.

## Non-goals

- Changing OpenInference span kind taxonomy
- Moving the Skill Content Diff UI into the deterministic board
