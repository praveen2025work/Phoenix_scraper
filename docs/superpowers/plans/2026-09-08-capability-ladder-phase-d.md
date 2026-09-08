# Capability Promotion Ladder — Phase D (Rung 2: lexical determinism) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score how **deterministic** each eligible in-scope cluster's answers
are (a lexical, no-LLM signal), persist `<cap>:d:<cluster_id>` candidates with an
evidence trend and the §10.1 machine (plus the `insufficient_data` holding
state), and write a deterministic `deterministic/<name>.{py,md}` + red
`test_<name>.py` stub on promote.

**Architecture:** `normalize.mask_volatile` is extracted so `prompt_signature`
and answer-masking share one masker. New pure module `determinism.py` computes
four sub-signals (`template_concentration`, `route_invariance`,
`output_self_similarity`, `slot_stability`), blends them into a
`determinism_score`, and gates on `n_answer_spans`. `ladder.detect_rung2` turns a
run's clusters + in-scope frame into `Rung2Signal`s; `ladder.next_status` gains
an `eligible` flag for the `insufficient_data` transitions;
`ladder_run.update_rung2` persists them, wired into
`run_capability_analysis` right after `update_rung1`. `artifacts` gains the
Rung-2 stub renderer and a `rung="deterministic"` branch in `promote_candidate`.

**Tech Stack:** Python 3.11+, pydantic v2 (frozen), pandas, rapidfuzz, Typer,
SQLite, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
— implements §8.4 (Rung-2 artifact), §9.2 (Rung-2 signal), §10.1 rows for
`insufficient_data`, §10.2 step 8, and the Phase D row of §13. API routes (§11)
are Phase E; the SPA (§12) is Phase F.

## Global Constraints

- Python **>= 3.11**. New files under **400 lines** (`determinism.py`); the
  additions to `ladder.py` / `ladder_run.py` / `artifacts.py` / `normalize.py` /
  `cli.py` are judged on what this phase adds.
- **All functions return NEW objects.** State transitions return a
  `LadderTransition`.
- **Type hints on every signature.** Frozen models subclass `_Frozen`.
- **TDD:** failing test first, watch it fail, implement.
- Run a module's tests: `uv run pytest tests/test_<module>.py -q`. Whole suite:
  `uv run pytest -q` — **exit 0 is the pass signal; the summary line is
  suppressed, trust the exit code.** Suite is at **702** after Phase C; nothing
  that passes may regress.
- Lint: `uv run ruff check src tests` (`E, F, I, UP, B`; line length 100).
- **No network / no live Phoenix in tests.**
- Commit `<type>: <description>`, one per task. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```
- Package `phoenix_scraper`; CLI `pheonix`; env prefix `PHEONIX_`.
- **Rung-2 `candidate_id`** = `f"{capability_id}:d:{cluster_id}"` (§7.2).
- **Answer span** = a member span with `span_kind == "LLM"` AND non-empty
  `output_text`. **`n_answer_spans`** = the count of those among a cluster's
  members.
- Phase C shipped: `candidates` / `candidate_observations` / `candidate_decisions`
  tables + Store methods; `ladder.py` (`resolve_thresholds`, `detect_rung1`,
  `LadderThresholds`, `Rung1Signal`, `readiness_met`, `is_material_change`,
  `next_status`, `advance_unobserved`, `LadderTransition`); `ladder_run.update_rung1`
  wired into `run_capability_analysis`; `artifacts.py`
  (`render_new_skill_md`, `render_strengthen_block`, `promote_candidate`,
  `slugify`, `dedupe_path`, `_member_prompts`, `PromoteResult`);
  `pheonix candidates | decide | promote`.

## Threshold defaults (§14 — copy verbatim, Task 4)

| Field | Env | Default |
|---|---|---|
| `rung2_min_answer_spans` | `PHEONIX_RUNG2_MIN_ANSWER_SPANS` | `10` |
| `rung2_determinism_score` | `PHEONIX_RUNG2_DETERMINISM_SCORE` | `0.8` |
| `rung2_sustained_runs` | `PHEONIX_RUNG2_SUSTAINED_RUNS` | `3` |

Per-capability `capability.thresholds` overrides `rung2_min_answer_spans`,
`rung2_determinism_score`, `rung2_sustained_runs` by bare name.

**Blend weights (§9.2, fixed):** `template_concentration 0.4`,
`slot_stability 0.3`, `output_self_similarity 0.2`, `route_invariance 0.1`.
`route_invariance` is **N/A** (dropped from the blend, weights renormalise) when
no member trace has a `TOOL` / `RETRIEVER` / `AGENT` / `CHAIN` span.

**Rung-2 creation floor:** first run `determinism_score >= 0.5`. Below that, no
`candidates` row.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/normalize.py` | modify | rename the masking body to `mask_volatile`; `normalize_prompt` becomes a thin alias |
| `src/phoenix_scraper/determinism.py` | **create** | `DeterminismSignals`; `template_concentration`; `route_invariance`; `output_self_similarity`; `slot_stability`; `blend_determinism`; `score_cluster` -> `Rung2Signal` |
| `src/phoenix_scraper/config.py` | modify | 3 `rung2_*` `Settings` fields |
| `src/phoenix_scraper/ladder.py` | modify | extend `LadderThresholds` + `resolve_thresholds` with `rung2_*`; `Rung2Signal`; `detect_rung2`; `next_status(..., eligible: bool = True)` + `insufficient_data` transitions |
| `src/phoenix_scraper/ladder_run.py` | modify | `update_rung2(...)` (parallel to `update_rung1`); shared `_advance_unobserved` gains a `rung` arg |
| `src/phoenix_scraper/capability_run.py` | modify | call `detect_rung2` + `update_rung2` after `update_rung1`; set `run.n_rung2_candidates`; thread the "N skipped" note |
| `src/phoenix_scraper/artifacts.py` | modify | `render_rung2_stub(candidate, *, cluster_signals, pairs) -> list[(filename, body)]`; `promote_candidate` `rung="deterministic"` branch |
| `src/phoenix_scraper/cli.py` | modify | `pheonix candidate <cid>` — one candidate's detail (evidence trend, Rung-2 signals + templates, decision log) |
| `tests/test_normalize.py` | modify | `mask_volatile` is the canonical name |
| `tests/test_determinism.py` | **create** | Tasks 2–3 |
| `tests/test_ladder.py` | modify | Task 4 — `detect_rung2`, `insufficient_data` transitions |
| `tests/test_ladder_run.py` | modify | Task 5 — `update_rung2` |
| `tests/test_capability_run.py` | modify | Task 5 — Rung-2 candidates from a run |
| `tests/test_artifacts.py` | modify | Task 6 — Rung-2 stub + promote |
| `tests/test_candidate_cli.py` | modify | Task 7 — `pheonix candidate` |
| `CONTRACTS.md` / `README.md` | modify | Task 8 |

**Deferred:** HTTP routes / `?capability=` params (Phase E); the SPA (Phase F);
retiring `dashboard.html` (Phase G). A semantic (LLM-judge) determinism confirmer
is explicitly out of v1 (§16.2) — the `signals` dict + blend is the seam.

---

## Task 1: `normalize.mask_volatile` — the shared masker

**Files:**
- Modify: `src/phoenix_scraper/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize.mask_volatile(text: str) -> str` — casefold + collapse
  whitespace + mask `<num> <date> <ccy> <id> <book> <desk>` (exactly today's
  `normalize_prompt` behaviour). `normalize_prompt` stays as a name that calls
  `mask_volatile` so every existing import keeps working.

- [x] **Step 1: Write the failing test**

Append to `tests/test_normalize.py`:

```python
def test_mask_volatile_is_the_canonical_masker() -> None:
    from phoenix_scraper.normalize import mask_volatile, normalize_prompt
    text = "Why is there a recon break of 100k on EQ_DELTA1_NY as of 2026-07-29?"
    assert mask_volatile(text) == normalize_prompt(text)
    masked = mask_volatile(text)
    assert "<num>" in masked and "<book>" in masked and "<date>" in masked
    assert "100k" not in masked


def test_mask_volatile_masks_output_style_text() -> None:
    from phoenix_scraper.normalize import mask_volatile
    a = mask_volatile("The EUR break of 250k on BUND_FFT is an unsettled trade.")
    b = mask_volatile("The USD break of 1.2m on GILT_LDN is an unsettled trade.")
    assert a == b  # same template once the volatile bits are masked
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_normalize.py -q -k mask_volatile`
Expected: FAIL — `ImportError: cannot import name 'mask_volatile'`.

- [x] **Step 3: Extract**

In `src/phoenix_scraper/normalize.py`, rename the current `normalize_prompt`
function body to `mask_volatile`, then re-add `normalize_prompt` as an alias:

```python
def mask_volatile(text: str) -> str:
    """Casefold, collapse whitespace, and mask volatile tokens with placeholders.

    The one masker shared by prompt_signature (input) and Rung-2's answer
    masking (output) — same token classes, lexical only.
    """
    result = _BOOK_PATTERN.sub("<book>", text)
    result = result.casefold()
    result = _DESK_PATTERN.sub("<desk> desk", result)
    for pattern in _DATE_PATTERNS:
        result = pattern.sub("<date>", result)
    result = _ID_PATTERN.sub("<id>", result)
    result = _CCY_PAIR_PATTERN.sub("<ccy>", result)
    result = _CCY_SINGLE_PATTERN.sub("<ccy>", result)
    result = _LEADING_SYMBOL_NUMBER.sub("<num>", result)
    result = _NUMBER_PATTERN.sub("<num>", result)
    return _WHITESPACE.sub(" ", result).strip()


def normalize_prompt(text: str) -> str:
    """Backwards-compatible alias for mask_volatile."""
    return mask_volatile(text)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_normalize.py -q`
