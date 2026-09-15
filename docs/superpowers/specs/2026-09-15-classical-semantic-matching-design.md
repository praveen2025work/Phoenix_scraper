# Classical + optional local-semantic skill matching

**Status:** Approved 2026-09-15  
**Constraint:** No generative LLM, no cloud embedding APIs.

## Goal

Raise skill↔cluster match quality with classical IR, and optionally local MiniLM
embeddings, with an on-screen matcher-mode toggle.

## Modes

| Mode | Value | Behavior |
| --- | --- | --- |
| Classical only (default) | `classical` | keyword + rapidfuzz + BM25 + n-gram TF-IDF + stem/synonym expand + MinHash near-dup collapse |
| Classical + semantic | `semantic` | classical score blended with local MiniLM cosine; falls back to classical if model unavailable |

## Pipeline

1. **Normalize** — tokenize, Porter-like stem, FOBO synonym expand (`config/fobo_synonyms.yaml`).
2. **Near-dup collapse** — MinHash/LSH on cluster representatives before matching (optional pass).
3. **Score** (classical):  
   `0.20 keyword + 0.25 fuzzy + 0.30 bm25 + 0.25 char/word n-gram TF-IDF`  
   (weights calibrated for short desk prompts).
4. **Semantic assist** (if mode=`semantic`):  
   `final = 0.70 * classical + 0.30 * embedding_cosine` (clipped to [0,1]).
5. Persist `method` on each `SkillMatch` reflecting active signals.

## UI

Setup → **Matcher mode** radio/select:
- Classical only  
- Classical + semantic (local)

Value sent on `POST .../jobs` as `match_mode`. Shown on Running/Results via job/run metadata when available.

## Config

- `PHEONIX_MATCH_MODE` default (`classical`|`semantic`)
- `PHEONIX_SEMANTIC_MODEL` default `sentence-transformers/all-MiniLM-L6-v2`
- Per-job body overrides settings default

## Dependencies

**Core:** `rank-bm25`, `scikit-learn`, `datasketch`  
**Optional extra `semantic`:** `sentence-transformers`, `faiss-cpu`

## Fallback

If semantic requested but extras missing or model load fails → classical + job warning message.

## Out of scope

Generative rewrite, LLM-as-judge, cloud embeddings, changing ladder thresholds.
