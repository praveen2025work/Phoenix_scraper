# Classical + semantic matching — implementation plan

> **For agentic workers:** Implement task-by-task. Checkboxes track progress.

**Goal:** Ship classical IR upgrades + optional local semantic assist with Setup UI toggle.

**Architecture:** Enrich `text_similarity` / new `text_normalize` + `semantic_match` modules; extend `skills_mapper.score_match` and `match_clusters(..., match_mode=)`; pass mode via JobRequest → jobs → capability_run; Setup select control.

**Tech Stack:** rank-bm25, scikit-learn, datasketch; optional sentence-transformers + faiss-cpu.

## Tasks

- [ ] T1: Design doc (done) + deps in pyproject
- [ ] T2: text_normalize (stem + synonyms) + FOBO synonym YAML
- [ ] T3: Upgrade text_similarity (BM25 + n-gram TF-IDF) + near_dup
- [ ] T4: Optional semantic_match module with lazy load + fallback
- [ ] T5: skills_mapper ensemble + match_mode method labels
- [ ] T6: Settings + JobRequest + jobs/capability_run wiring
- [ ] T7: Frontend Setup toggle + enqueue body
- [ ] T8: Tests + docs + commit/push