Expected: PASS (the whole file — `normalize_prompt` behaviour is unchanged).

- [x] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (702 → 704).

- [x] **Step 6: Commit**

```bash
git add src/phoenix_scraper/normalize.py tests/test_normalize.py
git commit -m "refactor: extract normalize.mask_volatile (shared input/output masker)"
```

---

## Task 2: `determinism.py` — the four sub-signals (pure)

**Files:**
- Create: `src/phoenix_scraper/determinism.py`
- Test: `tests/test_determinism.py` (create)

**Interfaces:**
- Consumes: `normalize.mask_volatile`; `rapidfuzz.fuzz.token_set_ratio`;
  `insights_llm._flow_signature`.
- Produces:
  - `_ROUTE_KINDS = frozenset({"TOOL", "RETRIEVER", "AGENT", "CHAIN"})`
  - `DeterminismSignals(_Frozen)` — `template_concentration: float`,
    `route_invariance: float | None`, `output_self_similarity: float`,
    `slot_stability: float`, `n_templates: int`, `n_answer_spans: int`,
    `route_applicable: bool`.
  - `build_templates(answers: list[str], *, fuzz_threshold: int) -> list[tuple[str,
    int]]` — `(masked_representative, count)` per template, largest first,
    greedy-merged by `token_set_ratio >= fuzz_threshold`.
  - `template_concentration(answers: list[str], *, fuzz_threshold: int) ->
    tuple[float, int]` — `(concentration, k)` where `k` = distinct templates to
    cover >= 90% of answers; `concentration = max(0, 1 - (k - 1) * 0.25)`.
  - `route_invariance(flows: list[str]) -> float` — `modal_count / len(flows)`;
    `0.0` for an empty list (caller decides N/A via `route_applicable`).
  - `output_self_similarity(answers: list[str], *, sample: int = 200, max_pairs:
    int = 5000) -> float` — mean pairwise `token_set_ratio / 100` over masked
    answers.
  - `slot_stability(pairs: list[tuple[str, str]], templates: list[tuple[str,
    int]], *, fuzz_threshold: int) -> float` — `pairs` are `(input_text,
    output_text)`; group by masked input signature; per group the modal template
    share; frequency-weighted mean.

- [x] **Step 1: Write the failing test**

Create `tests/test_determinism.py`:

```python
"""Pure tests for the four Rung-2 sub-signals."""

from phoenix_scraper import determinism as d

FUZZ = 90


class TestTemplates:
    def test_one_template_when_all_answers_match(self) -> None:
        answers = [f"The EUR break of {n}k on BUND is an unsettled trade." for n in range(20)]
        conc, k = d.template_concentration(answers, fuzz_threshold=FUZZ)
        assert k == 1 and conc == 1.0

    def test_two_templates_scores_075(self) -> None:
        a = [f"The EUR break of {n}k on BUND is an unsettled trade." for n in range(16)]
        b = [f"The break of {n}k matches a missing dividend accrual." for n in range(4)]
        conc, k = d.template_concentration(a + b, fuzz_threshold=FUZZ)
        assert k == 1  # 16/20 = 80% < 90% needs the 2nd -> k should be 2
        # (guard: 16/20 is 80%, so k must be 2)

    def test_high_variety_scores_low(self) -> None:
        answers = [f"Completely different answer number {n} about topic {n}." for n in range(20)]
        conc, k = d.template_concentration(answers, fuzz_threshold=FUZZ)
        assert conc < 0.5 and k >= 3


class TestRouteInvariance:
    def test_all_same_flow(self) -> None:
        assert d.route_invariance(["LLM → TOOL → LLM"] * 10) == 1.0

    def test_split_flow(self) -> None:
        flows = ["LLM → TOOL → LLM"] * 7 + ["LLM → TOOL ×2 → LLM"] * 3
        assert d.route_invariance(flows) == 0.7

    def test_empty(self) -> None:
        assert d.route_invariance([]) == 0.0


class TestSelfSimilarity:
    def test_identical_answers(self) -> None:
        assert d.output_self_similarity(["same text here"] * 5) == 1.0

    def test_unrelated_answers(self) -> None:
        assert d.output_self_similarity(
            ["the sky is blue today", "bananas ripen in warm rooms"]
        ) < 0.5

    def test_single_answer_is_perfectly_similar(self) -> None:
        assert d.output_self_similarity(["only one"]) == 1.0


class TestSlotStability:
    def test_stable_when_each_input_shape_maps_to_one_template(self) -> None:
        templates = d.build_templates(
            ["cause is an unsettled trade"] * 6 + ["cause is a missing accrual"] * 6,
            fuzz_threshold=FUZZ,
        )
        pairs = (
            [("why is there a break of 100k on BUND", "cause is an unsettled trade")] * 6
            + [("what caused the 50k adjustment on GILT", "cause is a missing accrual")] * 6
        )
        assert d.slot_stability(pairs, templates, fuzz_threshold=FUZZ) == 1.0

    def test_unstable_when_one_input_shape_splits(self) -> None:
        templates = d.build_templates(
            ["cause A"] * 5 + ["cause B"] * 5, fuzz_threshold=FUZZ
        )
        pairs = (
            [("why is there a break of 100k on BUND", "cause A")] * 5
            + [("why is there a break of 200k on BUND", "cause B")] * 5
        )
        # one masked input signature -> two templates 50/50
        assert d.slot_stability(pairs, templates, fuzz_threshold=FUZZ) == 0.5
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_determinism.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoenix_scraper.determinism'`.

- [x] **Step 3: Create `determinism.py` (sub-signals only)**

Create `src/phoenix_scraper/determinism.py`:

```python
"""Rung 2 of the promotion ladder: how deterministic is this cluster's answer?

Pure and lexical — mask volatile tokens, then measure four things: do the
answers collapse to a few templates (`template_concentration`), does the agent
take the same route every time (`route_invariance`), are the answers similar to
each other (`output_self_similarity`), and does each input phrasing always yield
the same template (`slot_stability`). `score_cluster` blends them and gates on
`n_answer_spans`. No LLM — a low score is a real "keep the model" answer.
"""

from itertools import combinations

from rapidfuzz import fuzz

from .insights_llm import _flow_signature
from .models import _Frozen
from .normalize import mask_volatile

_ROUTE_KINDS = frozenset({"TOOL", "RETRIEVER", "AGENT", "CHAIN"})
_COVER_TARGET = 0.90
_SELF_SIM_SAMPLE = 200
_SELF_SIM_MAX_PAIRS = 5000


class DeterminismSignals(_Frozen):
    template_concentration: float
    route_invariance: float | None
    output_self_similarity: float
    slot_stability: float
    n_templates: int
    n_answer_spans: int
    route_applicable: bool


def build_templates(
    answers: list[str], *, fuzz_threshold: int
) -> list[tuple[str, int]]:
    """(masked representative, count) per merged template, largest first."""
    groups: dict[str, int] = {}
    for answer in answers:
        groups[mask_volatile(answer)] = groups.get(mask_volatile(answer), 0) + 1
    ordered = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
    templates: list[list] = []  # [representative, count]
    for masked, n in ordered:
        for tmpl in templates:
            if fuzz.token_set_ratio(masked, tmpl[0]) >= fuzz_threshold:
                tmpl[1] += n
                break
        else:
            templates.append([masked, n])
    templates.sort(key=lambda t: -t[1])
    return [(t[0], t[1]) for t in templates]


def template_concentration(
    answers: list[str], *, fuzz_threshold: int
) -> tuple[float, int]:
    if not answers:
        return 0.0, 0
    templates = build_templates(answers, fuzz_threshold=fuzz_threshold)
    total = sum(n for _, n in templates)
    covered = 0
    k = 0
    for _, n in templates:
        covered += n
        k += 1
        if covered / total >= _COVER_TARGET:
            break
    return max(0.0, 1.0 - (k - 1) * 0.25), k


def route_invariance(flows: list[str]) -> float:
    if not flows:
        return 0.0
    counts: dict[str, int] = {}
    for flow in flows:
        counts[flow] = counts.get(flow, 0) + 1
    return max(counts.values()) / len(flows)


def output_self_similarity(
    answers: list[str], *, sample: int = _SELF_SIM_SAMPLE, max_pairs: int = _SELF_SIM_MAX_PAIRS
) -> float:
    masked = [mask_volatile(a) for a in answers[:sample]]
    if len(masked) < 2:
        return 1.0
    ratios: list[float] = []
    for a, b in combinations(masked, 2):
        ratios.append(fuzz.token_set_ratio(a, b) / 100.0)
        if len(ratios) >= max_pairs:
            break
    return sum(ratios) / len(ratios) if ratios else 1.0


def _template_of(masked_answer: str, templates: list[tuple[str, int]], fuzz_threshold: int) -> str:
    for rep, _ in templates:
        if fuzz.token_set_ratio(masked_answer, rep) >= fuzz_threshold:
            return rep
    return masked_answer


def slot_stability(
    pairs: list[tuple[str, str]],
    templates: list[tuple[str, int]],
    *,
    fuzz_threshold: int,
) -> float:
    if not pairs:
        return 0.0
    by_input: dict[str, list[str]] = {}
    for prompt, answer in pairs:
        key = mask_volatile(prompt)
        by_input.setdefault(key, []).append(
            _template_of(mask_volatile(answer), templates, fuzz_threshold)
        )
    total = 0
    weighted = 0.0
    for tmpls in by_input.values():
        counts: dict[str, int] = {}
        for t in tmpls:
            counts[t] = counts.get(t, 0) + 1
        modal_share = max(counts.values()) / len(tmpls)
        weighted += modal_share * len(tmpls)
        total += len(tmpls)
    return weighted / total if total else 0.0
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_determinism.py -q`
Expected: PASS. (If `test_two_templates_scores_075`'s `k == 1` assertion is
wrong — 16/20 = 0.80 < 0.90 so the 2nd template IS needed, `k == 2` — fix the
assertion to `k == 2` and drop the stale comment. The test is the spec check;
make it match `_COVER_TARGET`.)

