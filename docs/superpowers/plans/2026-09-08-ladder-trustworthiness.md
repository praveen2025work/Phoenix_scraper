# Ladder Trustworthiness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the three gaps that make the ladder *look* finished but not be
trustworthy end-to-end: (1) a scoped `pheonix run` now runs the CODE validators
over its in-scope spans, so the SPA's quality panels reflect that capability;
(2) `promote` for a Rung-2 candidate writes a `test_<name>.py` with the **real**
observed `(prompt → answer)` pairs instead of `(prompt, prompt)` placeholders;
(3) `window_days: 0` (or negative) in a hand-edited `capability.yaml` fails
loudly instead of silently coercing to 30.

**Architecture:** (1) `run_capability_analysis` gains an
`store.upsert_evaluations(evaluate_spans(in_scope, ...))` step — idempotent, so
overlapping capabilities just rewrite the same rows; the global
`replace_local_evaluations` (legacy `pheonix analyze`) is untouched (spec §10.2
step 6). (2) `artifacts` gets `_member_pairs()` — the latest run's
`capability_cluster_members` for the candidate's cluster → those spans'
`(input_text, output_text)` where the output is non-empty; `promote_candidate`
uses it, falling back to the prompt-only placeholder when there are none.
(3) `capability.load_capability` raises `ValueError` on a non-positive
`window_days`.

