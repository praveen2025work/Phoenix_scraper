# Span lane split: user asks vs LLM/MCP analysis

## Problem

Prompt→skill (Skill gaps / Promote to skill) mixes in MCP tool payloads and
LLM analysis blobs because `build_clusters` runs on every in-scope span.
Those belong on Make deterministic (skill→deterministic), not promote-to-skill.

## Rule

| Lane | Span sources |
| --- | --- |
| **Prompt → skill** | User asks only: `span_kind=LLM` whose extracted text is skill-shaped |
| **Skill → deterministic** | `TOOL` / `RETRIEVER`, deterministic-shaped text (MCP/SQL/params), and LLM spans that are not clean user asks |

## Design

1. Add `filter_user_ask_spans` / `filter_deterministic_source_spans` in
   `prompt_shape.py`.
2. In `run_capability_analysis`:
   - Cluster **user-ask** spans → skill match, coverage, Rung 1, run snapshot
   - Cluster **deterministic-source** spans → Rung 2
3. When scoring Rung 2, expand cluster members to **same-trace** spans so TOOL
   clusters still see LLM outputs for determinism signals.
4. Build suggested skill updates from skill-shaped uncovered asks only
   (filter before `suggested_updates`).

## Non-goals

- Changing OpenInference span kind taxonomy
- Moving the Skill Content Diff UI into the deterministic board