- [x] **Step 5: File length + lint**

Run: `wc -l src/phoenix_scraper/determinism.py && uv run ruff check src/phoenix_scraper/determinism.py tests/test_determinism.py`
Expected: under 400; ruff clean. (`_flow_signature` is a private import from
`insights_llm` — a deliberate reuse, mirroring `artifacts.py` importing
`skill_coverage._yaml_block`.)

- [x] **Step 6: Commit**

```bash
git add src/phoenix_scraper/determinism.py tests/test_determinism.py
git commit -m "feat: determinism.py — the four Rung-2 sub-signals"
```

---

## Task 3: `determinism.score_cluster` — blend + eligibility gate

**Files:**
- Modify: `src/phoenix_scraper/determinism.py`
- Test: `tests/test_determinism.py` (append)

**Interfaces:**
- Consumes: Task 2's sub-signals.
- Produces:
  - `blend_determinism(signals: DeterminismSignals) -> float` — `Σ(wᵢ·sᵢ) /
    Σ(wᵢ)` over available signals (drop `route_invariance` when
    `route_applicable` is False, renormalise).
  - `Rung2Signal(_Frozen)` — `cluster_id: str`, `title: str`, `signature: str`,
    `matched_skill: str | None`, `determinism_score: float`, `n_answer_spans:
    int`, `eligible: bool`, `signals: DeterminismSignals`, `templates:
    tuple[tuple[str, int], ...]`.
  - `score_cluster(cluster_id: str, title: str, signature: str, matched_skill:
    str | None, member_spans: pd.DataFrame, *, min_answer_spans: int,
    fuzz_threshold: int) -> Rung2Signal` — `member_spans` is the cluster's rows
    from the in-scope frame (needs `span_kind`, `output_text`, `input_text`,
    `trace_id`). Answer spans = `span_kind == "LLM"` AND `output_text` non-empty.
    When `n_answer_spans < min_answer_spans`: `eligible = False`,
    `determinism_score = 0.0`, signals still computed on what exists (or zeros).

- [x] **Step 1: Write the failing test**

Append to `tests/test_determinism.py`:

```python
import pandas as pd


def _member_spans(answers, prompts=None, flows_per_trace=None):
    prompts = prompts or ["why is there a break of 100k on BUND"] * len(answers)
    rows = []
    for i, (ans, prm) in enumerate(zip(answers, prompts, strict=False)):
        tid = f"t{i}"
        rows.append(dict(span_id=f"s{i}", trace_id=tid, span_kind="LLM",
                         input_text=prm, output_text=ans, start_time=i))
        for j, kind in enumerate((flows_per_trace or {}).get(tid, [])):
            rows.append(dict(span_id=f"s{i}-{j}", trace_id=tid, span_kind=kind,
                             input_text="", output_text="", start_time=i + 0.1 + j * 0.01))
    return pd.DataFrame(rows)


class TestBlendAndScore:
    def test_blend_drops_route_when_not_applicable(self) -> None:
        sig = d.DeterminismSignals(
            template_concentration=1.0, route_invariance=None,
            output_self_similarity=1.0, slot_stability=1.0,
            n_templates=1, n_answer_spans=12, route_applicable=False,
        )
        assert d.blend_determinism(sig) == 1.0

    def test_blend_weights(self) -> None:
        sig = d.DeterminismSignals(
            template_concentration=1.0, route_invariance=0.0,
            output_self_similarity=1.0, slot_stability=1.0,
            n_templates=1, n_answer_spans=12, route_applicable=True,
        )
        # (0.4*1 + 0.3*1 + 0.2*1 + 0.1*0) / 1.0 == 0.9
        assert round(d.blend_determinism(sig), 4) == 0.9

    def test_score_cluster_high_determinism(self) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        spans = _member_spans(answers)
        sig = d.score_cluster("c1", "t", "s", None, spans,
                              min_answer_spans=10, fuzz_threshold=90)
        assert sig.eligible is True
        assert sig.determinism_score > 0.8
        assert sig.signals.route_applicable is False  # no TOOL spans

    def test_score_cluster_insufficient_data(self) -> None:
        spans = _member_spans([f"answer {n}" for n in range(4)])
        sig = d.score_cluster("c2", "t", "s", None, spans,
                              min_answer_spans=10, fuzz_threshold=90)
        assert sig.eligible is False and sig.determinism_score == 0.0
        assert sig.n_answer_spans == 4

    def test_score_cluster_route_applicable_with_tools(self) -> None:
        answers = [f"The break of {n}k is unsettled." for n in range(12)]
        flows = {f"t{i}": ["TOOL"] for i in range(12)}
        spans = _member_spans(answers, flows_per_trace=flows)
        sig = d.score_cluster("c3", "t", "s", None, spans,
                              min_answer_spans=10, fuzz_threshold=90)
        assert sig.signals.route_applicable is True
        assert sig.signals.route_invariance == 1.0
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_determinism.py -q -k "Blend"`
Expected: FAIL — `AttributeError: module 'phoenix_scraper.determinism' has no attribute 'blend_determinism'`.

- [x] **Step 3: Implement**

Append to `src/phoenix_scraper/determinism.py`. Add `import pandas as pd` to the
imports.

```python
_WEIGHTS = {
    "template_concentration": 0.4,
    "slot_stability": 0.3,
    "output_self_similarity": 0.2,
    "route_invariance": 0.1,
}


class Rung2Signal(_Frozen):
    cluster_id: str
    title: str
    signature: str
    matched_skill: str | None
    determinism_score: float
    n_answer_spans: int
    eligible: bool
    signals: DeterminismSignals
    templates: tuple[tuple[str, int], ...] = ()


def blend_determinism(signals: DeterminismSignals) -> float:
    available = {
        "template_concentration": signals.template_concentration,
        "slot_stability": signals.slot_stability,
        "output_self_similarity": signals.output_self_similarity,
    }
    if signals.route_applicable and signals.route_invariance is not None:
        available["route_invariance"] = signals.route_invariance
    num = sum(_WEIGHTS[k] * v for k, v in available.items())
    den = sum(_WEIGHTS[k] for k in available)
    return round(num / den, 4) if den else 0.0


def _flows_for(member_spans: pd.DataFrame) -> tuple[list[str], bool]:
    if member_spans.empty or "trace_id" not in member_spans.columns:
        return [], False
    flows: list[str] = []
    applicable = False
    for _tid, group in member_spans.groupby("trace_id", sort=False):
        ordered = group.sort_values("start_time")
        kinds = list(ordered["span_kind"].fillna("UNKNOWN"))
        flows.append(_flow_signature(kinds))
        if _ROUTE_KINDS.intersection(kinds):
            applicable = True
    return flows, applicable


def score_cluster(
    cluster_id: str,
    title: str,
    signature: str,
    matched_skill: str | None,
    member_spans: "pd.DataFrame",
    *,
    min_answer_spans: int,
    fuzz_threshold: int,
) -> Rung2Signal:
    answer_rows = member_spans[
        (member_spans["span_kind"] == "LLM")
        & (member_spans["output_text"].fillna("").astype(str).str.strip() != "")
    ] if not member_spans.empty else member_spans
    answers = [str(t) for t in answer_rows["output_text"].tolist()] if not answer_rows.empty else []
    prompts = [str(t) for t in answer_rows["input_text"].fillna("").tolist()] if not answer_rows.empty else []
    n_answer_spans = len(answers)

    templates = build_templates(answers, fuzz_threshold=fuzz_threshold) if answers else []
    conc, k = template_concentration(answers, fuzz_threshold=fuzz_threshold) if answers else (0.0, 0)
    self_sim = output_self_similarity(answers) if answers else 0.0
    slots = slot_stability(
        list(zip(prompts, answers, strict=False)), templates, fuzz_threshold=fuzz_threshold
    ) if answers else 0.0
    flows, route_applicable = _flows_for(member_spans)
    route_inv = route_invariance(flows) if flows else None

    signals = DeterminismSignals(
        template_concentration=round(conc, 4),
        route_invariance=round(route_inv, 4) if route_inv is not None else None,
        output_self_similarity=round(self_sim, 4),
        slot_stability=round(slots, 4),
        n_templates=k,
        n_answer_spans=n_answer_spans,
        route_applicable=route_applicable,
    )
    eligible = n_answer_spans >= min_answer_spans
    score = blend_determinism(signals) if eligible else 0.0
    return Rung2Signal(
        cluster_id=cluster_id,
        title=title,
        signature=signature,
        matched_skill=matched_skill,
        determinism_score=score,
        n_answer_spans=n_answer_spans,
        eligible=eligible,
        signals=signals,
        templates=tuple(templates[:10]),
    )
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_determinism.py -q`
Expected: PASS.