**Tech Stack:** Python 3.11+, pandas, pydantic v2, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
§10.2 step 6 ("CODE checks over in-scope spans … v1: evaluate the union, it is
idempotent"), §8.4 ("`test_<name>.py`: parametrize over the real observed
`(input_text, output_text)` pairs … a green-bar target"), and Phase A review
item #22 (`window_days: 0`).

## Global Constraints

- Backend suite at **764**; nothing regresses. `uv run ruff check src tests &&
  uv run pytest -q` — exit 0.
- **All functions return NEW objects.** Type hints on every signature.
- **TDD:** failing test first, watch it fail, implement.
- Commit `<type>: <description>`, one per task. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```

---

## Task 1: Scoped evaluation in `run_capability_analysis`

**Files:** `src/phoenix_scraper/capability_run.py`, `tests/test_capability_run.py`.

**Interfaces:**
- Consumes: `evaluations.evaluate_spans(spans_df, settings, now=None) ->
  list[SpanEvaluation]`; `Store.upsert_evaluations(evaluations) -> int`;
  `settings.evaluate_on_analyze` (existing, default True).
- Behaviour: after `in_scope` is priced and before clustering-derived work is
  recorded, if `evaluate_on_analyze` and `in_scope` is non-empty,
  `store.upsert_evaluations(evaluate_spans(in_scope, settings, now=started_at))`.
  Idempotent (`INSERT OR REPLACE` on `(span_id, name, source)`), so a second run
  — or another capability whose window overlaps — just rewrites the same rows.
  A `"validated N in-scope spans"` note is NOT added (informational noise);
  failures in `evaluate_spans` must not abort the run (wrap, log, add a
  `"validation skipped: <exc>"` note, do not force `partial`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability_run.py` (inside `TestRunCapabilityAnalysis`):
```python
    def test_run_evaluates_in_scope_spans(self, seeded_store, fobo_capability) -> None:
        from phoenix_scraper.models import QueryFilters
        settings, cap = fobo_capability
        assert seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon")).empty
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        evals = seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon"))
        assert not evals.empty
        assert set(evals["source"]) == {"local"}

    def test_evaluation_is_idempotent_across_two_runs(self, seeded_store, fobo_capability) -> None:
        from phoenix_scraper.models import QueryFilters
        settings, cap = fobo_capability
        run_capability_analysis(seeded_store, settings, cap, now=NOW - timedelta(days=1))
        n1 = len(seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon")))
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        n2 = len(seeded_store.evaluations_frame(QueryFilters(workflow_stage="fobo_recon")))
        assert n1 == n2  # re-run rewrites the same rows, does not stack
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_run.py -q -k "evaluates_in_scope or idempotent"`
Expected: FAIL — `evaluations_frame(...)` is empty after a run.

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/capability_run.py`:
- add `from .evaluations import evaluate_spans` to the imports (alphabetical —
  after `.costs`);
- after the pricing block (the `if not in_scope.empty:` that re-reads
  `in_scope`) and before `clusters = build_clusters(...)`, insert:
```python
    if settings.evaluate_on_analyze and not in_scope.empty:
        try:
            store.upsert_evaluations(evaluate_spans(in_scope, settings, now=started_at))
        except Exception as exc:  # noqa: BLE001 — a broken checker must not abort the run
            logger.warning("scoped evaluation failed for %s: %s", capability.id, exc)
            run_notes.append(f"validation skipped: {exc}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_run.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (764 → 766). `tests/test_ladder_api.py` /
`test_scoped_analytics_api.py` still pass (the quality routes now return rows
for a run capability — the assertions there don't require empty).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/capability_run.py tests/test_capability_run.py
git commit -m "feat: pheonix run evaluates its in-scope spans (idempotent upsert)"
```

---

## Task 2: Real `(prompt, answer)` pairs in the Rung-2 promote artifact

**Files:** `src/phoenix_scraper/artifacts.py`, `tests/test_artifacts.py`.

**Interfaces:**
- Produces: `artifacts._member_pairs(store: Store, capability: Capability,
  candidate: Candidate) -> list[tuple[str, str]]` — the latest recorded run's
  `capability_cluster_members` for `candidate.cluster_id`, joined to those
  spans' `input_text` / `output_text`; keeps rows where **both** are non-empty,
  de-dupes, caps at 20. Empty list when there is no recorded run or no answer
  spans.
- `promote_candidate` (rung `"deterministic"` branch): `pairs =
  _member_pairs(...) or [(p, p) for p in prompts[:20]]`. The `render_rung2_stub`
  call and the fallback are otherwise unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_artifacts.py` (`TestRung2Artifacts`):
```python
    def test_promote_deterministic_uses_real_prompt_answer_pairs(
        self, seeded_store, tmp_path, settings
    ) -> None:
        from datetime import timedelta as _td

        from phoenix_scraper.capability_run import run_capability_analysis
        from phoenix_scraper.models import SpanRecord
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "fobo", cap_filter=CapabilityFilter(workflow_stage="fobo_recon")
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        base = datetime(2026, 7, 20, 9, tzinfo=UTC)
        seeded_store.upsert_spans([
            SpanRecord(
                span_id=f"det-{i:03d}", trace_id=f"det-t{i}", session_id=f"det-s{i}",
                project="pnl-agent", span_kind="LLM", start_time=base + _td(minutes=i),
                workflow_stage="fobo_recon", asset_class="fx", user_id=f"analyst-{i % 4}",
                input_text=f"why is there a recon break of {100 + i}k on EURUSD",
                output_text="The FX break is caused by an unsettled trade; post an adjustment.",
            )
            for i in range(14)
        ])
        run_capability_analysis(seeded_store, s, cap, now=datetime(2026, 7, 21, 12, tzinfo=UTC))
        cid = seeded_store.candidates_frame("fobo", rung="deterministic").iloc[0]["candidate_id"]
        cand = seeded_store.get_candidate(cid).model_copy(update={"status": "accepted"})
        seeded_store.upsert_candidate(cand)

        result = artifacts.promote_candidate(seeded_store, cap, cand, now=TS, actor="a", settings=s)
        test_file = next(b for p, b in result.contents if "/test_" in p)
        assert "The FX break is caused by an unsettled trade" in test_file  # a real answer, not a prompt echo
        assert "why is there a recon break of" in test_file                 # a real prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_artifacts.py -q -k real_prompt_answer`
Expected: FAIL — the generated `test_` file's `CASES` are `(prompt, prompt)`, so
the answer string is absent.

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/artifacts.py`, add near `_member_prompts`:
```python
def _member_pairs(
    store: Store, capability: Capability, candidate: Candidate
) -> list[tuple[str, str]]:
    """Real (input_text, output_text) pairs for this candidate's cluster, from the
    latest recorded run's member span ids."""
    run_id = store.previous_capability_run_id(capability.id)
    if run_id is None:
        return []
    members = store.capability_cluster_members_frame(capability.id, run_id)
    span_ids = set(
        members.loc[members["cluster_id"] == candidate.cluster_id, "span_id"]
    )
    if not span_ids:
        return []
    f = capability.filter
    frame = store.spans_frame(QueryFilters(
        project=f.project, workflow_stage=f.workflow_stage, asset_class=f.asset_class,
        model_name=f.model_name, search=f.search, limit=5000,
    ))
    if frame.empty or "span_id" not in frame.columns:
        return []
    rows = frame[frame["span_id"].isin(span_ids)]
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows.to_dict("records"):
        inp = str(row.get("input_text") or "").strip()
        out = str(row.get("output_text") or "").strip()
        if inp and out and (inp, out) not in seen:
            seen.add((inp, out))
            pairs.append((inp, out))
    return pairs[:_MEMBER_PROMPT_LIMIT * 2]
```
In `promote_candidate`, the `rung == "deterministic"` branch — change:
```python
        files = render_rung2_stub(
            candidate, latest_observation_signals=obs_signals,
            pairs=[(p, p) for p in prompts[:20]],
        )
```
to:
```python
        pairs = _member_pairs(store, capability, candidate) or [(p, p) for p in prompts[:20]]
        files = render_rung2_stub(
            candidate, latest_observation_signals=obs_signals, pairs=pairs,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_artifacts.py -q`
Expected: PASS (the existing `test_promote_deterministic_writes_three_files`
still passes — it has one observation and its candidate's cluster has no members
recorded, so `_member_pairs` returns `[]` and the placeholder fallback applies).

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (766 → 767).

- [ ] **Step 6: Update the plan/docs note**

In `docs/superpowers/plans/2026-09-08-capability-ladder-phase-d.md`, the Task 6
"Note on `pairs`" paragraph — append: *"(Resolved 2026-09-08:
`artifacts._member_pairs` threads the real observed pairs; the `(prompt, prompt)`
fallback only fires when a cluster has no recorded members.)"* — a one-line
amendment, keep it factual.

- [ ] **Step 7: Commit**

```bash
git add src/phoenix_scraper/artifacts.py tests/test_artifacts.py \
  docs/superpowers/plans/2026-09-08-capability-ladder-phase-d.md
git commit -m "feat: Rung-2 promote writes real (prompt, answer) test cases"
```

---

## Task 3: `window_days` must be positive

**Files:** `src/phoenix_scraper/capability.py`, `tests/test_capability.py`.

**Interfaces:**
- `capability.load_capability` raises `ValueError` when `window_days` parses to
  `<= 0`. A blank / absent value still defaults to `30` (unchanged).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability.py` (the load-tests class — match the existing
`self._write` helper):
```python
    def test_window_days_zero_is_rejected(self, tmp_path: Path) -> None:
        self._write(tmp_path, "z", "id: z\nname: Z\nwindow_days: 0\n")
        with pytest.raises(ValueError, match="window_days"):
            cap_mod.load_capability(tmp_path, "z")

    def test_window_days_negative_is_rejected(self, tmp_path: Path) -> None:
        self._write(tmp_path, "n", "id: n\nname: N\nwindow_days: -5\n")
        with pytest.raises(ValueError, match="window_days"):
            cap_mod.load_capability(tmp_path, "n")
```
(`pytest` is already imported in the test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability.py -q -k "window_days_zero or window_days_negative"`
Expected: FAIL — `0` coerces to `30`, no error; `-5` builds a model that
`Field(gt=0)` rejects with a `pydantic.ValidationError` (not a `ValueError`).

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/capability.py`, `load_capability`, replace:
```python
        window_days=int(raw.get("window_days") or 30),
```
with a computed local above the `return Capability(...)`:
```python
    raw_window = raw.get("window_days")
    window_days = 30 if raw_window is None or str(raw_window).strip() == "" else int(raw_window)
    if window_days <= 0:
        raise ValueError(f"{path}: window_days must be a positive integer, got {window_days}")
```
and use `window_days=window_days,` in the constructor.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability.py -q`
Expected: PASS — including `test_load_minimal_fills_defaults` (absent → 30) and
the blank-value test (`window_days:` → 30).

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (767 → 769).

- [ ] **Step 6: Commit + memory note**

```bash
git add src/phoenix_scraper/capability.py tests/test_capability.py
git commit -m "fix: capability.yaml window_days must be positive (was silently -> 30)"
```

---

## Self-Review

- §10.2 step 6 → Task 1. `upsert_evaluations` (not `replace_local_evaluations`)
  keeps the write idempotent and non-destructive to the global set, exactly as
  the spec's v1 note prescribes. The scoped run does NOT touch
  `store.replace_analysis` (that stays a `pipeline.run_analysis` concern).
- §8.4 "green-bar target" → Task 2. `_member_pairs` reads the **latest run's**
  members — the one `record_capability_run` just wrote — so on the same run that
  produced the candidate the pairs are present. The `(prompt, prompt)` fallback
  survives for the degenerate case (no members / no answer spans) so the file
  always renders.
- Phase A #22 → Task 3. Blank vs absent vs 0: absent (`None`) → 30, blank string
  → 30 (matches `test_capability.py:164`), `0` / negative → `ValueError`.
- Type consistency: `_member_pairs(store, capability, candidate) ->
  list[tuple[str, str]]` ↔ `render_rung2_stub(..., pairs=...)` (already
  `list[tuple[str, str]]`). `evaluate_spans(in_scope, settings, now=started_at)`
  ↔ its signature `(spans_df, settings, now=None)`. ✓
- Ambiguity: a capability with a 0-span in-scope window skips evaluation
  (`not in_scope.empty` guard) — no rows written, no note, `status` unaffected.