- [x] **Step 5: File length + lint**

Run: `wc -l src/phoenix_scraper/determinism.py && uv run ruff check src/phoenix_scraper/determinism.py tests/test_determinism.py`
Expected: under 400; ruff clean.

- [x] **Step 6: Commit**

```bash
git add src/phoenix_scraper/determinism.py tests/test_determinism.py
git commit -m "feat: determinism.score_cluster — blend + eligibility gate"
```

---

## Task 4: `ladder` — Rung-2 thresholds, `detect_rung2`, `insufficient_data`

**Files:**
- Modify: `src/phoenix_scraper/config.py`
- Modify: `src/phoenix_scraper/ladder.py`
- Test: `tests/test_ladder.py` (append)

**Interfaces:**
- Produces:
  - `Settings`: `rung2_min_answer_spans: int = 10`, `rung2_determinism_score:
    float = 0.8`, `rung2_sustained_runs: int = 3`.
  - `LadderThresholds` gains `rung2_min_answer_spans: int`,
    `rung2_determinism_score: float`, `rung2_sustained_runs: int`,
    `cluster_fuzz_threshold: int`.
  - `detect_rung2(clusters: list[PromptCluster], matches: list[SkillMatch],
    in_scope: pd.DataFrame, *, thresholds: LadderThresholds) ->
    list[determinism.Rung2Signal]` — one signal per cluster, `met_evidence_bar`
    stamped (`eligible AND determinism_score >= rung2_determinism_score`).
  - `next_status(..., eligible: bool = True)` — new keyword. When `eligible` is
    False and the status is `new`/`accumulating` → `insufficient_data`; an
    `insufficient_data` candidate that is eligible again → `accumulating` and
    the normal machine resumes.

- [x] **Step 1: Settings fields**

In `src/phoenix_scraper/config.py`, after the `material_change_users_delta` line:

```python
    rung2_min_answer_spans: int = 10  # LLM member spans with output text to score
    rung2_determinism_score: float = 0.8  # evidence bar
    rung2_sustained_runs: int = 3  # consecutive runs meeting the bar -> ready
```

- [x] **Step 2: Write the failing test**

Append to `tests/test_ladder.py`:

```python
class TestRung2Thresholds:
    def test_rung2_defaults_and_overrides(self) -> None:
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert t.rung2_min_answer_spans == 10 and t.rung2_determinism_score == 0.8
        assert t.rung2_sustained_runs == 3
        assert t.cluster_fuzz_threshold == 90
        t2 = ladder.resolve_thresholds(
            _capability({"rung2_determinism_score": 0.6, "rung2_sustained_runs": 2}),
            _settings(),
        )
        assert t2.rung2_determinism_score == 0.6 and t2.rung2_sustained_runs == 2


class TestDetectRung2:
    def _in_scope(self, cluster_id, answers, prompts=None):
        prompts = prompts or ["why is there a break of 100k on BUND"] * len(answers)
        return pd.DataFrame([
            dict(span_id=f"{cluster_id}-{i}", trace_id=f"{cluster_id}-t{i}",
                 span_kind="LLM", input_text=p, output_text=a, start_time=i)
            for i, (a, p) in enumerate(zip(answers, prompts, strict=False))
        ])

    def test_eligible_deterministic_cluster_signal(self) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        frame = self._in_scope("ddd", answers)
        cluster = _cluster("ddd", count=14)
        cluster = cluster.model_copy(update={"span_ids": tuple(frame["span_id"])})
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung2([cluster], [], frame, thresholds=t)
        assert len(signals) == 1
        assert signals[0].eligible is True
        assert signals[0].met_evidence_bar is True  # score > 0.8

    def test_ineligible_cluster_signal_not_met(self) -> None:
        answers = [f"answer {n}" for n in range(4)]
        frame = self._in_scope("eee", answers)
        cluster = _cluster("eee", count=4).model_copy(update={"span_ids": tuple(frame["span_id"])})
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung2([cluster], [], frame, thresholds=t)
        assert signals[0].eligible is False and signals[0].met_evidence_bar is False


class TestNextStatusRung2:
    def _t(self):
        return ladder.resolve_thresholds(_capability(), _settings())

    def test_ineligible_new_becomes_insufficient_data(self) -> None:
        tr = ladder.next_status(_cand2("new"), _o(False), [_o(False)],
                                run_ordinal=1, capability_run_count=1,
                                thresholds=self._t(), eligible=False)
        assert tr.status == "insufficient_data"

    def test_insufficient_data_resumes_when_eligible(self) -> None:
        tr = ladder.next_status(_cand2("insufficient_data"), _o(True), [_o(True), _o(True)],
                                run_ordinal=3, capability_run_count=3,
                                thresholds=self._t(), eligible=True)
        assert tr.status == "accumulating"

    def test_insufficient_data_stays_when_still_ineligible(self) -> None:
        tr = ladder.next_status(_cand2("insufficient_data"), _o(False), [_o(False)],
                                run_ordinal=3, capability_run_count=3,
                                thresholds=self._t(), eligible=False)
        assert tr.status == "insufficient_data"
```

- [x] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder.py -q -k "Rung2 or insufficient"`
Expected: FAIL — `AttributeError` on `detect_rung2` / `TypeError` on the
`eligible` kwarg.

- [x] **Step 4: Extend `LadderThresholds` + `resolve_thresholds`**

In `src/phoenix_scraper/ladder.py`, add to `LadderThresholds`:
```python
    rung2_min_answer_spans: int
    rung2_determinism_score: float
    rung2_sustained_runs: int
    cluster_fuzz_threshold: int
```
and to `resolve_thresholds`'s `LadderThresholds(...)` call:
```python
        rung2_min_answer_spans=int(
            over.get("rung2_min_answer_spans", settings.rung2_min_answer_spans)
        ),
        rung2_determinism_score=float(
            over.get("rung2_determinism_score", settings.rung2_determinism_score)
        ),
        rung2_sustained_runs=int(
            over.get("rung2_sustained_runs", settings.rung2_sustained_runs)
        ),
        cluster_fuzz_threshold=settings.cluster_fuzz_threshold,
```

- [x] **Step 5: Add `detect_rung2`**

In `ladder.py`, add `from . import determinism` at the top of the file (module
import to avoid a name clash with the `Rung1Signal` etc.), then after
`detect_rung1`:

```python
def detect_rung2(
    clusters: list[PromptCluster],
    matches: list[SkillMatch],
    in_scope: pd.DataFrame,
    *,
    thresholds: LadderThresholds,
) -> list["determinism.Rung2Signal"]:
    """One Rung2Signal per cluster (eligibility + determinism_score + met bar)."""
    match_by_cluster = {m.cluster_id: m.skill_name for m in matches}
    signals: list[determinism.Rung2Signal] = []
    for cluster in clusters:
        members = (
            in_scope[in_scope["span_id"].isin(set(cluster.span_ids))]
            if not in_scope.empty and "span_id" in in_scope.columns
            else in_scope
        )
        sig = determinism.score_cluster(
            cluster.cluster_id,
            cluster.representative.strip()[:200],
            cluster.signature,
            match_by_cluster.get(cluster.cluster_id),
            members,
            min_answer_spans=thresholds.rung2_min_answer_spans,
            fuzz_threshold=thresholds.cluster_fuzz_threshold,
        )
        met = sig.eligible and sig.determinism_score >= thresholds.rung2_determinism_score
        signals.append(sig.model_copy(update={"met_evidence_bar": met}))
    return signals
```

Add `met_evidence_bar: bool = False` to `determinism.Rung2Signal` (Task 3's
model) — update Task 3's model class and re-run `tests/test_determinism.py` to
confirm still green (the default keeps existing tests valid).

- [x] **Step 6: Extend `next_status` with `eligible`**

Change the `next_status` signature to add `eligible: bool = True` (keyword), and
insert the `insufficient_data` handling right after the `_HUMAN_TERMINAL` check
and before `if status == "stale"`:

```python
    if status in _HUMAN_TERMINAL:
        return LadderTransition(status=status)

    if not eligible:
        if status in ("new", "accumulating", "insufficient_data", "stale"):
            return LadderTransition(status="insufficient_data")
        # ready with the answer spans gone falls through to the fade path below
    if status == "insufficient_data":
        status = "accumulating"

    if status == "stale":
        status = "accumulating"
```

- [x] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ladder.py tests/test_determinism.py -q`
Expected: PASS (whole files — Rung-1 `next_status` callers still pass because
`eligible` defaults to True).

- [x] **Step 8: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~706 → ~717).

- [x] **Step 9: Commit**

```bash
git add src/phoenix_scraper/config.py src/phoenix_scraper/ladder.py \
  src/phoenix_scraper/determinism.py tests/test_ladder.py tests/test_determinism.py
git commit -m "feat: ladder Rung-2 thresholds + detect_rung2 + insufficient_data transitions"
```

---

## Task 5: `ladder_run.update_rung2` — persist Rung 2, wired into the run

**Files:**
- Modify: `src/phoenix_scraper/ladder_run.py`
- Modify: `src/phoenix_scraper/capability_run.py`
- Test: `tests/test_ladder_run.py` (append); `tests/test_capability_run.py` (append)

**Interfaces:**
- Produces:
  - `Rung2RunOutcome(_Frozen)` — `n_candidates: int`, `n_ready: int`,
    `n_insufficient: int`, `notes: tuple[str, ...]`, `crossed: tuple[str, ...]`.
  - `update_rung2(store: Store, capability: Capability, *, run_id: str,
    run_ordinal: int, capability_run_count: int, observed_at: datetime, signals:
    list[determinism.Rung2Signal], thresholds: LadderThresholds, history_limit:
    int) -> Rung2RunOutcome` — for each signal: skip if no candidate yet and not
    (`eligible AND determinism_score >= 0.5`) [creation floor]; else write the
    observation (`score = determinism_score`, `signals` = the sub-signals dict +
    `n_answer_spans` + `templates`), upsert the candidate
    (`candidate_id = "<cap>:d:<cluster_id>"`, `rung = "deterministic"`,
    `subtype = ""`), run `next_status(..., eligible=signal.eligible)`, persist,
    prune. Then `_advance_unobserved(..., rung="deterministic")`.
  - `_advance_unobserved` gains `rung: str` (was implicitly `"skill"`).
  - Wiring in `run_capability_analysis`: after `update_rung1`, add
    `detect_rung2` + `update_rung2`; `run.n_rung2_candidates = rung2.n_candidates`;
    `run_notes.extend(rung2.notes)` (a `"Rung 2: N clusters skipped (no output
    text)"` note when `n_insufficient` > 0 — informational, does not force
    `partial`).

- [x] **Step 1: Write the failing test**

Append to `tests/test_ladder_run.py`:

```python
import pandas as pd  # noqa: E402  (if not already imported at top)

from phoenix_scraper import determinism as _det  # noqa: E402
from phoenix_scraper.ladder import detect_rung2  # noqa: E402
from phoenix_scraper.ladder_run import update_rung2  # noqa: E402


def _r2_frame(cluster_id, answers):
    return pd.DataFrame([
        dict(span_id=f"{cluster_id}-{i}", trace_id=f"{cluster_id}-t{i}",
             span_kind="LLM", input_text="why is there a break of 100k on BUND",
             output_text=a, start_time=i)
        for i, a in enumerate(answers)
    ])


def _r2_signals(cluster_id, answers, t):
    from phoenix_scraper.models import PromptCluster
    frame = _r2_frame(cluster_id, answers)
    cluster = PromptCluster(
        cluster_id=cluster_id, signature=f"sig {cluster_id}",
        representative="why is there a break", count=len(answers),
        span_ids=tuple(frame["span_id"]),
    )
    return detect_rung2([cluster], [], frame, thresholds=t)


def _run2(store, cap, t, signals, *, run_id, ordinal, count, at):
    return update_rung2(
        store, cap, run_id=run_id, run_ordinal=ordinal, capability_run_count=count,
        observed_at=at, signals=signals, thresholds=t, history_limit=20,
    )


class TestUpdateRung2:
    def test_deterministic_cluster_creates_candidate(self, tmp_store, t) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        out = _run2(tmp_store, _cap(), t, _r2_signals("ddd", answers, t),
                    run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 1
        c = tmp_store.get_candidate("fobo:d:ddd")
        assert c is not None and c.rung == "deterministic"

    def test_variable_cluster_below_floor_is_not_recorded(self, tmp_store, t) -> None:
        answers = [f"Totally distinct answer number {n} about matter {n}." for n in range(14)]
        out = _run2(tmp_store, _cap(), t, _r2_signals("var", answers, t),
                    run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 0
        assert tmp_store.get_candidate("fobo:d:var") is None

    def test_ineligible_existing_candidate_goes_insufficient_data(self, tmp_store, t) -> None:
        good = [f"The break of {n}k on BUND is unsettled." for n in range(14)]
        _run2(tmp_store, _cap(), t, _r2_signals("ddd", good, t),
              run_id="r1", ordinal=1, count=1, at=TS)
        thin = [f"The break of {n}k on BUND is unsettled." for n in range(4)]
        out = _run2(tmp_store, _cap(), t, _r2_signals("ddd", thin, t),
                    run_id="r2", ordinal=2, count=2, at=TS + timedelta(days=1))
        assert tmp_store.get_candidate("fobo:d:ddd").status == "insufficient_data"
        assert out.n_insufficient == 1

    def test_sustained_reaches_ready(self, tmp_store, t) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        for i in range(1, 4):
            _run2(tmp_store, _cap(), t, _r2_signals("ddd", answers, t),
                  run_id=f"r{i}", ordinal=i, count=i, at=TS + timedelta(days=i))
        assert tmp_store.get_candidate("fobo:d:ddd").status == "ready"
```

Append to `tests/test_capability_run.py` (inside `TestRunCapabilityAnalysis`):

```python
    def test_rung2_candidate_from_a_deterministic_cluster(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        from datetime import timedelta as _td

        from phoenix_scraper.models import SpanRecord
        base = datetime(2026, 7, 20, 9, tzinfo=UTC)
        seeded_store.upsert_spans([
            SpanRecord(
                span_id=f"det-{i:03d}", trace_id=f"det-t{i}", session_id=f"det-s{i}",
                project="pnl-agent", span_kind="LLM",
                start_time=base + _td(minutes=i),
                workflow_stage="fobo_recon", asset_class="fx",
                user_id=f"analyst-{i % 4}",
                input_text=f"why is there a recon break of {100 + i}k on EURUSD",
                output_text="The FX break is caused by an unsettled trade; post an adjustment.",
            )
            for i in range(14)
        ])
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        runs = seeded_store.capability_runs_frame("fobo")
        assert runs.iloc[0]["n_rung2_candidates"] >= 1
        assert runs.iloc[0]["status"] == "ok"
        d_cands = seeded_store.candidates_frame("fobo", rung="deterministic")
        assert len(d_cands) >= 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder_run.py tests/test_capability_run.py -q -k "Rung2 or rung2"`
Expected: FAIL — `ImportError: cannot import name 'update_rung2'`.

- [x] **Step 3: Implement `update_rung2` + `_advance_unobserved(rung=...)`**

In `src/phoenix_scraper/ladder_run.py`, change `_advance_unobserved` to take
`rung: str` and pass it to `store.candidates_frame(capability_id, rung=rung)`;
update the `update_rung1` call site to `_advance_unobserved(store, capability.id,
run_ordinal, seen_ids, history_limit, rung="skill")`. Then append:

```python
from . import determinism  # add near the top imports


class Rung2RunOutcome(_Frozen):
    n_candidates: int = 0
    n_ready: int = 0
    n_insufficient: int = 0
    notes: tuple[str, ...] = ()
    crossed: tuple[str, ...] = ()


def _r2_candidate_id(capability_id: str, cluster_id: str) -> str:
    return f"{capability_id}:d:{cluster_id}"


def _r2_observation(
    signal: "determinism.Rung2Signal", cid: str, run_id: str, observed_at: datetime,
    crossed: bool,
) -> CandidateObservation:
    s = signal.signals
    return CandidateObservation(
        candidate_id=cid, run_id=run_id, observed_at=observed_at,
        count=signal.n_answer_spans, n_users=0, n_sessions=0, total_cost_usd=0.0,
        score=signal.determinism_score,
        signals={
            "template_concentration": s.template_concentration,
            "route_invariance": s.route_invariance,
            "output_self_similarity": s.output_self_similarity,
            "slot_stability": s.slot_stability,
            "n_templates": s.n_templates,
            "n_answer_spans": s.n_answer_spans,
            "route_applicable": s.route_applicable,
            "templates": [list(t) for t in signal.templates],
        },
        met_evidence_bar=signal.met_evidence_bar,
        crossed_threshold=crossed,
    )


def update_rung2(
    store: Store,
    capability: Capability,
    *,
    run_id: str,
    run_ordinal: int,
    capability_run_count: int,
    observed_at: datetime,
    signals: list["determinism.Rung2Signal"],
    thresholds: LadderThresholds,
    history_limit: int,
) -> Rung2RunOutcome:
    seen_ids: set[str] = set()
    n_ready = n_insufficient = 0
    crossed_ids: list[str] = []
    recorded = 0

    for signal in signals:
        cid = _r2_candidate_id(capability.id, signal.cluster_id)
        existing = store.get_candidate(cid)
        creation_ok = signal.eligible and signal.determinism_score >= 0.5
        if existing is None and not creation_ok:
            continue
        recorded += 1
        seen_ids.add(cid)

        prev = store.recent_candidate_observations(cid, 1)
        prev_met = prev[0].met_evidence_bar if prev else False
        crossed = signal.met_evidence_bar and not prev_met
        if crossed:
            crossed_ids.append(cid)

        obs = _r2_observation(signal, cid, run_id, observed_at, crossed)
        store.record_candidate_observation(obs)
        recent = store.recent_candidate_observations(cid, thresholds.rung2_sustained_runs)

        if existing is None:
            candidate = Candidate(
                candidate_id=cid, capability_id=capability.id, rung="deterministic",
                subtype="", cluster_id=signal.cluster_id, title=signal.title,
                signature=signal.signature, matched_skill=signal.matched_skill,
                status="new", first_seen_run_id=run_id, first_seen_at=observed_at,
                last_seen_run_id=run_id, last_seen_at=observed_at,
            )
        else:
            candidate = existing.model_copy(update={
                "matched_skill": signal.matched_skill, "title": signal.title,
                "signature": signal.signature, "last_seen_run_id": run_id,
                "last_seen_at": observed_at,
            })

        transition = next_status(
            candidate, obs, recent, run_ordinal=run_ordinal,
            capability_run_count=capability_run_count, thresholds=thresholds,
            eligible=signal.eligible,
        )
        updates: dict = {
            "status": transition.status,
            "current_evidence": {
                "determinism_score": signal.determinism_score,
                "n_answer_spans": signal.n_answer_spans,
                "n_templates": signal.signals.n_templates,
            },
        }
        if transition.set_ready_at and candidate.ready_at is None:
            updates["ready_at"] = observed_at
        store.upsert_candidate(candidate.model_copy(update=updates))

        if transition.decision_action == "reopen":
            store.record_candidate_decision(CandidateDecision(
                candidate_id=cid, run_id=run_id, action="reopen", actor="pheonix",
                note=transition.note or "material change", created_at=observed_at,
            ))
        if transition.status == "ready":
            n_ready += 1
        if transition.status == "insufficient_data":
            n_insufficient += 1
        store.prune_candidate_observations(cid, history_limit)

    _advance_unobserved(store, capability.id, run_ordinal, seen_ids, history_limit,
                        rung="deterministic")

    notes: list[str] = []
    skipped = sum(1 for s in signals if not s.eligible)
    if skipped:
        notes.append(f"Rung 2: {skipped} clusters skipped (no output text)")
    if recorded:
        notes.append(f"Rung 2: {recorded} candidates observed ({n_ready} ready)")
    return Rung2RunOutcome(
        n_candidates=recorded, n_ready=n_ready, n_insufficient=n_insufficient,
        notes=tuple(notes), crossed=tuple(crossed_ids),
    )
```

- [x] **Step 4: Run the `ladder_run` tests**

Run: `uv run pytest tests/test_ladder_run.py -q`
Expected: PASS.

- [x] **Step 5: Wire into `run_capability_analysis`**

In `src/phoenix_scraper/capability_run.py`, add imports:
```python
from .ladder import detect_rung1, detect_rung2, resolve_thresholds
from .ladder_run import update_rung1, update_rung2
```
After the `rung1 = update_rung1(...)` / `run_notes.extend(rung1.notes)` block:
```python
    rung2_signals = detect_rung2(list(clusters), list(matches), in_scope, thresholds=thresholds)
    rung2 = update_rung2(
        store, capability,
        run_id=run_id, run_ordinal=this_ordinal, capability_run_count=run_count,
        observed_at=started_at, signals=rung2_signals, thresholds=thresholds,
        history_limit=settings.run_history_limit,
    )
    run_notes.extend(rung2.notes)
```
In the `CapabilityRun(...)` constructor, replace the defaulted
`n_rung2_candidates` with:
```python
        n_rung2_candidates=rung2.n_candidates,
```

- [x] **Step 6: Run the wiring tests**

Run: `uv run pytest tests/test_capability_run.py tests/test_ladder_run.py -q`
Expected: PASS.

- [x] **Step 7: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~717 → ~726).

- [x] **Step 8: Commit**

```bash
git add src/phoenix_scraper/ladder_run.py src/phoenix_scraper/capability_run.py \
  tests/test_ladder_run.py tests/test_capability_run.py
git commit -m "feat: ladder_run.update_rung2 — persist Rung-2 candidates in the run"
```

---

## Task 6: `artifacts` — Rung-2 stub + promote branch

**Files:**
- Modify: `src/phoenix_scraper/artifacts.py`
- Test: `tests/test_artifacts.py` (append)

**Interfaces:**
- Produces:
  - `render_rung2_stub(candidate: Candidate, *, latest_observation_signals: dict,
    pairs: list[tuple[str, str]]) -> list[tuple[str, str]]` — returns THREE
    `(filename, body)` tuples: `<name>.py` (docstring with the evidence +
    templates; `TEMPLATES` dict from the observed templates;
    `DECISION_TABLE` dict populated only when `slot_stability >= 0.8`;
    `handle(prompt, context) -> str` raising `NotImplementedError`),
    `test_<name>.py` (`pytest.mark.parametrize` over `pairs`, asserting
    `handle` output matches modulo whitespace — ships **red**), `<name>.md`
    (evidence table, all templates with counts, route-flow line, sample span
    ids, `## Open decisions`).
  - `promote_candidate` `rung == "deterministic"` branch: writes the three files
    into `<capabilities_dir>/<cap>/deterministic/`, `<name>` = `_skill_stem` of
    the candidate, dedup-collided on the `.py`. Records the `promote` decision
    and `status='promoted'` + all three paths in `promoted_artifact_paths`, as
    the Rung-1 branch does.

- [x] **Step 1: Write the failing test**

Append to `tests/test_artifacts.py`:

```python
class TestRung2Artifacts:
    def _r2_cand(self, **over):
        base = dict(
            candidate_id="fobo:d:abc123", capability_id="fobo", rung="deterministic",
            subtype="", cluster_id="abc123",
            title="why is there a recon break of <num> on <book>",
            signature="why is there a recon break of <num> on <book>",
            status="accepted", first_seen_run_id="r1", first_seen_at=TS,
            last_seen_run_id="r3", last_seen_at=TS,
            current_evidence={"determinism_score": 0.86, "n_answer_spans": 41},
        )
        base.update(over)
        return Candidate(**base)

    def test_stub_has_three_files(self) -> None:
        files = artifacts.render_rung2_stub(
            self._r2_cand(),
            latest_observation_signals={
                "slot_stability": 0.88, "route_invariance": 0.93,
                "output_self_similarity": 0.91, "template_concentration": 0.75,
                "n_templates": 2,
                "templates": [["the break is an unsettled trade", 34],
                              ["the break matches a missing accrual", 7]],
            },
            pairs=[("why is there a break of 100k on BUND",
                    "the break is an unsettled trade")],
        )
        names = {n for n, _ in files}
        assert any(n.endswith(".py") and not n.startswith("test_") for n in names)
        assert any(n.startswith("test_") for n in names)
        assert any(n.endswith(".md") for n in names)
        py = next(b for n, b in files if n.endswith(".py") and not n.startswith("test_"))
        assert "TEMPLATES" in py and "raise NotImplementedError" in py
        md = next(b for n, b in files if n.endswith(".md"))
        assert "Open decisions" in md

    def test_promote_deterministic_writes_three_files(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "fobo", cap_filter=CapabilityFilter(workflow_stage="fobo_recon")
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        cand = self._r2_cand()
        seeded_store.upsert_candidate(cand)
        seeded_store.record_candidate_observation(
            __import__("phoenix_scraper.models", fromlist=["CandidateObservation"])
            .CandidateObservation(
                candidate_id=cand.candidate_id, run_id="r3", observed_at=TS,
                score=0.86, signals={"slot_stability": 0.5, "templates": [["t", 5]]},
            )
        )
        result = artifacts.promote_candidate(seeded_store, cap, cand, now=TS,
                                             actor="a", settings=s)
        assert result.wrote_files is True and len(result.paths) == 3
        from pathlib import Path
        assert all(Path(p).exists() for p in result.paths)
        assert any(p.endswith(".py") for p in result.paths)
        assert seeded_store.get_candidate(cand.candidate_id).status == "promoted"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_artifacts.py -q -k Rung2`
Expected: FAIL — `AttributeError: module 'phoenix_scraper.artifacts' has no attribute 'render_rung2_stub'`.

- [x] **Step 3: Implement**

In `src/phoenix_scraper/artifacts.py`, add:

```python
def render_rung2_stub(
    candidate: Candidate,
    *,
    latest_observation_signals: dict,
    pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    stem = _skill_stem(candidate)
    sig = latest_observation_signals
    templates = sig.get("templates") or []
    ev = candidate.current_evidence
    score = ev.get("determinism_score", 0.0)

    tmpl_lines = "\n".join(
        f'    "template_{i + 1}": {rep!r},  # {n} answers'
        for i, (rep, n) in enumerate(templates)
    ) or '    # no templates observed'
    decision_table = ""
    if float(sig.get("slot_stability") or 0.0) >= 0.8 and pairs:
        rows = "\n".join(
            f"    {_mask(p)!r}: \"template_1\","
            for p, _a in pairs[:8]
        )
        decision_table = f"\n\nDECISION_TABLE: dict[str, str] = {{\n{rows}\n}}\n"

    py = (
        f'"""Deterministic replacement for the LLM step behind `{stem}`.\n\n'
        f"Scaffolded by pheonix from candidate {candidate.candidate_id}.\n"
        f"determinism_score {score} — template_concentration "
        f"{sig.get('template_concentration')}, route_invariance "
        f"{sig.get('route_invariance')}, output_self_similarity "
        f"{sig.get('output_self_similarity')}, slot_stability "
        f"{sig.get('slot_stability')}.\n"
        f'"""\n'
        f"from __future__ import annotations\n\n"
        f"TEMPLATES: dict[str, str] = {{\n{tmpl_lines}\n}}\n"
        f"{decision_table}\n"
        f"def handle(prompt: str, context: list[dict]) -> str:\n"
        f'    """TODO: extract the slots from `prompt`, classify from `context`,\n'
        f"    return the filled TEMPLATES entry. test_{stem}.py has the real cases.\"\"\"\n"
        f"    raise NotImplementedError\n"
    )

    cases = ",\n".join(f"    ({p!r}, {a!r})" for p, a in pairs) or "    # none observed"
    test = (
        f'"""Real observed (prompt -> answer) pairs for `{stem}`. Ships red."""\n'
        f"import pytest\n\n"
        f"from .{stem} import handle\n\n"
        f"CASES = [\n{cases}\n]\n\n\n"
        f'@pytest.mark.parametrize("prompt, expected", CASES)\n'
        f"def test_handle_matches_observed(prompt: str, expected: str) -> None:\n"
        f'    assert " ".join(handle(prompt, []).split()) == " ".join(expected.split())\n'
    )

    tmpl_table = "\n".join(f"| T{i + 1} | {n} | `{rep}` |"
                           for i, (rep, n) in enumerate(templates)) or "| — | — | — |"
    md = (
        f"# {stem} — deterministic candidate\n\n"
        f"Source candidate: `{candidate.candidate_id}`  ·  "
        f"determinism_score **{score}**  ·  {ev.get('n_answer_spans', 0)} answer spans\n\n"
        f"## Signals\n\n"
        f"| signal | value |\n|---|---|\n"
        f"| template_concentration | {sig.get('template_concentration')} |\n"
        f"| route_invariance | {sig.get('route_invariance')} |\n"
        f"| output_self_similarity | {sig.get('output_self_similarity')} |\n"
        f"| slot_stability | {sig.get('slot_stability')} |\n\n"
        f"## Observed templates\n\n| # | answers | masked text |\n|---|---|---|\n{tmpl_table}\n\n"
        f"## Open decisions\n\n"
        f"- Slot extraction: which fields does `handle` pull from the prompt?\n"
        f"- Classifier input: what does `context` need to carry to pick the template?\n"
        f"- Error handling: what does `handle` do when no template fits?\n"
    )
    return [(f"{stem}.py", py), (f"test_{stem}.py", test), (f"{stem}.md", md)]


def _mask(text: str) -> str:
    from .normalize import mask_volatile
    return mask_volatile(text)
```

In `promote_candidate`, before the `if candidate.subtype == "strengthen_skill":`
check, add a `rung == "deterministic"` branch:

```python
    if candidate.rung == "deterministic":
        det_dir = cap_dir / "deterministic"
        det_dir.mkdir(parents=True, exist_ok=True)
        recent = store.recent_candidate_observations(candidate.candidate_id, 1)
        signals = recent[0].signals if recent else {}
        files = render_rung2_stub(
            candidate, latest_observation_signals=signals,
            pairs=list(zip(prompts, prompts, strict=False))[:20],
        )
        stem = files[0][0][:-3]
        py_path = dedupe_path(det_dir, stem, ".py")
        stem = py_path.stem
        written: list[str] = []
        contents_list: list[tuple[str, str]] = []
        for name, body in files:
            out = det_dir / name.replace(files[0][0][:-3], stem, 1)
            contents_list.append((str(out), body))
            if not dry_run:
                out.write_text(body, encoding="utf-8")
            written.append(str(out))
        paths = tuple(written)
        contents = tuple(contents_list)
        wrote = not dry_run
        if not dry_run:
            store.record_candidate_decision_now(candidate.candidate_id, "promote", actor, now)
            store.upsert_candidate(candidate.model_copy(update={
                "status": "promoted", "promoted_at": now,
                "promoted_artifact_paths": paths, "decided_by": actor, "decided_at": now,
            }))
        return PromoteResult(paths=paths, contents=contents, wrote_files=wrote)
```

**Note on `pairs`:** `_member_prompts` returns prompt strings only, not
`(prompt, answer)` pairs. For v1 the stub's `CASES` uses
`(prompt, prompt)` placeholders — the file ships **red** anyway and the human
fills the real expected answers from the `.md` templates. A follow-up can thread
real `(input_text, output_text)` pairs through `promote_candidate` from the
cluster members; noted in §16.
_(Resolved 2026-09-08 in `2026-09-08-ladder-trustworthiness.md` Task 2:
`artifacts._member_pairs` threads the real observed `(input_text, output_text)`
pairs from the latest run's cluster members; the `(prompt, prompt)` fallback only
fires when a cluster has no recorded members or no answer spans.)_

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_artifacts.py -q`
Expected: PASS.

- [x] **Step 5: File length + lint**

Run: `wc -l src/phoenix_scraper/artifacts.py && uv run ruff check src/phoenix_scraper/artifacts.py tests/test_artifacts.py`
Expected: under 400; ruff clean.

- [x] **Step 6: Commit**

```bash
git add src/phoenix_scraper/artifacts.py tests/test_artifacts.py
git commit -m "feat: artifacts.render_rung2_stub + promote deterministic branch"
```

---

## Task 7: CLI — `pheonix candidate <cid>` (one candidate's detail)

**Files:**
- Modify: `src/phoenix_scraper/cli.py`
- Test: `tests/test_candidate_cli.py` (append)

**Interfaces:**
- Produces:
  - `pheonix candidate <candidate_id> [--db] [--capabilities-dir]` — prints the
    candidate's header (rung, subtype, status, matched_skill), its
    `current_evidence`, the observation trend (one line per run:
    `run_id · count/score · met`), Rung-2 signal breakdown + templates from the
    latest observation, and the decision log.

- [x] **Step 1: Write the failing test**

Append to `tests/test_candidate_cli.py`:

```python
class TestCandidateDetail:
    def test_shows_trend_and_decisions(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        _invoke("decide", cid, "--action", "snooze", "--snooze-runs", "2",
                "--actor", "a", *common)
        r = _invoke("candidate", cid, *common)
        assert r.exit_code == 0, r.output
        assert cid in r.output
        assert "snooze" in r.output.lower()
        assert "run" in r.output.lower() or "score" in r.output.lower()

    def test_unknown_candidate_exits_1(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        r = _invoke("candidate", "nope:s:x", *common)
        assert r.exit_code == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_candidate_cli.py -q -k CandidateDetail`
Expected: FAIL — `candidate` is not a command (`exit_code == 2`).

- [x] **Step 3: Implement**

In `src/phoenix_scraper/cli.py`, after the `candidates` command:

```python
@app.command()
def candidate(
    candidate_id: str = CandidateIdArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """One candidate's evidence trend, signals, and decision log."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        c = store.get_candidate(candidate_id)
        if c is None:
            typer.secho(f"No candidate {candidate_id!r}.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        obs = store.candidate_observations_frame(candidate_id)
        decisions = store.candidate_decisions_frame(candidate_id)
    typer.echo(
        f"{c.candidate_id}\n  rung={c.rung} subtype={c.subtype or '-'} "
        f"status={c.status} matched_skill={c.matched_skill or '-'}"
    )
    typer.echo(f"  title: {c.title}")
    if c.current_evidence:
        typer.echo(f"  evidence: {c.current_evidence}")
    typer.echo("\n  trend:")
    for row in obs.to_dict("records"):
        score = row["score"]
        score_s = f"{score:.2f}" if score is not None else "-"
        typer.echo(
            f"    {row['run_id']:<27} count={row['count']:<4} score={score_s:<5} "
            f"{'met' if row['met_evidence_bar'] else '   '}"
        )
    if len(obs) and c.rung == "deterministic":
        last = json.loads(obs.iloc[-1]["signals_json"] or "{}")
        typer.echo("\n  signals (latest run):")
        for key in ("template_concentration", "route_invariance",
                    "output_self_similarity", "slot_stability"):
            typer.echo(f"    {key:<24} {last.get(key)}")
        for rep, n in last.get("templates", []):
            typer.echo(f"    template ({n})  {str(rep)[:70]}")
    typer.echo("\n  decisions:")
    for row in decisions.to_dict("records"):
        typer.echo(f"    {row['created_at']}  {row['action']:<8} by {row['actor']}  {row['note']}")
    if not len(decisions):
        typer.echo("    (none)")
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_candidate_cli.py -q`
Expected: PASS.

- [x] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~726 → ~730).

- [x] **Step 6: Commit**

```bash
git add src/phoenix_scraper/cli.py tests/test_candidate_cli.py
git commit -m "feat: pheonix candidate <cid> — one candidate's detail view"
```

---

## Task 8: Docs — CONTRACTS.md + README.md

**Files:**
- Modify: `CONTRACTS.md`
- Modify: `README.md`

- [x] **Step 1: CONTRACTS.md**

After the `## ladder_run.py` block, add a `## determinism.py` block and extend
the `## ladder.py` / `## ladder_run.py` / `## artifacts.py` blocks:

```
## determinism.py  (pure: the Rung-2 lexical determinism signal; no LLM)
def mask_volatile  # -> now lives in normalize.py, shared with prompt_signature
def build_templates(answers, *, fuzz_threshold) -> list[(masked_rep, count)]
def template_concentration(answers, *, fuzz_threshold) -> (concentration, k)   # k to cover >=90%
def route_invariance(flows) -> float                                          # modal / n
def output_self_similarity(answers, *, sample=200, max_pairs=5000) -> float
def slot_stability(pairs, templates, *, fuzz_threshold) -> float
def blend_determinism(signals: DeterminismSignals) -> float                   # 0.4/0.3/0.2/0.1, route N/A renormalises
def score_cluster(cluster_id, title, signature, matched_skill, member_spans, *,
        min_answer_spans, fuzz_threshold) -> Rung2Signal
    # answer span = LLM member span with non-empty output_text; < min -> eligible=False, score=0.
```

Add to `## ladder.py`: `detect_rung2(clusters, matches, in_scope, *, thresholds)
-> list[Rung2Signal]`; `next_status(..., eligible=True)` — ineligible
new/accumulating -> insufficient_data; insufficient_data + eligible ->
accumulating. Add to `## ladder_run.py`: `update_rung2(...)` (parallel to
`update_rung1`; creation floor determinism_score >= 0.5; `insufficient_data`
holding state). Add to `## artifacts.py`: `render_rung2_stub(candidate, *,
latest_observation_signals, pairs) -> [(filename, body) x3]` and the
`rung=='deterministic'` promote branch (writes `deterministic/<name>.{py,md}` +
`test_<name>.py`).

Note the new `Settings` fields: `rung2_min_answer_spans` (10),
`rung2_determinism_score` (0.8), `rung2_sustained_runs` (3). Update the `## cli.py`
line: add `candidate (<cid>)` next to `candidates`.

- [x] **Step 2: README.md**

In the `## The promotion ladder` section, replace the final sentence
("Rung 2 ... is the next phase.") with a **Rung 2** paragraph + one `bash` line:

> **Rung 2 — make it deterministic.** The same run scores every eligible cluster
> (`rung2_min_answer_spans` answer spans, default 10) on four lexical signals —
> do the answers collapse to a few templates, does the agent take the same route,
> are the answers similar, does each input phrasing map to one template — blended
> into a `determinism_score`. At `rung2_determinism_score` (0.8) sustained over
> `rung2_sustained_runs` (3) runs the `<cap>:d:<cluster>` candidate is `ready`;
> `promote` writes a `deterministic/<name>.py` stub + a red `test_<name>.py` with
> the real observed cases + a `<name>.md` write-up. A low score is a real
> "keep the model" answer, not a failure.
>
> ```bash
> pheonix candidates fobo --rung deterministic
> pheonix candidate fobo:d:abc123          # signals, templates, trend, decisions
> ```

- [x] **Step 3: Lint + full suite (docs — sanity only)**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [x] **Step 4: Commit**

```bash
git add CONTRACTS.md README.md
git commit -m "docs: Rung 2 (lexical determinism) — CONTRACTS + README"
```

---

## Self-Review

**1. Spec coverage (Phase D slice):**

| Spec element | Task |
|---|---|
| §9.2 `mask_volatile` extracted from `normalize.py` | Task 1 |
| §9.2 eligibility: `n_answer_spans >= rung2_min_answer_spans`, LLM + non-empty output | Task 3 (`score_cluster`) |
| §9.2 `template_concentration` (mask, group, greedy-merge, k to cover 90%, `1-(k-1)*0.25`) | Task 2 |
| §9.2 `route_invariance` (`_flow_signature` per trace, modal/n, N/A when no TOOL/RETRIEVER/AGENT/CHAIN) | Task 2 + Task 3 (`_flows_for`) |
| §9.2 `output_self_similarity` (mean pairwise `token_set_ratio/100`, sample ≤200 / ≤5000 pairs) | Task 2 |
| §9.2 `slot_stability` (per masked-input signature, modal template share, freq-weighted) | Task 2 |
| §9.2 blend weights 0.4/0.3/0.2/0.1, route N/A renormalises | Task 3 (`blend_determinism`) |
| §9.2 creation floor `determinism_score >= 0.5` first run | Task 5 (`update_rung2`) |
| §9.2 evidence bar + readiness (`rung2_sustained_runs`) | Task 4 (`detect_rung2` met flag) + reuse `readiness_met` |
| §9.2 run note `"Rung 2: N clusters skipped (no output text)"` | Task 5 (`update_rung2` notes) |
| §10.1 `new/accumulating → insufficient_data`; `insufficient_data → accumulating` | Task 4 (`next_status` `eligible`) |
| §10.1 `— → new` requires `determinism_score >= 0.5` | Task 5 (creation floor) |
| §10.2 step 8 (score eligible clusters, upsert candidates + observations, state machine) | Task 5 |
| §10.2 step 10 (`n_rung2_candidates` on the run) | Task 5 (wiring) |
| §8.4 `deterministic/<name>.py` (docstring, TEMPLATES, DECISION_TABLE when slot_stability high, `handle` NotImplementedError) | Task 6 (`render_rung2_stub`) |
| §8.4 `test_<name>.py` parametrized over observed pairs, ships red | Task 6 |
| §8.4 `<name>.md` (evidence, templates+counts, route-flow, span ids, Open decisions) | Task 6 |
| §14 three `rung2_*` Settings | Task 4 |

**Deferred (documented):** real `(input_text, output_text)` pairs threaded into
the Rung-2 stub's `CASES` — v1 uses `(prompt, prompt)` placeholders, the file
ships red regardless (§16 seam). `insights_llm._flow_signature` private import is
a deliberate reuse. HTTP routes (Phase E), SPA (Phase F).

**2. Placeholder scan:** No `TBD`/"handle edge cases". The literal `TODO` in
`render_rung2_stub`'s generated `handle` body and the `# TODO` in `<name>.md` are
the intended draft content per §8.4.

**3. Type consistency:**
- `DeterminismSignals` — 7 fields, identical in Task 2 def, Task 3
  `score_cluster` construction, Task 5 `_r2_observation` reads
  (`s.template_concentration` etc.). `Rung2Signal` — Task 3 def + `met_evidence_bar`
  added in Task 4; read in Task 4 `detect_rung2`, Task 5 `update_rung2`
  (`.eligible`, `.determinism_score`, `.met_evidence_bar`, `.n_answer_spans`,
  `.signals`, `.templates`, `.title`, `.signature`, `.matched_skill`,
  `.cluster_id`). ✓
- `LadderThresholds` — Task 3 (Phase C) 7 fields + Task 4 adds 4
  (`rung2_min_answer_spans`, `rung2_determinism_score`, `rung2_sustained_runs`,
  `cluster_fuzz_threshold`); every construction site is `resolve_thresholds` (one
  place). ✓
- `next_status(candidate, observation, recent_observations, *, run_ordinal,
  capability_run_count, thresholds, eligible=True)` — Rung-1 callers
  (`update_rung1`, Phase C tests) omit `eligible` → default True → unchanged. ✓
- `update_rung2(store, capability, *, run_id, run_ordinal, capability_run_count,
  observed_at, signals, thresholds, history_limit)` — identical kw set in Task 5
  interface, impl, test `_run2` helper, wiring call. ✓
- `_advance_unobserved(store, capability_id, run_ordinal, seen_ids,
  history_limit, rung)` — Task 5 adds `rung`; both call sites updated
  (`update_rung1` → `rung="skill"`, `update_rung2` → `rung="deterministic"`). ✓
- `render_rung2_stub(candidate, *, latest_observation_signals, pairs)` — Task 6
  def ↔ Task 6 tests ↔ `promote_candidate` call. ✓
- `Candidate` for a Rung-2 row: `rung="deterministic"`, `subtype=""`,
  `candidate_id="<cap>:d:<cluster>"` — Task 5 construction ↔ Task 5 tests ↔
  `candidates_frame(rung="deterministic")` in Task 5/6/7. ✓

**4. Ambiguity resolved:**
- **Creation floor vs `insufficient_data`.** A cluster with `< 10` answer spans
  on its FIRST sighting: no candidate (we cannot yet tell if it is
  deterministic). Once a candidate exists (it once scored `>= 0.5` eligible),
  a later ineligible run drives it to `insufficient_data` (Task 5:
  `existing is None and not creation_ok → continue`).
- **`met_evidence_bar` for Rung 2** is stamped by `detect_rung2` (it has the
  threshold), not `score_cluster` (it does not). `Rung2Signal.met_evidence_bar`
  defaults False so Task 3's own tests need no threshold.
- **Rung-2 observations have `n_users = 0 / n_sessions = 0`.** The determinism
  signal is about answers, not askers; the trend the SPA draws is `score` over
  runs. `count` on the observation carries `n_answer_spans` (what the chart's
  x-axis needs).
- **`route_invariance` N/A** is `signals.route_invariance = <value or None>` PLUS
  `route_applicable = False`; `blend_determinism` drops it only when
  `route_applicable is False` — so a genuine `route_invariance == 0.0` (tools
  present, routes vary wildly) still counts against the score.
- **`ladder.py` imports `determinism`** as a module (`from . import
  determinism`), not names, to keep the Rung-1 symbols unambiguous and avoid a
  circular import (`determinism` does not import `ladder`).

