# Capability Promotion Ladder — Phase C (Rung 1 + Lifecycle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect **Rung-1 candidates** (recurring in-scope prompt clusters that
need a new skill or a stronger one), persist them with an evidence trend and a
status machine, expose `pheonix candidates | decide | promote`, and write the
draft `skills/<name>.md` artifact on promote.

**Architecture:** Two new pure modules — `ladder.py` (threshold resolution,
Rung-1 detection, the lifecycle state machine, all DataFrame-in / value-out) and
`artifacts.py` (render the draft skill file / strengthen block). A new
store-touching orchestrator `ladder_run.py` (`update_rung1()`) upserts
`candidates`, writes one `candidate_observations` row per run, runs the state
machine, and advances the lifecycle for candidates not seen this run. It is
called from `capability_run.run_capability_analysis` **after** the scoped
analysis and **before** `record_capability_run` (so `capability_runs.n_rung1_candidates`
is accurate). Rung 2 / `determinism.py` is Phase D — the run keeps writing
`n_rung2_candidates = 0`.

**Tech Stack:** Python 3.11+, pydantic v2 (frozen models), pandas, Typer,
SQLite (stdlib `sqlite3`), pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
— this plan implements §7.2 (`candidates`, `candidate_observations`,
`candidate_decisions`), §7.3 (the three models + enums), §8.3 (Rung-1 artifact),
§9.1 (Rung-1 detection + evidence bar + readiness), §10.1 (status machine),
§10.2 steps 7 + 9 + 10 (Rung-1 slice), §10.3 (decisions), and the Phase C row of
§13. Rung 2 (§8.4, §9.2, §10.2 step 8) is Phase D. API routes (§11) are Phase E.

## Global Constraints

- Python **>= 3.11**. New files stay **under 400 lines** (`ladder.py`,
  `artifacts.py`, `ladder_run.py`); `storage.py`, `cli.py`, `models.py`,
  `capability_run.py` are pre-existing — judge only what this phase adds.
- **All functions return NEW objects** — never mutate an input argument. State
  transitions return a `LadderTransition`, they do not mutate the `Candidate`.
- **Type hints on every function signature.**
- Data models are **frozen** — subclass `_Frozen` in `models.py`
  (`ConfigDict(frozen=True)`); mutable defaults via `Field(default_factory=...)`.
- **TDD:** write the test in `tests/test_<module>.py` first, watch it fail, then
  implement.
- Run a module's tests: `uv run pytest tests/test_<module>.py -q`. Run
  everything: `uv run pytest -q` — **exit code 0 is the pass signal; the summary
  line is suppressed in this environment, trust the exit code.** The suite is at
  **642** after Phase B; nothing that passes may regress.
- Lint: `uv run ruff check src tests` (rules `E, F, I, UP, B`; line length 100).
- **No network, no live Phoenix in tests.**
- Commit message format: `<type>: <description>` — one commit per task (the
  final step of each task). End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```
- Package is `phoenix_scraper`; CLI is `pheonix`. Settings env prefix `PHEONIX_`.
- `run_id` is an ISO-8601 UTC timestamp string. `run_history_limit` (existing,
  default 20) bounds `candidate_observations` per candidate AND the "stale"
  window ("not observed for `run_history_limit` consecutive runs").
- **Run ordinal** = the count of this capability's `capability_runs` rows,
  ordered by `run_id` (== `started_at` order). `snooze_until_run` is an ordinal:
  `(ordinal at decision time) + snooze_runs`.
- Phase A shipped: `Capability`/`CapabilityFilter`; `capability.py`; `capabilities`
  table + CRUD; `pheonix capability new|list|show|sync`.
- Phase B shipped: `CapabilityRun`/`CapabilityRunResult`; `capability_runs` /
  `capability_cluster_snapshots` (column **`skill_name`**, not the spec's
  indicative `matched_skill`) / `capability_cluster_members` tables + `Store`
  methods; `src/phoenix_scraper/capability_run.py`
  (`run_capability_analysis` — costs→clusters→skills→matches→coverage→efficiency,
  records the run; `load_capability_skills`; `run_capabilities` orchestrator);
  `skills.scan_skill_files`; `pheonix run` / `pheonix capability runs`.

---

## Threshold defaults (§14 — copy verbatim into `Settings`, Task 3)

| Field | Env | Default |
|---|---|---|
| `rung1_min_users` | `PHEONIX_RUNG1_MIN_USERS` | `3` |
| `rung1_min_count` | `PHEONIX_RUNG1_MIN_COUNT` | `15` |
| `rung1_sustained_runs` | `PHEONIX_RUNG1_SUSTAINED_RUNS` | `5` |
| `material_change_count_factor` | `PHEONIX_MATERIAL_CHANGE_COUNT_FACTOR` | `1.5` |
| `material_change_users_delta` | `PHEONIX_MATERIAL_CHANGE_USERS_DELTA` | `2` |

`operator_name` (`PHEONIX_OPERATOR_NAME`, default `""`) already exists.
Per-capability `capability.thresholds` (a `dict[str, float]`) overrides any of
the `rung1_*` keys by bare name (`rung1_min_users`, `rung1_min_count`,
`rung1_sustained_runs`).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/models.py` | modify | `Candidate`, `CandidateObservation`, `CandidateDecision` frozen models + `Rung` / `CandidateStatus` / `DecisionAction` `Literal`s |
| `src/phoenix_scraper/config.py` | modify | 5 new `rung1_*` / `material_change_*` `Settings` fields |
| `src/phoenix_scraper/storage.py` | modify | 3 tables in `_SCHEMA`; `upsert_candidate`; `get_candidate`; `candidates_frame`; `record_candidate_observation`; `candidate_observations_frame`; `recent_candidate_observations`; `record_candidate_decision`; `candidate_decisions_frame`; `capability_run_ordinal`; `_prune_candidate_observations` |
| `src/phoenix_scraper/ladder.py` | **create** | `LadderThresholds` + `resolve_thresholds`; `Rung1Signal` + `detect_rung1`; `LadderTransition` + `next_status` / `advance_unobserved` / `is_material_change` |
| `src/phoenix_scraper/ladder_run.py` | **create** | `update_rung1(store, capability, run_id, ordinal, observed_at, signals, thresholds)` — upsert candidates, write observations, run the machine, advance unobserved; returns `Rung1RunOutcome` |
| `src/phoenix_scraper/artifacts.py` | **create** | `render_new_skill_md`; `render_strengthen_block`; `promote_candidate` |
| `src/phoenix_scraper/capability_run.py` | modify | call `ladder_run.update_rung1` before `record_capability_run`; set `run.n_rung1_candidates`; thread its notes |
| `src/phoenix_scraper/cli.py` | modify | `pheonix candidates <id>`, `pheonix decide <cid>`, `pheonix promote <cid>` |
| `tests/test_candidate_storage.py` | **create** | Task 2 |
| `tests/test_ladder.py` | **create** | Tasks 3–4 |
| `tests/test_ladder_run.py` | **create** | Task 5 |
| `tests/test_artifacts.py` | **create** | Task 6 |
| `tests/test_candidate_cli.py` | **create** | Task 7 |
| `tests/test_capability_run.py` | modify | Task 5 — Rung-1 candidates appear after a run |
| `CONTRACTS.md` / `README.md` | modify | Task 8 |

**Deliberately deferred (documented, not dropped):**
- Rung 2 / `determinism.py` / `mask_volatile` extraction → Phase D. `n_rung2_candidates`
  stays `0`; `ladder_run.update_rung1` is Rung-1 only.
- `derive_sessions` per capability is still not persisted (Phase F recomputes).
- `evaluate_spans` per capability (§10.2 step 6) — still not run here; Phase C
  does not evaluate. (Kept as a Phase D/E decision, matching the Phase B note.)
- HTTP routes for candidates/decisions/promote → Phase E. Phase C ships the CLI.

---

## Task 1: Models — `Candidate`, `CandidateObservation`, `CandidateDecision`

**Files:**
- Modify: `src/phoenix_scraper/models.py`
- Test: `tests/test_models_candidate.py` (create)

**Interfaces:**
- Consumes: `_Frozen`, `Literal`, `Field`, `datetime` (all already imported in `models.py`).
- Produces:
  - `Rung = Literal["skill", "deterministic"]`
  - `CandidateStatus = Literal["new", "accumulating", "insufficient_data", "ready",
    "accepted", "snoozed", "rejected", "promoted", "stale"]`
  - `DecisionAction = Literal["accept", "reject", "snooze", "reopen", "promote"]`
  - `Candidate(_Frozen)` — fields exactly as listed in Step 3.
  - `CandidateObservation(_Frozen)` — fields exactly as listed in Step 3.
  - `CandidateDecision(_Frozen)` — fields exactly as listed in Step 3.

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_candidate.py`:

```python
"""Frozen-model round-trips for the ladder candidate models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from phoenix_scraper.models import Candidate, CandidateDecision, CandidateObservation

TS = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)


def _candidate(**over) -> Candidate:
    base = dict(
        candidate_id="fobo:s:abc123",
        capability_id="fobo",
        rung="skill",
        subtype="new_skill",
        cluster_id="abc123",
        title="Why is there a recon break of <num> on <book>?",
        signature="why recon break of <num> on <book>",
        first_seen_run_id="2026-09-01T10:00:00+00:00",
        first_seen_at=TS,
        last_seen_run_id="2026-09-07T10:00:00+00:00",
        last_seen_at=TS,
    )
    base.update(over)
    return Candidate(**base)


def test_candidate_defaults() -> None:
    c = _candidate()
    assert c.status == "new"
    assert c.matched_skill is None
    assert c.promoted_artifact_paths == ()
    assert c.snooze_until_run is None
    assert c.current_evidence == {}


def test_candidate_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _candidate().status = "ready"


def test_candidate_rejects_bad_status() -> None:
    with pytest.raises(ValidationError):
        _candidate(status="cooking")


def test_observation_defaults() -> None:
    obs = CandidateObservation(
        candidate_id="fobo:s:abc123", run_id="2026-09-07T10:00:00+00:00", observed_at=TS
    )
    assert obs.count == 0 and obs.n_users == 0
    assert obs.score is None
    assert obs.signals == {}
    assert obs.met_evidence_bar is False and obs.crossed_threshold is False


def test_decision_round_trip() -> None:
    d = CandidateDecision(
        candidate_id="fobo:s:abc123", action="accept", actor="alice", created_at=TS
    )
    assert d.note == "" and d.run_id is None and d.id is None
    with pytest.raises(ValidationError):
        CandidateDecision(
            candidate_id="x", action="explode", actor="a", created_at=TS
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_candidate.py -q`
Expected: FAIL — `ImportError: cannot import name 'Candidate' from 'phoenix_scraper.models'`.

- [ ] **Step 3: Add the models**

In `src/phoenix_scraper/models.py`, immediately after the `CapabilityRunResult`
class (added in Phase B), add:

```python
Rung = Literal["skill", "deterministic"]
CandidateStatus = Literal[
    "new", "accumulating", "insufficient_data", "ready", "accepted",
    "snoozed", "rejected", "promoted", "stale",
]
DecisionAction = Literal["accept", "reject", "snooze", "reopen", "promote"]


class Candidate(_Frozen):
    """The persistent ladder record for one in-scope cluster (mirrors `candidates`)."""

    candidate_id: str  # "<cap>:s:<cluster_id>" (rung 1) | "<cap>:d:<cluster_id>" (rung 2)
    capability_id: str
    rung: Rung
    subtype: str = ""  # rung "skill": "new_skill" | "strengthen_skill"
    cluster_id: str
    title: str  # representative prompt, trimmed
    signature: str
    matched_skill: str | None = None
    status: CandidateStatus = "new"
    first_seen_run_id: str
    first_seen_at: datetime
    last_seen_run_id: str
    last_seen_at: datetime
    ready_at: datetime | None = None
    promoted_at: datetime | None = None
    promoted_artifact_paths: tuple[str, ...] = ()
    snooze_until_run: int | None = None  # run ordinal to unsnooze at
    dismiss_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    current_evidence: dict[str, Any] = Field(default_factory=dict)


class CandidateObservation(_Frozen):
    """One candidate's evidence for one run (mirrors `candidate_observations`)."""

    candidate_id: str
    run_id: str
    observed_at: datetime
    count: int = 0
    n_users: int = 0
    n_sessions: int = 0
    total_cost_usd: float = 0.0
    score: float | None = None  # rung 1: gap strength; rung 2: determinism_score
    signals: dict[str, Any] = Field(default_factory=dict)
    met_evidence_bar: bool = False
    crossed_threshold: bool = False  # met the bar this run, had not last run


class CandidateDecision(_Frozen):
    """One row of the append-only decision log (mirrors `candidate_decisions`)."""

    candidate_id: str
    action: DecisionAction
    actor: str
    created_at: datetime
    id: int | None = None  # AUTOINCREMENT — None until read back
    run_id: str | None = None
    note: str = ""
```

`Any`, `Literal`, `Field` are already imported in `models.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_models_candidate.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (642 → 647).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/models.py tests/test_models_candidate.py
git commit -m "feat: Candidate / CandidateObservation / CandidateDecision models"
```

---

## Task 2: Storage — candidate tables + methods

**Files:**
- Modify: `src/phoenix_scraper/storage.py`
- Test: `tests/test_candidate_storage.py` (create)

**Interfaces:**
- Consumes: `Candidate`, `CandidateObservation`, `CandidateDecision` (Task 1).
- Produces:
  - `Store.upsert_candidate(self, candidate: Candidate) -> None` — INSERT OR
    REPLACE on `candidate_id`.
  - `Store.get_candidate(self, candidate_id: str) -> Candidate | None`
  - `Store.candidates_frame(self, capability_id: str, *, rung: str | None = None,
    status: str | None = None) -> pd.DataFrame` — ordered by `status`, then
    `last_seen_at DESC`.
  - `Store.record_candidate_observation(self, obs: CandidateObservation) -> None`
    — INSERT OR REPLACE on `(candidate_id, run_id)`; then
    `_prune_candidate_observations(obs.candidate_id, self._history_limit_hint)`
    is **not** called here — pruning is driven by the run (Task 5) which knows
    the limit. This method only writes.
  - `Store.candidate_observations_frame(self, candidate_id: str) -> pd.DataFrame`
    — all rows, oldest first (by `run_id`).
  - `Store.recent_candidate_observations(self, candidate_id: str, n: int) ->
    list[CandidateObservation]` — newest `n`, returned newest-first.
  - `Store.record_candidate_decision(self, decision: CandidateDecision) -> int`
    — INSERT, returns the new `id`.
  - `Store.candidate_decisions_frame(self, candidate_id: str) -> pd.DataFrame` —
    oldest first (by `id`).
  - `Store.capability_run_ordinal(self, capability_id: str, run_id: str | None =
    None) -> int` — count of this capability's `capability_runs` rows with
    `run_id <= run_id` (or all of them when `run_id is None`). 0 when none.
  - `Store.prune_candidate_observations(self, candidate_id: str, keep: int) ->
    None` — drop all but the newest `keep` observation rows.

- [ ] **Step 1: Write the failing test**

Create `tests/test_candidate_storage.py`:

```python
"""Tests for the candidates / observations / decisions tables on Store."""

from datetime import UTC, datetime

from phoenix_scraper.models import Candidate, CandidateDecision, CandidateObservation

TS = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)


def _cand(cid: str = "fobo:s:aaa", cap: str = "fobo", **over) -> Candidate:
    base = dict(
        candidate_id=cid, capability_id=cap, rung="skill", subtype="new_skill",
        cluster_id=cid.split(":")[-1], title="why recon break", signature="why recon break",
        first_seen_run_id="r1", first_seen_at=TS, last_seen_run_id="r1", last_seen_at=TS,
    )
    base.update(over)
    return Candidate(**base)


def _obs(cid: str, run_id: str, **over) -> CandidateObservation:
    base = dict(candidate_id=cid, run_id=run_id, observed_at=TS, count=20, n_users=5)
    base.update(over)
    return CandidateObservation(**base)


class TestCandidateCrud:
    def test_upsert_then_get_round_trips(self, tmp_store) -> None:
        c = _cand(status="ready", matched_skill="fobo-triage",
                  promoted_artifact_paths=("capabilities/fobo/skills/x.md",),
                  current_evidence={"count": 20})
        tmp_store.upsert_candidate(c)
        assert tmp_store.get_candidate("fobo:s:aaa") == c

    def test_get_unknown_is_none(self, tmp_store) -> None:
        assert tmp_store.get_candidate("nope") is None

    def test_upsert_replaces(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        tmp_store.upsert_candidate(_cand(status="accumulating"))
        assert tmp_store.get_candidate("fobo:s:aaa").status == "accumulating"
        assert len(tmp_store.candidates_frame("fobo")) == 1

    def test_candidates_frame_filters(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand("fobo:s:aaa", status="ready"))
        tmp_store.upsert_candidate(_cand("fobo:s:bbb", status="rejected"))
        tmp_store.upsert_candidate(_cand("fobo:d:ccc", rung="deterministic", status="ready"))
        assert len(tmp_store.candidates_frame("fobo")) == 3
        assert len(tmp_store.candidates_frame("fobo", status="ready")) == 2
        assert len(tmp_store.candidates_frame("fobo", rung="skill")) == 2
        assert len(tmp_store.candidates_frame("fobo", rung="skill", status="ready")) == 1


class TestObservations:
    def test_record_then_frame_oldest_first(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "2026-09-05T10:00:00+00:00"))
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "2026-09-07T10:00:00+00:00"))
        frame = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert list(frame["run_id"]) == [
            "2026-09-05T10:00:00+00:00", "2026-09-07T10:00:00+00:00",
        ]

    def test_re_record_same_run_replaces(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "r1", count=10))
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "r1", count=99))
        frame = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert len(frame) == 1 and frame.iloc[0]["count"] == 99

    def test_recent_observations_newest_first(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        for day in (1, 2, 3, 4):
            tmp_store.record_candidate_observation(
                _obs("fobo:s:aaa", f"2026-09-0{day}T10:00:00+00:00", count=day)
            )
        recent = tmp_store.recent_candidate_observations("fobo:s:aaa", 2)
        assert [o.count for o in recent] == [4, 3]
        assert all(isinstance(o, CandidateObservation) for o in recent)

    def test_prune_keeps_newest(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        for day in range(1, 6):
            tmp_store.record_candidate_observation(
                _obs("fobo:s:aaa", f"2026-09-0{day}T10:00:00+00:00")
            )
        tmp_store.prune_candidate_observations("fobo:s:aaa", 2)
        frame = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert list(frame["run_id"]) == [
            "2026-09-04T10:00:00+00:00", "2026-09-05T10:00:00+00:00",
        ]


class TestDecisions:
    def test_record_returns_id_and_frame_ordered(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        i1 = tmp_store.record_candidate_decision(CandidateDecision(
            candidate_id="fobo:s:aaa", action="snooze", actor="a", note="q3 freeze",
            created_at=TS,
        ))
        i2 = tmp_store.record_candidate_decision(CandidateDecision(
            candidate_id="fobo:s:aaa", action="accept", actor="b", created_at=TS,
        ))
        assert i2 > i1
        frame = tmp_store.candidate_decisions_frame("fobo:s:aaa")
        assert list(frame["action"]) == ["snooze", "accept"]
        assert list(frame["actor"]) == ["a", "b"]


class TestRunOrdinal:
    def test_ordinal_counts_runs_up_to_and_including(self, seeded_store, tmp_path, settings) -> None:
        from phoenix_scraper import capability as cap_mod
        from phoenix_scraper.capability_run import run_capability_analysis
        from phoenix_scraper.models import CapabilityFilter
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "fobo", cap_filter=CapabilityFilter(workflow_stage="fobo_recon")
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        r1 = run_capability_analysis(seeded_store, s, cap,
                                     now=datetime(2026, 7, 20, 12, tzinfo=UTC))
        r2 = run_capability_analysis(seeded_store, s, cap,
                                     now=datetime(2026, 7, 21, 12, tzinfo=UTC))
        assert seeded_store.capability_run_ordinal("fobo") == 2
        assert seeded_store.capability_run_ordinal("fobo", r1.run.run_id) == 1
        assert seeded_store.capability_run_ordinal("fobo", r2.run.run_id) == 2
        assert seeded_store.capability_run_ordinal("other") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_candidate_storage.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'upsert_candidate'`.

- [ ] **Step 3: Add the schema**

In `src/phoenix_scraper/storage.py`, inside `_SCHEMA`, after the
`capability_cluster_members` block (+ its index) added in Phase B and before the
closing `"""`, add:

```sql

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id        TEXT PRIMARY KEY,
    capability_id       TEXT NOT NULL,
    rung                TEXT NOT NULL,
    subtype             TEXT NOT NULL DEFAULT '',
    cluster_id          TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    signature           TEXT NOT NULL DEFAULT '',
    matched_skill       TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    first_seen_run_id   TEXT NOT NULL,
    first_seen_at       TEXT NOT NULL,
    last_seen_run_id    TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    ready_at            TEXT,
    promoted_at         TEXT,
    promoted_artifact_paths_json TEXT NOT NULL DEFAULT '[]',
    snooze_until_run    INTEGER,
    dismiss_reason      TEXT,
    decided_by          TEXT,
    decided_at          TEXT,
    current_evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_candidates_capability
    ON candidates (capability_id, rung, status);

CREATE TABLE IF NOT EXISTS candidate_observations (
    candidate_id       TEXT NOT NULL,
    run_id             TEXT NOT NULL,
    observed_at        TEXT NOT NULL,
    count              INTEGER NOT NULL DEFAULT 0,
    n_users            INTEGER NOT NULL DEFAULT 0,
    n_sessions         INTEGER NOT NULL DEFAULT 0,
    total_cost_usd     REAL NOT NULL DEFAULT 0,
    score              REAL,
    signals_json       TEXT NOT NULL DEFAULT '{}',
    met_evidence_bar   INTEGER NOT NULL DEFAULT 0,
    crossed_threshold  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (candidate_id, run_id)
);

CREATE TABLE IF NOT EXISTS candidate_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL,
    run_id       TEXT,
    action       TEXT NOT NULL,
    actor        TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cand_decisions ON candidate_decisions (candidate_id, id);
```

- [ ] **Step 4: Extend the storage imports**

Add `Candidate`, `CandidateDecision`, `CandidateObservation` to the
`from .models import (...)` block in `storage.py` (alphabetical — after
`CapabilityRun`).

- [ ] **Step 5: Add the module-level column list + `_json` / `_bool` helpers check**

Near `_CAP_SNAPSHOT_COLUMNS` (added Phase B) add:

```python
_CANDIDATE_COLUMNS = [
    "candidate_id", "capability_id", "rung", "subtype", "cluster_id", "title",
    "signature", "matched_skill", "status", "first_seen_run_id", "first_seen_at",
    "last_seen_run_id", "last_seen_at", "ready_at", "promoted_at",
    "promoted_artifact_paths_json", "snooze_until_run", "dismiss_reason",
    "decided_by", "decided_at", "current_evidence_json",
]
```

- [ ] **Step 6: Add the methods**

In `storage.py`, after the Phase B `# ---- capability runs` section (after
`_prune_capability_runs`) and before `# ---- span evaluations`, add a
`# ---- ladder candidates` section:

```python
    # ---- ladder candidates --------------------------------------------------
    def upsert_candidate(self, candidate: Candidate) -> None:
        c = self._conn
        c.execute(
            "INSERT OR REPLACE INTO candidates ("
            "candidate_id, capability_id, rung, subtype, cluster_id, title, "
            "signature, matched_skill, status, first_seen_run_id, first_seen_at, "
            "last_seen_run_id, last_seen_at, ready_at, promoted_at, "
            "promoted_artifact_paths_json, snooze_until_run, dismiss_reason, "
            "decided_by, decided_at, current_evidence_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.candidate_id, candidate.capability_id, candidate.rung,
                candidate.subtype, candidate.cluster_id, candidate.title,
                candidate.signature, candidate.matched_skill, candidate.status,
                candidate.first_seen_run_id, _iso(candidate.first_seen_at),
                candidate.last_seen_run_id, _iso(candidate.last_seen_at),
                _iso(candidate.ready_at), _iso(candidate.promoted_at),
                json.dumps(list(candidate.promoted_artifact_paths)),
                candidate.snooze_until_run, candidate.dismiss_reason,
                candidate.decided_by, _iso(candidate.decided_at),
                json.dumps(candidate.current_evidence),
            ),
        )
        c.commit()

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        row = self._conn.execute(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return _candidate_from_row(row) if row is not None else None

    def candidates_frame(
        self, capability_id: str, *, rung: str | None = None, status: str | None = None
    ) -> pd.DataFrame:
        clauses = ["capability_id = ?"]
        params: list = [capability_id]
        if rung is not None:
            clauses.append("rung = ?")
            params.append(rung)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        return pd.read_sql_query(
            f"SELECT * FROM candidates WHERE {' AND '.join(clauses)} "  # noqa: S608 — literal clauses
            "ORDER BY status, last_seen_at DESC",
            self._conn, params=params,
        )

    def record_candidate_observation(self, obs: "CandidateObservation") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO candidate_observations ("
            "candidate_id, run_id, observed_at, count, n_users, n_sessions, "
            "total_cost_usd, score, signals_json, met_evidence_bar, crossed_threshold"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                obs.candidate_id, obs.run_id, _iso(obs.observed_at), obs.count,
                obs.n_users, obs.n_sessions, obs.total_cost_usd, obs.score,
                json.dumps(obs.signals), int(obs.met_evidence_bar),
                int(obs.crossed_threshold),
            ),
        )
        self._conn.commit()

    def candidate_observations_frame(self, candidate_id: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM candidate_observations WHERE candidate_id = ? "
            "ORDER BY run_id",
            self._conn, params=[candidate_id],
        )

    def recent_candidate_observations(
        self, candidate_id: str, n: int
    ) -> list["CandidateObservation"]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_observations WHERE candidate_id = ? "
            "ORDER BY run_id DESC LIMIT ?",
            (candidate_id, n),
        ).fetchall()
        return [_observation_from_row(row) for row in rows]

    def record_candidate_decision(self, decision: "CandidateDecision") -> int:
        cur = self._conn.execute(
            "INSERT INTO candidate_decisions (candidate_id, run_id, action, actor, "
            "note, created_at) VALUES (?,?,?,?,?,?)",
            (
                decision.candidate_id, decision.run_id, decision.action,
                decision.actor, decision.note, _iso(decision.created_at),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def candidate_decisions_frame(self, candidate_id: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM candidate_decisions WHERE candidate_id = ? ORDER BY id",
            self._conn, params=[candidate_id],
        )

    def capability_run_ordinal(
        self, capability_id: str, run_id: str | None = None
    ) -> int:
        if run_id is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM capability_runs WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM capability_runs WHERE capability_id = ? "
                "AND run_id <= ?",
                (capability_id, run_id),
            ).fetchone()
        return int(row["n"])

    def prune_candidate_observations(self, candidate_id: str, keep: int) -> None:
        stale = [
            row["run_id"]
            for row in self._conn.execute(
                "SELECT run_id FROM candidate_observations WHERE candidate_id = ? "
                "ORDER BY run_id DESC LIMIT -1 OFFSET ?",
                (candidate_id, max(1, keep)),
            ).fetchall()
        ]
        if not stale:
            return
        placeholders = ",".join("?" * len(stale))
        self._conn.execute(
            f"DELETE FROM candidate_observations WHERE candidate_id = ? "  # noqa: S608 — placeholders only
            f"AND run_id IN ({placeholders})",
            [candidate_id, *stale],
        )
        self._conn.commit()
```

Then, near `_capability_from_row` (Phase A), add the row parsers:

```python
def _candidate_from_row(row: sqlite3.Row) -> Candidate:
    return Candidate(
        candidate_id=row["candidate_id"],
        capability_id=row["capability_id"],
        rung=row["rung"],
        subtype=row["subtype"],
        cluster_id=row["cluster_id"],
        title=row["title"],
        signature=row["signature"],
        matched_skill=row["matched_skill"],
        status=row["status"],
        first_seen_run_id=row["first_seen_run_id"],
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_seen_run_id=row["last_seen_run_id"],
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        ready_at=_dt_or_none(row["ready_at"]),
        promoted_at=_dt_or_none(row["promoted_at"]),
        promoted_artifact_paths=tuple(json.loads(row["promoted_artifact_paths_json"])),
        snooze_until_run=row["snooze_until_run"],
        dismiss_reason=row["dismiss_reason"],
        decided_by=row["decided_by"],
        decided_at=_dt_or_none(row["decided_at"]),
        current_evidence=json.loads(row["current_evidence_json"]),
    )


def _observation_from_row(row: sqlite3.Row) -> CandidateObservation:
    return CandidateObservation(
        candidate_id=row["candidate_id"],
        run_id=row["run_id"],
        observed_at=datetime.fromisoformat(row["observed_at"]),
        count=row["count"],
        n_users=row["n_users"],
        n_sessions=row["n_sessions"],
        total_cost_usd=row["total_cost_usd"],
        score=row["score"],
        signals=json.loads(row["signals_json"]),
        met_evidence_bar=bool(row["met_evidence_bar"]),
        crossed_threshold=bool(row["crossed_threshold"]),
    )


def _dt_or_none(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
```

`datetime` and `sqlite3` are already imported in `storage.py`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_candidate_storage.py -q`
Expected: PASS.

- [ ] **Step 8: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (647 → ~659).

- [ ] **Step 9: Commit**

```bash
git add src/phoenix_scraper/storage.py tests/test_candidate_storage.py
git commit -m "feat: candidates / observations / decisions tables and Store methods"
```

---

## Task 3: `ladder.py` — thresholds + Rung-1 detection (pure)

**Files:**
- Modify: `src/phoenix_scraper/config.py`
- Create: `src/phoenix_scraper/ladder.py`
- Test: `tests/test_ladder.py` (create)

**Interfaces:**
- Consumes: `models.Capability`, `config.Settings`, `models.PromptCluster`,
  `models.SkillMatch`, and the `annotated` / `efficiency` frames produced by
  `capability_run` (`skill_coverage.annotate_coverage` /
  `insights.cluster_efficiency`).
- Produces:
  - `Settings` fields: `rung1_min_users: int = 3`, `rung1_min_count: int = 15`,
    `rung1_sustained_runs: int = 5`, `material_change_count_factor: float = 1.5`,
    `material_change_users_delta: int = 2`.
  - `LadderThresholds(_Frozen)` — `rung1_min_users: int`, `rung1_min_count: int`,
    `rung1_sustained_runs: int`, `material_change_count_factor: float`,
    `material_change_users_delta: int`, `skill_match_threshold: float`,
    `skill_coverage_threshold: float`.
  - `resolve_thresholds(capability: Capability, settings: Settings) ->
    LadderThresholds` — `settings` defaults, overridden by
    `capability.thresholds` for the `rung1_*` keys.
  - `Rung1Signal(_Frozen)` — `cluster_id: str`, `subtype: Literal["new_skill",
    "strengthen_skill"]`, `title: str`, `signature: str`, `matched_skill: str |
    None`, `score: float`, `count: int`, `n_users: int`, `n_sessions: int`,
    `total_cost_usd: float`, `route_len_avg: float | None`, `long_route: bool`,
    `met_evidence_bar: bool`.
  - `RUNG1_CREATION_FLOOR(count: int, thresholds) -> int` is inlined, not a
    function: `max(3, thresholds.rung1_min_count // 3)`.
  - `detect_rung1(clusters: list[PromptCluster], matches: list[SkillMatch],
    annotated: pd.DataFrame, efficiency: pd.DataFrame, *, thresholds:
    LadderThresholds) -> list[Rung1Signal]` — one signal per in-scope cluster
    whose `count` is at or above the creation floor and which is either
    `new_skill` or `strengthen_skill`. Covered clusters (matched AND
    `coverage_score >= skill_coverage_threshold`) produce **no** signal.

- [ ] **Step 1: Add the Settings fields**

In `src/phoenix_scraper/config.py`, in the `# analysis knobs` / validation-knobs
region (after `run_history_limit`), add:

```python
    # ladder — Rung 1 (see docs/superpowers/specs/...-ladder-design.md §9.1, §14)
    rung1_min_users: int = 3  # evidence bar: distinct users
    rung1_min_count: int = 15  # evidence bar: asks
    rung1_sustained_runs: int = 5  # consecutive runs meeting the bar -> ready
    material_change_count_factor: float = 1.5  # reopen a rejected candidate
    material_change_users_delta: int = 2  # ... or this many more users
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_ladder.py`:

```python
"""Pure-function tests for ladder threshold resolution + Rung-1 detection."""

import pandas as pd

from phoenix_scraper import ladder
from phoenix_scraper.config import Settings
from phoenix_scraper.models import Capability, CapabilityFilter, PromptCluster, SkillMatch


def _settings(**over) -> Settings:
    return Settings(db_path="x.db", **over)


def _capability(thresholds=None) -> Capability:
    return Capability(
        id="fobo", name="FOBO", filter=CapabilityFilter(workflow_stage="fobo_recon"),
        thresholds=thresholds or {},
    )


def _cluster(cid: str, count: int, n_users: int = 5, **over) -> PromptCluster:
    base = dict(
        cluster_id=cid, signature=f"sig {cid}", representative=f"why {cid} break",
        count=count, n_users=n_users, n_sessions=count, total_cost_usd=1.0,
        span_ids=tuple(f"{cid}-{i}" for i in range(count)),
    )
    base.update(over)
    return PromptCluster(**base)


class TestResolveThresholds:
    def test_settings_defaults(self) -> None:
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert t.rung1_min_users == 3 and t.rung1_min_count == 15
        assert t.rung1_sustained_runs == 5
        assert t.skill_match_threshold == 0.55 and t.skill_coverage_threshold == 0.70

    def test_capability_overrides_win(self) -> None:
        t = ladder.resolve_thresholds(
            _capability({"rung1_min_users": 8, "rung1_sustained_runs": 2}), _settings()
        )
        assert t.rung1_min_users == 8 and t.rung1_sustained_runs == 2
        assert t.rung1_min_count == 15  # untouched key still from settings

    def test_settings_env_overrides_default(self) -> None:
        t = ladder.resolve_thresholds(_capability(), _settings(rung1_min_count=40))
        assert t.rung1_min_count == 40


class TestDetectRung1:
    def _frames(self, clusters, matches, covered_ids=()):
        annotated = pd.DataFrame(
            [
                {
                    "cluster_id": m.cluster_id, "skill_name": m.skill_name,
                    "representative": "", "signature": "", "count": 0, "n_users": 0,
                    "coverage_score": 0.9 if m.cluster_id in covered_ids else 0.2,
                    "covered": m.cluster_id in covered_ids,
                }
                for m in matches
            ],
            columns=["cluster_id", "skill_name", "representative", "signature",
                     "count", "n_users", "coverage_score", "covered"],
        )
        efficiency = pd.DataFrame(
            [{"cluster_id": c.cluster_id, "route_len_avg": 3.0, "long_route": False}
             for c in clusters],
            columns=["cluster_id", "route_len_avg", "long_route"],
        )
        return annotated, efficiency

    def test_new_skill_signal_when_nothing_matches(self) -> None:
        clusters = [_cluster("aaa", count=20)]
        annotated, efficiency = self._frames(clusters, [])
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung1(clusters, [], annotated, efficiency, thresholds=t)
        assert len(signals) == 1
        s = signals[0]
        assert s.subtype == "new_skill" and s.matched_skill is None
        assert s.score == 1.0  # nothing close
        assert s.met_evidence_bar is True  # 20 >= 15, 5 >= 3

    def test_strengthen_signal_when_match_but_thin_coverage(self) -> None:
        clusters = [_cluster("bbb", count=18)]
        matches = [SkillMatch(cluster_id="bbb", skill_name="fobo-triage", score=0.72)]
        annotated, efficiency = self._frames(clusters, matches, covered_ids=())
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung1(clusters, matches, annotated, efficiency, thresholds=t)
        assert len(signals) == 1
        assert signals[0].subtype == "strengthen_skill"
        assert signals[0].matched_skill == "fobo-triage"
        assert 0 < signals[0].score <= 1

    def test_covered_cluster_yields_no_signal(self) -> None:
        clusters = [_cluster("ccc", count=30)]
        matches = [SkillMatch(cluster_id="ccc", skill_name="fobo-triage", score=0.9)]
        annotated, efficiency = self._frames(clusters, matches, covered_ids={"ccc"})
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert ladder.detect_rung1(clusters, matches, annotated, efficiency, thresholds=t) == []

    def test_below_creation_floor_yields_no_signal(self) -> None:
        # floor = max(3, 15 // 3) = 5
        clusters = [_cluster("ddd", count=4)]
        annotated, efficiency = self._frames(clusters, [])
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert ladder.detect_rung1(clusters, [], annotated, efficiency, thresholds=t) == []

    def test_between_floor_and_bar_is_signal_but_bar_not_met(self) -> None:
        clusters = [_cluster("eee", count=8, n_users=2)]
        annotated, efficiency = self._frames(clusters, [])
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung1(clusters, [], annotated, efficiency, thresholds=t)
        assert len(signals) == 1 and signals[0].met_evidence_bar is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoenix_scraper.ladder'`.

- [ ] **Step 4: Create `ladder.py` (thresholds + detection only)**

Create `src/phoenix_scraper/ladder.py`:

```python
"""Rung 1 of the promotion ladder: recurring prompt -> skill, plus the lifecycle
state machine. Pure — DataFrame / value in, value out. No store, no I/O.

`detect_rung1` turns a run's scoped analysis into `Rung1Signal`s (one per
in-scope cluster that needs a skill it does not have). `next_status` /
`advance_unobserved` / `is_material_change` are the §10.1 status machine, one
transition at a time. `ladder_run.update_rung1` (store-touching) drives them.
"""

from typing import Literal

import pandas as pd

from .config import Settings
from .models import Capability, PromptCluster, SkillMatch, _Frozen

_RUNG1_KEYS = ("rung1_min_users", "rung1_min_count", "rung1_sustained_runs")


class LadderThresholds(_Frozen):
    rung1_min_users: int
    rung1_min_count: int
    rung1_sustained_runs: int
    material_change_count_factor: float
    material_change_users_delta: int
    skill_match_threshold: float
    skill_coverage_threshold: float


def resolve_thresholds(capability: Capability, settings: Settings) -> LadderThresholds:
    """Settings defaults, overridden by capability.thresholds for the rung1_* keys."""
    over = capability.thresholds
    return LadderThresholds(
        rung1_min_users=int(over.get("rung1_min_users", settings.rung1_min_users)),
        rung1_min_count=int(over.get("rung1_min_count", settings.rung1_min_count)),
        rung1_sustained_runs=int(
            over.get("rung1_sustained_runs", settings.rung1_sustained_runs)
        ),
        material_change_count_factor=settings.material_change_count_factor,
        material_change_users_delta=settings.material_change_users_delta,
        skill_match_threshold=settings.skill_match_threshold,
        skill_coverage_threshold=settings.skill_coverage_threshold,
    )


class Rung1Signal(_Frozen):
    cluster_id: str
    subtype: Literal["new_skill", "strengthen_skill"]
    title: str
    signature: str
    matched_skill: str | None
    score: float  # gap strength, 0-1
    count: int
    n_users: int
    n_sessions: int
    total_cost_usd: float
    route_len_avg: float | None
    long_route: bool
    met_evidence_bar: bool


def _creation_floor(thresholds: LadderThresholds) -> int:
    return max(3, thresholds.rung1_min_count // 3)


def _efficiency_lookup(efficiency: pd.DataFrame) -> dict[str, tuple[float | None, bool]]:
    out: dict[str, tuple[float | None, bool]] = {}
    if efficiency is None or efficiency.empty:
        return out
    for row in efficiency.to_dict("records"):
        out[row["cluster_id"]] = (
            row.get("route_len_avg"), bool(row.get("long_route")),
        )
    return out


def _coverage_lookup(annotated: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    if annotated is None or annotated.empty:
        return out
    for row in annotated.to_dict("records"):
        out[row["cluster_id"]] = float(row.get("coverage_score") or 0.0)
    return out


def detect_rung1(
    clusters: list[PromptCluster],
    matches: list[SkillMatch],
    annotated: pd.DataFrame,
    efficiency: pd.DataFrame,
    *,
    thresholds: LadderThresholds,
) -> list[Rung1Signal]:
    """One Rung1Signal per in-scope cluster that needs a skill it does not have."""
    floor = _creation_floor(thresholds)
    match_by_cluster = {m.cluster_id: m for m in matches}
    coverage = _coverage_lookup(annotated)
    routes = _efficiency_lookup(efficiency)

    signals: list[Rung1Signal] = []
    for cluster in clusters:
        if cluster.count < floor:
            continue
        match = match_by_cluster.get(cluster.cluster_id)
        if match is None or match.score < thresholds.skill_match_threshold:
            subtype: Literal["new_skill", "strengthen_skill"] = "new_skill"
            matched_skill = None
            best = match.score if match else 0.0
            score = round(1.0 - best, 4)
        else:
            cov = coverage.get(cluster.cluster_id, 0.0)
            if cov >= thresholds.skill_coverage_threshold:
                continue  # covered: the skill works
            subtype = "strengthen_skill"
            matched_skill = match.skill_name
            gap = (thresholds.skill_coverage_threshold - cov) / thresholds.skill_coverage_threshold
            score = round(min(1.0, max(0.0, gap)), 4)

        route_len, long_route = routes.get(cluster.cluster_id, (None, False))
        signals.append(
            Rung1Signal(
                cluster_id=cluster.cluster_id,
                subtype=subtype,
                title=cluster.representative.strip()[:200],
                signature=cluster.signature,
                matched_skill=matched_skill,
                score=score,
                count=cluster.count,
                n_users=cluster.n_users,
                n_sessions=cluster.n_sessions,
                total_cost_usd=cluster.total_cost_usd,
                route_len_avg=route_len,
                long_route=long_route,
                met_evidence_bar=(
                    cluster.n_users >= thresholds.rung1_min_users
                    and cluster.count >= thresholds.rung1_min_count
                ),
            )
        )
    return signals
```

`_Frozen` is exported from `models.py` (it is the base class — importing it is
fine; it is already used across the package).

- [ ] **Step 5: Run the detection tests**

Run: `uv run pytest tests/test_ladder.py -q`
Expected: PASS (all `TestResolveThresholds` + `TestDetectRung1`).

- [ ] **Step 6: File length + lint**

Run: `wc -l src/phoenix_scraper/ladder.py && uv run ruff check src/phoenix_scraper/ladder.py src/phoenix_scraper/config.py tests/test_ladder.py`
Expected: under 400 lines; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/phoenix_scraper/ladder.py src/phoenix_scraper/config.py tests/test_ladder.py
git commit -m "feat: ladder.py — threshold resolution + Rung-1 detection"
```

---

## Task 4: `ladder.py` — the lifecycle state machine (pure)

**Files:**
- Modify: `src/phoenix_scraper/ladder.py`
- Test: `tests/test_ladder.py` (append)

**Interfaces:**
- Consumes: `models.Candidate`, `models.CandidateObservation`, Task 3's
  `LadderThresholds`.
- Produces:
  - `LadderTransition(_Frozen)` — `status: CandidateStatus`, `note: str | None =
    None`, `set_ready_at: bool = False`, `decision_action: str | None = None`
    (set to `"reopen"` when a rejected candidate auto-reopens).
  - `readiness_met(recent_observations: list[CandidateObservation], *,
    sustained_runs: int, capability_run_count: int) -> bool` — the last
    `sustained_runs` observations (newest-first list) ALL `met_evidence_bar`, and
    the capability has at least `sustained_runs` runs.
  - `is_material_change(candidate: Candidate, observation: CandidateObservation,
    *, thresholds: LadderThresholds) -> bool` — reads
    `candidate.current_evidence["count_at_rejection"]` /
    `["n_users_at_rejection"]`.
  - `next_status(candidate: Candidate, observation: CandidateObservation,
    recent_observations: list[CandidateObservation], *, run_ordinal: int,
    capability_run_count: int, thresholds: LadderThresholds) -> LadderTransition`
    — the transition when the candidate **was observed** this run.
    `recent_observations` is newest-first and INCLUDES this run's observation.
  - `advance_unobserved(candidate: Candidate, *, run_ordinal: int,
    last_seen_ordinal: int, history_limit: int) -> LadderTransition | None` — the
    transition when the candidate was **not** observed this run (auto-unsnooze,
    `stale`). `None` = no change.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ladder.py`:

```python
from datetime import UTC, datetime

from phoenix_scraper.models import Candidate, CandidateObservation

_TS = datetime(2026, 9, 7, tzinfo=UTC)


def _cand2(status: str = "new", **over) -> Candidate:
    base = dict(
        candidate_id="fobo:s:aaa", capability_id="fobo", rung="skill",
        subtype="new_skill", cluster_id="aaa", title="t", signature="s",
        first_seen_run_id="r1", first_seen_at=_TS, last_seen_run_id="r1",
        last_seen_at=_TS, status=status,
    )
    base.update(over)
    return Candidate(**base)


def _o(met: bool, run_id: str = "r", **over) -> CandidateObservation:
    base = dict(candidate_id="fobo:s:aaa", run_id=run_id, observed_at=_TS,
               count=20, n_users=5, met_evidence_bar=met)
    base.update(over)
    return CandidateObservation(**base)


class TestReadiness:
    def test_needs_full_sustained_streak(self) -> None:
        recent = [_o(True), _o(True), _o(True)]
        assert ladder.readiness_met(recent, sustained_runs=3, capability_run_count=5) is True

    def test_a_miss_in_the_window_blocks(self) -> None:
        recent = [_o(True), _o(False), _o(True)]
        assert ladder.readiness_met(recent, sustained_runs=3, capability_run_count=5) is False

    def test_not_enough_runs_yet(self) -> None:
        recent = [_o(True), _o(True)]
        assert ladder.readiness_met(recent, sustained_runs=3, capability_run_count=2) is False


class TestNextStatus:
    def _t(self):
        return ladder.resolve_thresholds(_capability(), _settings())

    def test_new_first_observation_stays_new(self) -> None:
        tr = ladder.next_status(_cand2("new"), _o(False), [_o(False)],
                                run_ordinal=1, capability_run_count=1, thresholds=self._t())
        assert tr.status == "new"

    def test_new_second_observation_becomes_accumulating(self) -> None:
        tr = ladder.next_status(_cand2("new"), _o(False), [_o(False), _o(False)],
                                run_ordinal=2, capability_run_count=2, thresholds=self._t())
        assert tr.status == "accumulating"

    def test_accumulating_to_ready_on_streak(self) -> None:
        recent = [_o(True)] * 5
        tr = ladder.next_status(_cand2("accumulating"), _o(True), recent,
                                run_ordinal=6, capability_run_count=6, thresholds=self._t())
        assert tr.status == "ready" and tr.set_ready_at is True

    def test_ready_falls_back_when_evidence_fades(self) -> None:
        recent = [_o(False), _o(True), _o(True), _o(True), _o(True)]
        tr = ladder.next_status(_cand2("ready"), _o(False), recent,
                                run_ordinal=7, capability_run_count=7, thresholds=self._t())
        assert tr.status == "accumulating" and tr.note

    def test_accepted_and_promoted_are_stable(self) -> None:
        for st in ("accepted", "promoted"):
            tr = ladder.next_status(_cand2(st), _o(True), [_o(True)] * 5,
                                    run_ordinal=9, capability_run_count=9, thresholds=self._t())
            assert tr.status == st

    def test_snoozed_unsnoozes_when_ordinal_passes(self) -> None:
        c = _cand2("snoozed", snooze_until_run=5)
        tr = ladder.next_status(c, _o(True), [_o(True)],
                                run_ordinal=5, capability_run_count=5, thresholds=self._t())
        assert tr.status == "accumulating"

    def test_snoozed_stays_when_ordinal_not_reached(self) -> None:
        c = _cand2("snoozed", snooze_until_run=9)
        tr = ladder.next_status(c, _o(True), [_o(True)],
                                run_ordinal=5, capability_run_count=5, thresholds=self._t())
        assert tr.status == "snoozed"

    def test_stale_reactivates_on_observation(self) -> None:
        tr = ladder.next_status(_cand2("stale"), _o(False), [_o(False), _o(False)],
                                run_ordinal=8, capability_run_count=8, thresholds=self._t())
        assert tr.status == "accumulating"

    def test_rejected_reopens_on_material_change(self) -> None:
        c = _cand2("rejected", current_evidence={"count_at_rejection": 20, "n_users_at_rejection": 4})
        tr = ladder.next_status(c, _o(True, count=40, n_users=5), [_o(True)],
                                run_ordinal=8, capability_run_count=8, thresholds=self._t())
        assert tr.status == "accumulating" and tr.decision_action == "reopen"

    def test_rejected_stays_without_material_change(self) -> None:
        c = _cand2("rejected", current_evidence={"count_at_rejection": 20, "n_users_at_rejection": 4})
        tr = ladder.next_status(c, _o(True, count=22, n_users=4), [_o(True)],
                                run_ordinal=8, capability_run_count=8, thresholds=self._t())
        assert tr.status == "rejected"


class TestAdvanceUnobserved:
    def test_stale_after_history_limit_runs(self) -> None:
        tr = ladder.advance_unobserved(_cand2("accumulating"),
                                       run_ordinal=25, last_seen_ordinal=4, history_limit=20)
        assert tr is not None and tr.status == "stale"

    def test_not_yet_stale(self) -> None:
        assert ladder.advance_unobserved(_cand2("accumulating"),
                                         run_ordinal=10, last_seen_ordinal=4,
                                         history_limit=20) is None

    def test_unsnooze_even_when_unobserved(self) -> None:
        tr = ladder.advance_unobserved(_cand2("snoozed", snooze_until_run=8),
                                       run_ordinal=8, last_seen_ordinal=3, history_limit=20)
        assert tr is not None and tr.status == "accumulating"

    def test_terminal_states_untouched(self) -> None:
        for st in ("promoted", "rejected", "accepted"):
            assert ladder.advance_unobserved(_cand2(st), run_ordinal=99,
                                             last_seen_ordinal=1, history_limit=20) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder.py -q -k "Readiness or NextStatus or AdvanceUnobserved"`
Expected: FAIL — `AttributeError: module 'phoenix_scraper.ladder' has no attribute 'next_status'`.

- [ ] **Step 3: Implement the state machine**

Append to `src/phoenix_scraper/ladder.py` (after `detect_rung1`). Add
`Candidate`, `CandidateObservation`, `CandidateStatus` to the
`from .models import ...` line:

```python
_STALE_ELIGIBLE = frozenset({"new", "accumulating", "ready"})
_HUMAN_TERMINAL = frozenset({"accepted", "promoted"})


class LadderTransition(_Frozen):
    status: CandidateStatus
    note: str | None = None
    set_ready_at: bool = False
    decision_action: str | None = None  # "reopen" for an auto-reopen


def readiness_met(
    recent_observations: list[CandidateObservation],
    *,
    sustained_runs: int,
    capability_run_count: int,
) -> bool:
    if capability_run_count < sustained_runs:
        return False
    window = recent_observations[:sustained_runs]
    return len(window) >= sustained_runs and all(o.met_evidence_bar for o in window)


def is_material_change(
    candidate: Candidate,
    observation: CandidateObservation,
    *,
    thresholds: LadderThresholds,
) -> bool:
    ev = candidate.current_evidence
    count_at = ev.get("count_at_rejection")
    users_at = ev.get("n_users_at_rejection")
    if count_at is None or users_at is None:
        return False
    return (
        observation.count >= thresholds.material_change_count_factor * float(count_at)
        or observation.n_users >= int(users_at) + thresholds.material_change_users_delta
    )


def _unsnoozed(candidate: Candidate, run_ordinal: int) -> bool:
    return (
        candidate.status == "snoozed"
        and candidate.snooze_until_run is not None
        and run_ordinal >= candidate.snooze_until_run
    )


def next_status(
    candidate: Candidate,
    observation: CandidateObservation,
    recent_observations: list[CandidateObservation],
    *,
    run_ordinal: int,
    capability_run_count: int,
    thresholds: LadderThresholds,
) -> LadderTransition:
    status = candidate.status

    if status == "snoozed":
        if _unsnoozed(candidate, run_ordinal):
            status = "accumulating"
        else:
            return LadderTransition(status="snoozed")

    if status == "rejected":
        if is_material_change(candidate, observation, thresholds=thresholds):
            return LadderTransition(
                status="accumulating",
                note=(
                    f"reopened: material change "
                    f"({observation.count} asks, {observation.n_users} users)"
                ),
                decision_action="reopen",
            )
        return LadderTransition(status="rejected")

    if status in _HUMAN_TERMINAL:
        return LadderTransition(status=status)

    if status == "stale":
        status = "accumulating"

    if status == "new":
        status = "accumulating" if len(recent_observations) >= 2 else "new"

    ready = readiness_met(
        recent_observations,
        sustained_runs=thresholds.rung1_sustained_runs,
        capability_run_count=capability_run_count,
    )
    if status == "accumulating" and ready:
        return LadderTransition(status="ready", set_ready_at=True)
    if status == "ready" and not ready:
        return LadderTransition(
            status="accumulating", note="evidence fell below the bar this run"
        )
    return LadderTransition(status=status)


def advance_unobserved(
    candidate: Candidate,
    *,
    run_ordinal: int,
    last_seen_ordinal: int,
    history_limit: int,
) -> LadderTransition | None:
    if _unsnoozed(candidate, run_ordinal):
        return LadderTransition(status="accumulating", note="snooze expired")
    if (
        candidate.status in _STALE_ELIGIBLE
        and run_ordinal - last_seen_ordinal >= history_limit
    ):
        return LadderTransition(
            status="stale", note=f"not seen for {history_limit} runs"
        )
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ladder.py -q`
Expected: PASS (whole file).

- [ ] **Step 5: File length + lint**

Run: `wc -l src/phoenix_scraper/ladder.py && uv run ruff check src/phoenix_scraper/ladder.py tests/test_ladder.py`
Expected: under 400 lines; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/ladder.py tests/test_ladder.py
git commit -m "feat: ladder.py — Rung-1 lifecycle state machine"
```

---

## Task 5: `ladder_run.py` — persist Rung 1, wired into the run

**Files:**
- Create: `src/phoenix_scraper/ladder_run.py`
- Modify: `src/phoenix_scraper/capability_run.py`
- Test: `tests/test_ladder_run.py` (create); `tests/test_capability_run.py` (append)

**Interfaces:**
- Consumes: Task 2 `Store` methods; Task 3 `detect_rung1` /
  `resolve_thresholds` / `Rung1Signal`; Task 4 `next_status` /
  `advance_unobserved`; `models.Candidate` / `CandidateObservation` /
  `CandidateDecision`.
- Produces:
  - `Rung1RunOutcome(_Frozen)` — `n_candidates: int` (candidates observed this
    run), `n_ready: int`, `notes: tuple[str, ...]`, `crossed: tuple[str, ...]`
    (candidate ids that met the bar this run but not last).
  - `update_rung1(store: Store, capability: Capability, *, run_id: str,
    run_ordinal: int, capability_run_count: int, observed_at: datetime, signals:
    list[Rung1Signal], thresholds: LadderThresholds, history_limit: int) ->
    Rung1RunOutcome` — for each signal: upsert the `candidates` row (create at
    `status='new'` on first sight, else carry status forward), write one
    `candidate_observations` row, run `next_status`, persist the new status +
    `ready_at` + any auto-`reopen` decision, prune observations to
    `history_limit`. Then for every OTHER non-terminal candidate of this
    capability + rung `'skill'` not in this run's signals, run
    `advance_unobserved` and persist.
  - Wiring: `run_capability_analysis` gains `rung1: Rung1RunOutcome` handling —
    after `efficiency` is computed and `run_id` is resolved, before building
    `CapabilityRun`. `run.n_rung1_candidates = outcome.n_candidates`; append
    `outcome.notes` to `run_notes` (status stays `ok` unless a scrape note
    already forced `partial` — ladder notes are informational, they do NOT force
    `partial`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ladder_run.py`:

```python
"""update_rung1: candidates + observations + state machine across runs."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from phoenix_scraper import ladder
from phoenix_scraper.config import Settings
from phoenix_scraper.ladder import Rung1Signal
from phoenix_scraper.ladder_run import update_rung1
from phoenix_scraper.models import Capability, CapabilityFilter

TS = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _cap(thresholds=None) -> Capability:
    return Capability(id="fobo", name="FOBO",
                      filter=CapabilityFilter(workflow_stage="fobo_recon"),
                      thresholds=thresholds or {})


def _sig(cid="aaa", *, count=20, n_users=5, met=True, subtype="new_skill",
         matched_skill=None, score=1.0) -> Rung1Signal:
    return Rung1Signal(
        cluster_id=cid, subtype=subtype, title=f"why {cid}", signature=f"sig {cid}",
        matched_skill=matched_skill, score=score, count=count, n_users=n_users,
        n_sessions=count, total_cost_usd=1.0, route_len_avg=3.0, long_route=False,
        met_evidence_bar=met,
    )


@pytest.fixture()
def t():
    return ladder.resolve_thresholds(_cap(), Settings(db_path="x.db"))


def _run(store, cap, t, signals, *, run_id, ordinal, count, at):
    return update_rung1(
        store, cap, run_id=run_id, run_ordinal=ordinal, capability_run_count=count,
        observed_at=at, signals=signals, thresholds=t, history_limit=20,
    )


class TestUpdateRung1:
    def test_creates_candidate_and_observation(self, tmp_store, t) -> None:
        out = _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 1
        c = tmp_store.get_candidate("fobo:s:aaa")
        assert c is not None and c.status == "new" and c.subtype == "new_skill"
        obs = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert len(obs) == 1 and obs.iloc[0]["count"] == 20

    def test_second_run_moves_to_accumulating(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r1", ordinal=1, count=1, at=TS)
        _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r2", ordinal=2, count=2,
             at=TS + timedelta(days=1))
        assert tmp_store.get_candidate("fobo:s:aaa").status == "accumulating"

    def test_sustained_streak_reaches_ready(self, tmp_store, t) -> None:
        for i in range(1, 7):
            _run(tmp_store, _cap(), t, [_sig("aaa", met=True)],
                 run_id=f"r{i}", ordinal=i, count=i, at=TS + timedelta(days=i))
        c = tmp_store.get_candidate("fobo:s:aaa")
        assert c.status == "ready" and c.ready_at is not None

    def test_crossed_threshold_flag(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t, [_sig("aaa", met=False)], run_id="r1", ordinal=1, count=1, at=TS)
        out = _run(tmp_store, _cap(), t, [_sig("aaa", met=True)], run_id="r2", ordinal=2,
                   count=2, at=TS + timedelta(days=1))
        assert "fobo:s:aaa" in out.crossed
        obs = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert obs.iloc[-1]["crossed_threshold"] == 1

    def test_unobserved_candidate_goes_stale(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r1", ordinal=1, count=1, at=TS)
        # 21 later runs without aaa
        for i in range(2, 23):
            _run(tmp_store, _cap(), t, [_sig("bbb")], run_id=f"r{i:02d}", ordinal=i,
                 count=i, at=TS + timedelta(days=i))
        assert tmp_store.get_candidate("fobo:s:aaa").status == "stale"

    def test_strengthen_subtype_recorded(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t,
             [_sig("ccc", subtype="strengthen_skill", matched_skill="fobo-triage", score=0.3)],
             run_id="r1", ordinal=1, count=1, at=TS)
        c = tmp_store.get_candidate("fobo:s:ccc")
        assert c.subtype == "strengthen_skill" and c.matched_skill == "fobo-triage"

    def test_notes_report_ready_and_new(self, tmp_store, t) -> None:
        out = _run(tmp_store, _cap(), t, [_sig("aaa"), _sig("bbb")],
                   run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 2
        assert any("Rung 1" in n for n in out.notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder_run.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoenix_scraper.ladder_run'`.

- [ ] **Step 3: Create `ladder_run.py`**

Create `src/phoenix_scraper/ladder_run.py`:

```python
"""Persist a run's Rung-1 candidates: upsert `candidates`, write one
`candidate_observations` row each, run the §10.1 state machine, and advance the
lifecycle for candidates not seen this run. Store-touching companion to the pure
`ladder.py`.

Rung 2 is Phase D — this module is Rung-1 only.
"""

from datetime import datetime

from .ladder import (
    LadderThresholds,
    Rung1Signal,
    advance_unobserved,
    next_status,
)
from .models import Candidate, CandidateDecision, CandidateObservation, _Frozen
from .storage import Store


class Rung1RunOutcome(_Frozen):
    n_candidates: int = 0
    n_ready: int = 0
    notes: tuple[str, ...] = ()
    crossed: tuple[str, ...] = ()


def _candidate_id(capability_id: str, cluster_id: str) -> str:
    return f"{capability_id}:s:{cluster_id}"


def _observation(signal: Rung1Signal, cid: str, run_id: str, observed_at: datetime,
                 crossed: bool) -> CandidateObservation:
    return CandidateObservation(
        candidate_id=cid,
        run_id=run_id,
        observed_at=observed_at,
        count=signal.count,
        n_users=signal.n_users,
        n_sessions=signal.n_sessions,
        total_cost_usd=signal.total_cost_usd,
        score=signal.score,
        signals={
            "subtype": signal.subtype,
            "route_len_avg": signal.route_len_avg,
            "long_route": signal.long_route,
        },
        met_evidence_bar=signal.met_evidence_bar,
        crossed_threshold=crossed,
    )


def update_rung1(
    store: Store,
    capability: "Capability",
    *,
    run_id: str,
    run_ordinal: int,
    capability_run_count: int,
    observed_at: datetime,
    signals: list[Rung1Signal],
    thresholds: LadderThresholds,
    history_limit: int,
) -> Rung1RunOutcome:
    seen_ids: set[str] = set()
    n_ready = 0
    crossed_ids: list[str] = []

    for signal in signals:
        cid = _candidate_id(capability.id, signal.cluster_id)
        seen_ids.add(cid)
        existing = store.get_candidate(cid)

        prev_recent = store.recent_candidate_observations(cid, 1)
        prev_met = prev_recent[0].met_evidence_bar if prev_recent else False
        crossed = signal.met_evidence_bar and not prev_met
        if crossed:
            crossed_ids.append(cid)

        obs = _observation(signal, cid, run_id, observed_at, crossed)
        store.record_candidate_observation(obs)
        recent = store.recent_candidate_observations(cid, thresholds.rung1_sustained_runs)

        if existing is None:
            candidate = Candidate(
                candidate_id=cid,
                capability_id=capability.id,
                rung="skill",
                subtype=signal.subtype,
                cluster_id=signal.cluster_id,
                title=signal.title,
                signature=signal.signature,
                matched_skill=signal.matched_skill,
                status="new",
                first_seen_run_id=run_id,
                first_seen_at=observed_at,
                last_seen_run_id=run_id,
                last_seen_at=observed_at,
            )
        else:
            candidate = existing.model_copy(update={
                "subtype": signal.subtype,
                "matched_skill": signal.matched_skill,
                "title": signal.title,
                "signature": signal.signature,
                "last_seen_run_id": run_id,
                "last_seen_at": observed_at,
            })

        transition = next_status(
            candidate, obs, recent,
            run_ordinal=run_ordinal,
            capability_run_count=capability_run_count,
            thresholds=thresholds,
        )
        updates: dict = {
            "status": transition.status,
            "current_evidence": {
                "count": signal.count, "n_users": signal.n_users,
                "score": signal.score, "subtype": signal.subtype,
            },
        }
        if transition.set_ready_at and candidate.ready_at is None:
            updates["ready_at"] = observed_at
        store.upsert_candidate(candidate.model_copy(update=updates))

        if transition.decision_action == "reopen":
            store.record_candidate_decision(CandidateDecision(
                candidate_id=cid, run_id=run_id, action="reopen",
                actor="pheonix", note=transition.note or "material change",
                created_at=observed_at,
            ))
        if transition.status == "ready":
            n_ready += 1
        store.prune_candidate_observations(cid, history_limit)

    _advance_unobserved(store, capability.id, run_id, run_ordinal, seen_ids, history_limit)

    notes: list[str] = []
    if signals:
        notes.append(
            f"Rung 1: {len(signals)} candidates observed "
            f"({n_ready} ready, {len(crossed_ids)} crossed the bar)"
        )
    return Rung1RunOutcome(
        n_candidates=len(signals),
        n_ready=n_ready,
        notes=tuple(notes),
        crossed=tuple(crossed_ids),
    )


def _advance_unobserved(
    store: Store,
    capability_id: str,
    run_id: str,
    run_ordinal: int,
    seen_ids: set[str],
    history_limit: int,
) -> None:
    frame = store.candidates_frame(capability_id, rung="skill")
    for row in frame.to_dict("records"):
        cid = row["candidate_id"]
        if cid in seen_ids:
            continue
        candidate = store.get_candidate(cid)
        if candidate is None:
            continue
        last_seen_ordinal = store.capability_run_ordinal(
            capability_id, candidate.last_seen_run_id
        )
        transition = advance_unobserved(
            candidate,
            run_ordinal=run_ordinal,
            last_seen_ordinal=last_seen_ordinal,
            history_limit=history_limit,
        )
        if transition is not None and transition.status != candidate.status:
            store.upsert_candidate(candidate.model_copy(update={"status": transition.status}))
```

Add `from .models import Capability` to the import block (the string annotation
`"Capability"` can then be unquoted — keep it consistent with the file, so
**unquote it**: `capability: Capability`).

- [ ] **Step 4: Run the `ladder_run` tests**

Run: `uv run pytest tests/test_ladder_run.py -q`
Expected: PASS.

- [ ] **Step 5: Wire into `run_capability_analysis`**

Append to the test file `tests/test_capability_run.py` (inside
`TestRunCapabilityAnalysis`):

```python
    def test_rung1_candidates_created_by_a_run(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        runs = seeded_store.capability_runs_frame("fobo")
        # sample_spans has 8 near-identical fobo_recon prompts -> one strong cluster,
        # no catalog skill demonstrates it -> one new_skill candidate.
        assert runs.iloc[0]["n_rung1_candidates"] >= 1
        cands = seeded_store.candidates_frame("fobo", rung="skill")
        assert len(cands) >= 1
        assert set(cands["status"]) <= {"new", "accumulating"}

    def test_second_run_advances_candidate_status(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        run_capability_analysis(seeded_store, settings, cap, now=NOW - timedelta(days=1))
        run_capability_analysis(seeded_store, settings, cap, now=NOW)
        cands = seeded_store.candidates_frame("fobo", rung="skill")
        assert "accumulating" in set(cands["status"])
```

In `src/phoenix_scraper/capability_run.py`:

1. Add imports:
```python
from .ladder import detect_rung1, resolve_thresholds
from .ladder_run import update_rung1
```

2. The current constructor computes `status="partial" if run_notes else "ok"`.
   Ladder notes must NOT force `partial` — only scrape notes do. So **first**,
   change that line to key off the original `notes` argument:

```python
    scrape_partial = bool(notes)   # add near the top, right after run_notes = list(notes or [])
```
   and later `status="partial" if scrape_partial else "ok"`.

3. In `run_capability_analysis`, after `efficiency = cluster_efficiency(...)` and
   after `run_id` / `previous_run_id` are resolved but **before** the
   `run = CapabilityRun(...)` construction, insert:

```python
    _existing_ordinal = store.capability_run_ordinal(capability.id, run_id)
    this_ordinal = _existing_ordinal or (store.capability_run_ordinal(capability.id) + 1)
    run_count = max(this_ordinal, store.capability_run_ordinal(capability.id))

    thresholds = resolve_thresholds(capability, settings)
    rung1_signals = detect_rung1(
        list(clusters), list(matches), annotated, efficiency, thresholds=thresholds
    )
    rung1 = update_rung1(
        store, capability,
        run_id=run_id,
        run_ordinal=this_ordinal,
        capability_run_count=run_count,
        observed_at=started_at,
        signals=rung1_signals,
        thresholds=thresholds,
        history_limit=settings.run_history_limit,
    )
    run_notes.extend(rung1.notes)
```

   **Ordinal note:** for a fresh run the `capability_runs` row is not written
   yet, so `capability_run_ordinal(run_id)` returns 0 and `this_ordinal` falls
   back to `count + 1`. On `--replace-today` the row already exists so
   `capability_run_ordinal(run_id)` is this run's real ordinal.

4. In the `CapabilityRun(...)` constructor, set:
```python
        n_rung1_candidates=rung1.n_candidates,
        status="partial" if scrape_partial else "ok",
```
   (leave `n_rung2_candidates` defaulting to 0. `notes=tuple(run_notes)` still
   carries both scrape and ladder notes.)

- [ ] **Step 6: Run the wiring tests**

Run: `uv run pytest tests/test_capability_run.py tests/test_ladder_run.py -q`
Expected: PASS.

- [ ] **Step 7: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~659 → ~675).

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/ladder_run.py src/phoenix_scraper/capability_run.py \
  tests/test_ladder_run.py tests/test_capability_run.py
git commit -m "feat: ladder_run.update_rung1 — persist Rung-1 candidates in the run"
```

---

## Task 6: `artifacts.py` — Rung-1 skill draft + strengthen block + promote

**Files:**
- Create: `src/phoenix_scraper/artifacts.py`
- Test: `tests/test_artifacts.py` (create)

**Interfaces:**
- Consumes: `models.Candidate`, `models.SkillEntry`, `models.Capability`;
  `skills.distinctive_words`; `skill_coverage._suggested_keywords` /
  `_yaml_block` (module-private — import with the underscore, they are stable
  helpers this module legitimately reuses per §8.3); `taxonomy.suggest_level`.
- Produces:
  - `slugify(name: str) -> str` — kebab-case, `[a-z0-9-]`, collapse repeats.
  - `dedupe_path(directory: Path, stem: str, suffix: str = ".md") -> Path` —
    `stem.md`, then `stem-2.md`, … first that does not exist.
  - `render_new_skill_md(candidate: Candidate, *, capability: Capability,
    member_prompts: list[str], today: date) -> tuple[str, str]` — returns
    `(filename, markdown)` for a `subtype='new_skill'` candidate. Frontmatter per
    §8.3 (`status: draft`, `source_candidate`, `evidence`), body with the
    scaffold comment + `## When to use` + `## Procedure\n1. TODO`.
  - `render_strengthen_block(candidate: Candidate, skill: SkillEntry, *,
    member_prompts: list[str], member_signatures: list[str]) -> tuple[str, str]`
    — returns `(target_source_file, yaml_block)` reusing
    `skill_coverage._yaml_block`.
  - `promote_candidate(store: Store, capability: Capability, candidate: Candidate,
    *, now: datetime, actor: str, dry_run: bool = False) -> PromoteResult` —
    resolves member prompts from `capability_cluster_members` +
    `spans_frame`; for `new_skill` writes
    `<capabilities_dir>/<cap>/skills/<name>.md` (dedup-collided); for
    `strengthen_skill` writes **nothing**, returns the block + target path.
    Records a `promote` decision and, when not `dry_run`, upserts the candidate
    to `status='promoted'`, `promoted_at`, `promoted_artifact_paths`.
  - `PromoteResult(_Frozen)` — `paths: tuple[str, ...]`, `contents: tuple[tuple[str,
    str], ...]` (path, body), `wrote_files: bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_artifacts.py`:

```python
"""Rung-1 artifact rendering + promote."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from phoenix_scraper import artifacts
from phoenix_scraper import capability as cap_mod
from phoenix_scraper.models import Candidate, CapabilityFilter, SkillEntry

TS = datetime(2026, 9, 8, 12, tzinfo=UTC)


def _cand(subtype="new_skill", **over) -> Candidate:
    base = dict(
        candidate_id="fobo:s:abc123", capability_id="fobo", rung="skill",
        subtype=subtype, cluster_id="abc123",
        title="why is there a recon break of 100k on the credit book",
        signature="why recon break of <num> on <book>",
        matched_skill="fobo-triage" if subtype == "strengthen_skill" else None,
        status="accepted", first_seen_run_id="r1", first_seen_at=TS,
        last_seen_run_id="r6", last_seen_at=TS,
        current_evidence={"count": 214, "n_users": 7},
    )
    base.update(over)
    return Candidate(**base)


class TestRendering:
    def test_slugify(self) -> None:
        assert artifacts.slugify("Recon Break Explain!") == "recon-break-explain"

    def test_dedupe_path(self, tmp_path: Path) -> None:
        (tmp_path / "x.md").write_text("", encoding="utf-8")
        assert artifacts.dedupe_path(tmp_path, "x").name == "x-2.md"

    def test_new_skill_md_has_frontmatter_and_scaffold(self) -> None:
        name, md = artifacts.render_new_skill_md(
            _cand(), capability=_capability(), member_prompts=[
                "why is there a recon break of 100k on the credit book",
                "explain the fx recon break on EURUSD_LDN",
            ], today=date(2026, 9, 8),
        )
        assert name.endswith(".md")
        assert "status: draft" in md
        assert "source_candidate: fobo:s:abc123" in md
        assert "## Procedure" in md and "1. TODO" in md
        assert "example_prompts:" in md

    def test_strengthen_block_targets_the_matched_skill(self) -> None:
        skill = SkillEntry(name="fobo-triage", description="Triage recon breaks.",
                           example_prompts=("existing one",), source="skill_md",
                           path="capabilities/fobo/skills/fobo-triage.md")
        target, block = artifacts.render_strengthen_block(
            _cand("strengthen_skill"), skill,
            member_prompts=["why is there a recon break of 100k on the credit book"],
            member_signatures=["why recon break of <num> on <book>"],
        )
        assert target == "capabilities/fobo/skills/fobo-triage.md"
        assert "```yaml" in block and "example_prompts:" in block


def _capability():
    return cap_mod.Capability(
        id="fobo", name="FOBO", filter=CapabilityFilter(workflow_stage="fobo_recon"),
    )


class TestPromote:
    @pytest.fixture()
    def wired(self, seeded_store, tmp_path, settings):
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "fobo", cap_filter=CapabilityFilter(workflow_stage="fobo_recon")
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        from phoenix_scraper.capability_run import run_capability_analysis
        run_capability_analysis(seeded_store, s, cap,
                                now=datetime(2026, 7, 21, 12, tzinfo=UTC))
        cid = seeded_store.candidates_frame("fobo", rung="skill").iloc[0]["candidate_id"]
        cand = seeded_store.get_candidate(cid).model_copy(update={"status": "accepted"})
        seeded_store.upsert_candidate(cand)
        return seeded_store, s, cap, cand

    def test_promote_new_skill_writes_a_draft_file(self, wired) -> None:
        store, s, cap, cand = wired
        result = artifacts.promote_candidate(store, cap, cand, now=TS, actor="alice",
                                             settings=s)
        assert result.wrote_files is True
        assert len(result.paths) == 1
        written = Path(result.paths[0])
        assert written.exists() and written.parent.name == "skills"
        assert store.get_candidate(cand.candidate_id).status == "promoted"
        decisions = store.candidate_decisions_frame(cand.candidate_id)
        assert "promote" in list(decisions["action"])

    def test_dry_run_writes_nothing(self, wired) -> None:
        store, s, cap, cand = wired
        result = artifacts.promote_candidate(store, cap, cand, now=TS, actor="a",
                                             settings=s, dry_run=True)
        assert result.wrote_files is False
        assert store.get_candidate(cand.candidate_id).status == "accepted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_artifacts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoenix_scraper.artifacts'`.

- [ ] **Step 3: Create `artifacts.py`**

Create `src/phoenix_scraper/artifacts.py`:

```python
"""Render (and, on promote, write) the ladder's draft artifacts.

Rung 1: `skills/<name>.md` for a `new_skill` candidate; a paste-ready
`example_prompts` / `keywords` block for a `strengthen_skill` candidate (no file
written — the target is a hand-authored skill). Rung-2 artifacts are Phase D.
Draft files carry `status: draft`; pheonix never edits hand-authored files.
"""

import re
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import Settings
from .models import Candidate, Capability, QueryFilters, SkillEntry, _Frozen
from .skill_coverage import _suggested_keywords, _yaml_block
from .skills import distinctive_words
from .storage import Store
from .taxonomy import suggest_level

_MEMBER_PROMPT_LIMIT = 8
_PLACEHOLDER = re.compile(r"<[a-z]+>")


class PromoteResult(_Frozen):
    paths: tuple[str, ...] = ()
    contents: tuple[tuple[str, str], ...] = ()
    wrote_files: bool = False


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return re.sub(r"-{2,}", "-", slug) or "skill"


def dedupe_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    candidate = directory / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def _keywords(candidate: Candidate) -> list[str]:
    words = [w for w in distinctive_words(candidate.signature) if not _PLACEHOLDER.match(f"<{w}>")]
    name_words = set(distinctive_words(candidate.title))
    return [w for w in words if w not in name_words][:8]


def render_new_skill_md(
    candidate: Candidate,
    *,
    capability: Capability,
    member_prompts: list[str],
    today: date,
) -> tuple[str, str]:
    stem = slugify(candidate.signature.replace("<", "").replace(">", "")) or slugify(candidate.title)
    level, asset_class, _cap = suggest_level(candidate.title)
    ev = candidate.current_evidence
    front = {
        "name": stem,
        "description": f"Answer: {candidate.title.strip()[:120]}",
        "level": level if level != "asset_class" else "capability",
        "capability": capability.id,
        "keywords": _keywords(candidate) or distinctive_words(candidate.title)[:6],
        "example_prompts": member_prompts[:_MEMBER_PROMPT_LIMIT],
        "status": "draft",
        "source_candidate": candidate.candidate_id,
        "evidence": {
            "first_seen": candidate.first_seen_at.date().isoformat(),
            "asks": int(ev.get("count", 0)),
            "users": int(ev.get("n_users", 0)),
        },
    }
    if asset_class:
        front["asset_class"] = asset_class
    dumped = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=10**6).rstrip()
    body = (
        f"---\n{dumped}\n---\n\n"
        f"# {stem}\n\n"
        f"<!-- Draft scaffolded by pheonix from candidate {candidate.candidate_id}.\n"
        f"     Fill in the procedure, then set status: active. pheonix stops\n"
        f"     proposing this candidate once a skill matches and demonstrates it. -->\n\n"
        f"## When to use\n"
        f"Recurring across {int(ev.get('n_users', 0))} analysts; "
        f"{int(ev.get('count', 0))} asks since {candidate.first_seen_at.date().isoformat()}.\n\n"
        f"## Procedure\n1. TODO\n"
    )
    return f"{stem}.md", body


def render_strengthen_block(
    candidate: Candidate,
    skill: SkillEntry,
    *,
    member_prompts: list[str],
    member_signatures: list[str],
) -> tuple[str, str]:
    keywords = _suggested_keywords(member_signatures, skill)
    block = _yaml_block(skill, member_prompts[:_MEMBER_PROMPT_LIMIT], keywords)
    target = skill.path or f"(skill '{skill.name}' — source file unknown)"
    return target, block


def _member_prompts(store: Store, capability: Capability, candidate: Candidate) -> list[str]:
    f = capability.filter
    frame = store.spans_frame(QueryFilters(
        project=f.project, workflow_stage=f.workflow_stage, asset_class=f.asset_class,
        model_name=f.model_name, search=f.search, limit=5000,
    ))
    if frame.empty or "input_text" not in frame.columns:
        return [candidate.title]
    texts = [
        str(t).strip()
        for t in frame["input_text"].tolist()
        if str(t).strip()
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for t in texts:
        key = t.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique[:_MEMBER_PROMPT_LIMIT] or [candidate.title]


def promote_candidate(
    store: Store,
    capability: Capability,
    candidate: Candidate,
    *,
    now: datetime,
    actor: str,
    settings: Settings,
    dry_run: bool = False,
) -> PromoteResult:
    prompts = _member_prompts(store, capability, candidate)
    cap_dir = Path(settings.capabilities_dir) / capability.id
    if candidate.subtype == "strengthen_skill":
        from .skills import load_all_skills
        skills = {s.name: s for s in load_all_skills(settings)}
        skill = skills.get(candidate.matched_skill or "")
        if skill is None:
            skill = SkillEntry(name=candidate.matched_skill or "unknown",
                               path=str(cap_dir / "skills" / f"{candidate.matched_skill}.md"))
        target, block = render_strengthen_block(
            candidate, skill, member_prompts=prompts, member_signatures=[candidate.signature],
        )
        paths = (target,)
        contents = ((target, block),)
        wrote = False
    else:
        skills_dir = cap_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        filename, body = render_new_skill_md(
            candidate, capability=capability, member_prompts=prompts, today=now.date(),
        )
        out_path = dedupe_path(skills_dir, filename[:-3])
        contents = ((str(out_path), body),)
        if not dry_run:
            out_path.write_text(body, encoding="utf-8")
        paths = (str(out_path),)
        wrote = not dry_run

    if not dry_run:
        store.record_candidate_decision_now(candidate.candidate_id, "promote", actor, now)
        store.upsert_candidate(candidate.model_copy(update={
            "status": "promoted",
            "promoted_at": now,
            "promoted_artifact_paths": paths,
            "decided_by": actor,
            "decided_at": now,
        }))
    return PromoteResult(paths=paths, contents=contents, wrote_files=wrote)
```

**Helper on `Store`** (add to `storage.py`, `# ---- ladder candidates` section,
after `record_candidate_decision`): a convenience the CLI and `artifacts` both
use so the `CandidateDecision` construction lives in one place:

```python
    def record_candidate_decision_now(
        self, candidate_id: str, action: str, actor: str, when: datetime,
        *, note: str = "", run_id: str | None = None,
    ) -> int:
        return self.record_candidate_decision(CandidateDecision(
            candidate_id=candidate_id, run_id=run_id, action=action, actor=actor,
            note=note, created_at=when,
        ))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_artifacts.py -q`
Expected: PASS.

- [ ] **Step 5: File length + lint**

Run: `wc -l src/phoenix_scraper/artifacts.py && uv run ruff check src/phoenix_scraper/artifacts.py src/phoenix_scraper/storage.py tests/test_artifacts.py`
Expected: under 400 lines; ruff clean. (`_suggested_keywords` / `_yaml_block`
are underscore-imported from `skill_coverage` deliberately — if ruff flags the
private import, add `# noqa: PLC2701` — but `PLC` is not in the selected rules,
so it will not.)

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/artifacts.py src/phoenix_scraper/storage.py tests/test_artifacts.py
git commit -m "feat: artifacts.py — Rung-1 draft skill / strengthen block + promote"
```

---

## Task 7: CLI — `pheonix candidates | decide | promote`

**Files:**
- Modify: `src/phoenix_scraper/cli.py`
- Test: `tests/test_candidate_cli.py` (create)

**Interfaces:**
- Consumes: `Store.candidates_frame` / `get_candidate` /
  `record_candidate_decision_now`; `artifacts.promote_candidate`;
  `capability.load_capability`; the §10.1 decision transitions.
- Produces:
  - `pheonix candidates <cap_id> [--rung skill|deterministic] [--status <s>]
    [--all] [--db] [--capabilities-dir]` — the board, grouped by status; rejected
    + snoozed hidden unless `--all` or an explicit `--status`.
  - `pheonix decide <candidate_id> --action accept|reject|snooze|reopen
    [--actor <name>] [--note <text>] [--snooze-runs N] [--db] [--capabilities-dir]`
    — appends a decision, applies the transition (§10.3). Invalid transition →
    exit 1 with the current status. `--actor` defaults to
    `Settings.operator_name`.
  - `pheonix promote <candidate_id> [--accept] [--actor] [--dry-run] [--db]
    [--capabilities-dir]` — `artifacts.promote_candidate`; prints the paths and
    (for strengthen / `--dry-run`) the block. `--accept` allows `ready → promoted`
    in one step.

- [ ] **Step 1: Write the failing test**

Create `tests/test_candidate_cli.py`:

```python
"""CLI tests for pheonix candidates / decide / promote."""

from pathlib import Path

from typer.testing import CliRunner, Result

from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.storage import Store

runner = CliRunner()


def _invoke(*args: str) -> Result:
    return runner.invoke(cli_app, list(args))


def _seed(tmp_path: Path):
    db, caps = tmp_path / "c.db", tmp_path / "caps"
    assert _invoke("demo", "--db", str(db), "--export-dir", str(tmp_path / "e"),
                   "--sessions", "24").exit_code == 0
    common = ("--capabilities-dir", str(caps), "--db", str(db))
    assert _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common).exit_code == 0
    assert _invoke("run", "--capability", "fobo", *common).exit_code == 0
    return db, common


def _first_candidate(db: Path) -> str:
    store = Store(db)
    try:
        return store.candidates_frame("fobo").iloc[0]["candidate_id"]
    finally:
        store.close()


class TestCandidatesVerb:
    def test_lists_candidates(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        r = _invoke("candidates", "fobo", *common)
        assert r.exit_code == 0, r.output
        assert "fobo:s:" in r.output

    def test_empty_capability(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        _invoke("capability", "new", "empty", *common)
        r = _invoke("candidates", "empty", *common)
        assert r.exit_code == 0 and "no candidates" in r.output.lower()


class TestDecide:
    def test_reject_then_status_changes(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        r = _invoke("decide", cid, "--action", "reject", "--actor", "alice",
                    "--note", "covered elsewhere", *common)
        assert r.exit_code == 0, r.output
        store = Store(db)
        try:
            assert store.get_candidate(cid).status == "rejected"
            assert list(store.candidate_decisions_frame(cid)["action"]) == ["reject"]
        finally:
            store.close()

    def test_invalid_transition_exits_1(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        # a brand-new / accumulating candidate cannot be 'accept'ed (only ready can)
        r = _invoke("decide", cid, "--action", "accept", "--actor", "a", *common)
        assert r.exit_code == 1
        assert "ready" in r.output.lower() or "cannot" in r.output.lower()


class TestPromote:
    def test_promote_dry_run_prints_without_writing(self, tmp_path: Path) -> None:
        db, common = _seed(tmp_path)
        cid = _first_candidate(db)
        store = Store(db)
        try:
            store.upsert_candidate(store.get_candidate(cid).model_copy(
                update={"status": "accepted"}))
        finally:
            store.close()
        r = _invoke("promote", cid, "--dry-run", "--actor", "a", *common)
        assert r.exit_code == 0, r.output
        store = Store(db)
        try:
            assert store.get_candidate(cid).status == "accepted"
        finally:
            store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_candidate_cli.py -q`
Expected: FAIL — `candidates` is not a command (`exit_code == 2`).

- [ ] **Step 3: Add option singletons + imports**

In `cli.py`, add to the package imports (next to `from . import capability_run as
capability_run_mod`):
```python
from . import artifacts as artifacts_mod
from . import ladder as ladder_mod
```
(only `artifacts_mod` is strictly needed for Task 7; `ladder_mod` is unused here
— **do not add it** unless a later step needs it. Add only `artifacts_mod`.)

Near the Phase B `Run*Opt` singletons, add:
```python
CandidateRungOpt = typer.Option(None, "--rung", help="skill | deterministic")
CandidateStatusOpt = typer.Option(None, "--status", help="Filter to one status.")
CandidateAllOpt = typer.Option(False, "--all", help="Include rejected + snoozed.")
DecisionActionOpt = typer.Option(..., "--action", help="accept | reject | snooze | reopen")
ActorOpt = typer.Option(None, "--actor", help="Who is deciding (default: PHEONIX_OPERATOR_NAME).")
DecisionNoteOpt = typer.Option("", "--note", help="Why.")
SnoozeRunsOpt = typer.Option(3, "--snooze-runs", help="Runs to snooze for.")
PromoteAcceptOpt = typer.Option(False, "--accept", help="Allow ready -> promoted in one step.")
DryRunOpt = typer.Option(False, "--dry-run", help="Render without writing.")
CandidateIdArg = typer.Argument(..., help="Candidate id, e.g. fobo:s:abc123.")
```

- [ ] **Step 4: Implement `pheonix candidates`**

Append after the Phase B `capability_runs` command (inside the `capability_app`?
No — `candidates` is a top-level verb per the spec, like `run`). Add after the
`run` command, before `_echo_capability_run`:

```python
_HIDDEN_BY_DEFAULT = frozenset({"rejected", "snoozed", "stale"})


@app.command()
def candidates(
    cap_id: str = CapIdArg,
    rung: str | None = CandidateRungOpt,
    status: str | None = CandidateStatusOpt,
    show_all: bool = CandidateAllOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """The ladder board for a capability: candidates grouped by status."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        frame = store.candidates_frame(cap_id, rung=rung, status=status)
    if not len(frame):
        typer.echo(f"No candidates for '{cap_id}'.")
        return
    rows = frame.to_dict("records")
    if status is None and not show_all:
        rows = [r for r in rows if r["status"] not in _HIDDEN_BY_DEFAULT]
    if not rows:
        typer.echo("No active candidates (rejected/snoozed/stale hidden — use --all).")
        return
    by_status: dict[str, list[dict]] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)
    for st, group in by_status.items():
        typer.echo(f"\n{st.upper()}  ({len(group)})")
        for r in group:
            ev = json.loads(r["current_evidence_json"] or "{}")
            typer.echo(
                f"  {r['candidate_id']:<28} {r['subtype']:<16} "
                f"{ev.get('count', 0):>4} asks / {ev.get('n_users', 0)} users  "
                f"{str(r['title'])[:60]}"
            )
```

`json` is already imported in `cli.py`? Check — it is **not**. Add `import json`
to `cli.py`'s stdlib imports (top of file, after `import logging`).

- [ ] **Step 5: Implement `pheonix decide`**

The decision transition table (§10.1) as a helper, then the command:

```python
_DECISION_TRANSITIONS = {
    "accept": ({"ready"}, "accepted"),
    "reject": ({"accumulating", "ready", "new"}, "rejected"),
    "snooze": ({"accumulating", "ready", "new"}, "snoozed"),
    "reopen": ({"rejected", "snoozed", "stale"}, "accumulating"),
}


@app.command()
def decide(
    candidate_id: str = CandidateIdArg,
    action: str = DecisionActionOpt,
    actor: str | None = ActorOpt,
    note: str = DecisionNoteOpt,
    snooze_runs: int = SnoozeRunsOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Record a human decision on a candidate and apply the transition."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    who = actor or settings.operator_name or "unknown"
    if action not in _DECISION_TRANSITIONS:
        typer.secho(f"Unknown action {action!r}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    allowed, target = _DECISION_TRANSITIONS[action]
    now = datetime.now(UTC)
    with _open_store(settings) as store:
        candidate = store.get_candidate(candidate_id)
        if candidate is None:
            typer.secho(f"No candidate {candidate_id!r}.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if candidate.status not in allowed:
            typer.secho(
                f"Cannot {action} a candidate in status {candidate.status!r} "
                f"(allowed from: {', '.join(sorted(allowed))}).",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1)
        store.record_candidate_decision_now(
            candidate_id, action, who, now, note=note,
        )
        updates: dict = {"status": target, "decided_by": who, "decided_at": now}
        if action == "reject":
            updates["dismiss_reason"] = note
            updates["current_evidence"] = {
                **candidate.current_evidence,
                "count_at_rejection": candidate.current_evidence.get("count", 0),
                "n_users_at_rejection": candidate.current_evidence.get("n_users", 0),
            }
        if action == "snooze":
            ordinal = store.capability_run_ordinal(candidate.capability_id)
            updates["snooze_until_run"] = ordinal + snooze_runs
        store.upsert_candidate(candidate.model_copy(update=updates))
    typer.echo(f"{candidate_id}: {candidate.status} -> {target}  (by {who})")
```

- [ ] **Step 6: Implement `pheonix promote`**

```python
@app.command()
def promote(
    candidate_id: str = CandidateIdArg,
    accept: bool = PromoteAcceptOpt,
    actor: str | None = ActorOpt,
    dry_run: bool = DryRunOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Write the draft artifact for an accepted (or --accept a ready) candidate."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    who = actor or settings.operator_name or "unknown"
    now = datetime.now(UTC)
    with _open_store(settings) as store:
        candidate = store.get_candidate(candidate_id)
        if candidate is None:
            typer.secho(f"No candidate {candidate_id!r}.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if candidate.status == "ready" and accept and not dry_run:
            candidate = candidate.model_copy(update={"status": "accepted"})
            store.upsert_candidate(candidate)
        if candidate.status != "accepted" and not dry_run:
            typer.secho(
                f"Candidate is {candidate.status!r}; accept it first "
                f"(or pass --accept for a ready candidate).",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1)
        try:
            cap = capability_mod.load_capability(settings.capabilities_dir,
                                                 candidate.capability_id)
        except (ValueError, FileNotFoundError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        result = artifacts_mod.promote_candidate(
            store, cap, candidate, now=now, actor=who, settings=settings, dry_run=dry_run,
        )
    for path, body in result.contents:
        typer.echo(f"\n--- {path} ---")
        typer.echo(body)
    typer.echo("" if dry_run else f"\nWrote {len(result.paths)} artifact(s).")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_candidate_cli.py -q`
Expected: PASS.

- [ ] **Step 8: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~675 → ~685).

- [ ] **Step 9: Commit**

```bash
git add src/phoenix_scraper/cli.py tests/test_candidate_cli.py
git commit -m "feat: pheonix candidates / decide / promote"
```

---

## Task 8: Docs — CONTRACTS.md + README.md

**Files:**
- Modify: `CONTRACTS.md`
- Modify: `README.md`

- [ ] **Step 1: CONTRACTS.md — `ladder.py` + `ladder_run.py` + `artifacts.py` + new Store methods**

After the `## capability_run.py` block (Phase B), add three blocks in the file's
existing style (`## name` + a ```python signature block + a short paragraph):

```
## ladder.py  (pure: threshold resolution, Rung-1 detection, §10.1 state machine)
def resolve_thresholds(capability, settings) -> LadderThresholds
def detect_rung1(clusters, matches, annotated, efficiency, *, thresholds) -> list[Rung1Signal]
    # one signal per in-scope cluster at/above the creation floor
    # (max(3, rung1_min_count//3)) that is new_skill (no match >= skill_match_threshold)
    # or strengthen_skill (matched but coverage_score < skill_coverage_threshold).
    # score = gap strength; met_evidence_bar = n_users>=rung1_min_users AND count>=rung1_min_count.
def readiness_met(recent_observations, *, sustained_runs, capability_run_count) -> bool
def is_material_change(candidate, observation, *, thresholds) -> bool
def next_status(candidate, observation, recent_observations, *, run_ordinal,
        capability_run_count, thresholds) -> LadderTransition        # observed this run
def advance_unobserved(candidate, *, run_ordinal, last_seen_ordinal,
        history_limit) -> LadderTransition | None                    # not observed this run

## ladder_run.py  (store-touching: persist a run's Rung-1 candidates)
def update_rung1(store, capability, *, run_id, run_ordinal, capability_run_count,
        observed_at, signals, thresholds, history_limit) -> Rung1RunOutcome
    # upsert candidates (create at 'new'), one observation row each, run next_status,
    # persist status/ready_at + auto 'reopen' decision, prune observations to
    # history_limit; then advance_unobserved for every other rung-'skill' candidate.

## artifacts.py  (render / write the ladder's draft artifacts; never edits hand-authored files)
def render_new_skill_md(candidate, *, capability, member_prompts, today) -> (filename, markdown)
def render_strengthen_block(candidate, skill, *, member_prompts, member_signatures) -> (target_path, yaml_block)
def promote_candidate(store, capability, candidate, *, now, actor, settings,
        dry_run=False) -> PromoteResult
    # new_skill -> writes capabilities/<cap>/skills/<name>.md (status: draft, dedup-collided);
    # strengthen_skill -> writes nothing, returns the paste block + target path.
    # Records a 'promote' decision; sets status='promoted' + promoted_artifact_paths.
```

Then extend the `## storage.py` (or the capabilities block) list with the new
methods: `upsert_candidate`, `get_candidate`, `candidates_frame(cap, *, rung,
status)`, `record_candidate_observation`, `candidate_observations_frame`,
`recent_candidate_observations(cid, n)`, `record_candidate_decision ->
id`, `record_candidate_decision_now`, `candidate_decisions_frame`,
`capability_run_ordinal(cap, run_id=None)`, `prune_candidate_observations(cid,
keep)`. And note the three new tables: `candidates`, `candidate_observations`,
`candidate_decisions`.

Update the `## cli.py` command line: append `, candidates (<id> --rung --status
--all), decide (<cid> --action --actor --note --snooze-runs), promote (<cid>
--accept --dry-run)`.

- [ ] **Step 2: README.md — "The promotion ladder" section**

After the `## Daily runs` section (Phase B) and before `## Dashboard UI`, insert
`## The promotion ladder` (a heading, two short paragraphs, one fenced `bash`
block — no nested fences):

> `## The promotion ladder`
>
> Each `pheonix run` also updates the capability's **Rung-1 candidates** — an
> in-scope prompt cluster that recurs across users and either has no skill
> (`new_skill`) or matched one that doesn't demonstrate it (`strengthen_skill`).
> A candidate is created once it clears a low floor, gathers an evidence trend
> run over run, and reaches `ready` after `rung1_sustained_runs` (default 5)
> consecutive runs meeting the bar (`rung1_min_users` users AND `rung1_min_count`
> asks).
>
> ```bash
> pheonix candidates fobo                       # the board, active candidates
> pheonix candidates fobo --all                 # include rejected / snoozed / stale
> pheonix decide fobo:s:abc123 --action reject --actor you --note "covered by X"
> pheonix decide fobo:s:abc123 --action snooze --snooze-runs 5 --actor you
> pheonix promote fobo:s:abc123 --actor you     # writes capabilities/fobo/skills/<name>.md
> pheonix promote fobo:s:abc123 --dry-run       # show the draft without writing
> ```
>
> `promote` writes a **draft** `skills/<name>.md` (frontmatter `status: draft`)
> for a `new_skill`, or prints the paste-ready `example_prompts` / `keywords`
> block for a `strengthen_skill`. pheonix never edits a hand-authored file. A
> rejected candidate reopens automatically only on a **material change** in
> volume (`material_change_count_factor` / `material_change_users_delta`).
> Rung 2 (make it deterministic) is the next phase.

(Strip the leading `> `.)

- [ ] **Step 3: Lint + full suite (docs — sanity only)**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 4: Commit**

```bash
git add CONTRACTS.md README.md
git commit -m "docs: the promotion ladder (Rung 1) — CONTRACTS + README"
```

---

## Self-Review

**1. Spec coverage (Phase C slice):**

| Spec element | Task |
|---|---|
| §7.2 `candidates` table | Task 2 |
| §7.2 `candidate_observations` table | Task 2 |
| §7.2 `candidate_decisions` table (append-only, AUTOINCREMENT id) | Task 2 |
| §7.3 `Candidate` / `CandidateObservation` / `CandidateDecision` + enums | Task 1 |
| §7.2 `candidate_id` = `<cap>:s:<cluster_id>` | Task 5 (`_candidate_id`) |
| §8.3 Rung-1 `skills/<name>.md` draft (frontmatter, `status: draft`, `source_candidate`, `evidence`, scaffold body) | Task 6 (`render_new_skill_md`) |
| §8.3 `strengthen_skill` → paste block, no file, records target path | Task 6 (`render_strengthen_block`, `promote_candidate`) |
| §8.3 keywords = `distinctive_words(signature)` minus placeholders/name words | Task 6 (`_keywords`) + reuse `skill_coverage._suggested_keywords` for strengthen |
| §9.1 `new_skill` vs `strengthen_skill` classification | Task 3 (`detect_rung1`) |
| §9.1 creation floor `max(3, rung1_min_count // 3)` | Task 3 (`_creation_floor`) |
| §9.1 `score` (gap strength) for both subtypes | Task 3 |
| §9.1 evidence bar `n_users ≥ rung1_min_users AND count ≥ rung1_min_count` | Task 3 (`met_evidence_bar`) |
| §9.1 readiness = last `rung1_sustained_runs` obs all met the bar; needs ≥ that many runs | Task 4 (`readiness_met`) |
| §10.1 every transition row | Task 4 (`next_status`, `advance_unobserved`) + Task 7 (`_DECISION_TRANSITIONS`) |
| §10.1 `snooze_until_run` ordinal = ordinal-at-decision + snooze_runs | Task 7 (`decide`) |
| §10.1 material-change reopen emits a `reopen` decision + note | Task 5 (`update_rung1`) via Task 4 `decision_action` |
| §10.1 `stale` after `run_history_limit` unobserved runs; `stale → accumulating` on re-observe | Task 4 + Task 5 |
| §10.2 step 7 (Rung 1: upsert candidate, write observation, run machine) | Task 5 |
| §10.2 step 9 (advance lifecycle globally: unsnooze, reopen, stale, crossed_threshold) | Task 5 (`update_rung1` + `_advance_unobserved`) |
| §10.2 step 10 (`n_rung1_candidates` on the run; prune observations) | Task 5 (wiring) + Task 2 (`prune_candidate_observations`) |
| §10.2 idempotency (`--replace-today` reuses run_id / ordinal) | Task 5 (ordinal note) |
| §10.3 decisions: append row + apply transition, `actor` default, invalid → error | Task 7 (`decide`) |
| §14 five new `Settings` fields | Task 3 (Step 1) |
| §15 CONTRACTS additions | Task 8 |

**Deferred (correctly, per spec phasing):** Rung 2 / `determinism.py` /
`mask_volatile` (Phase D); `?capability=` analytics params + all HTTP routes
(Phase E); the SPA (Phase F). `n_rung2_candidates` stays 0. `evaluate_spans`
per-capability is still not wired (Phase B note carried forward).

**2. Placeholder scan:** No `TBD`/`TODO`(in plan prose)/"handle edge cases".
Every code step is literal. The only literal `TODO` strings are inside the
generated artifact bodies (`## Procedure\n1. TODO`) and the strengthen path —
those are the intended draft content a human fills in, per §8.3.

**3. Type consistency:**
- `LadderThresholds` — same 7 fields in Task 3 def, Task 3 `resolve_thresholds`,
  Task 4 signatures (`sustained_runs=thresholds.rung1_sustained_runs`), Task 5
  call. ✓
- `Rung1Signal` — Task 3 def (13 fields) ↔ Task 5 `_observation` reads
  (`signal.count`, `.n_users`, `.n_sessions`, `.total_cost_usd`, `.score`,
  `.subtype`, `.route_len_avg`, `.long_route`, `.met_evidence_bar`) ↔ Task 5 test
  `_sig` builder. ✓
- `LadderTransition` — `status` / `note` / `set_ready_at` / `decision_action` in
  Task 4 def, Task 4 tests, Task 5 `update_rung1` reads. ✓
- `next_status(candidate, observation, recent_observations, *, run_ordinal,
  capability_run_count, thresholds)` — identical in Task 4 interface, Task 4
  impl, Task 5 call site. ✓
- `Candidate` fields — Task 1 model ↔ Task 2 `candidates` columns ↔ Task 2
  `upsert_candidate` INSERT ↔ Task 2 `_candidate_from_row` ↔ Task 5
  `model_copy(update=...)` keys (`status`, `current_evidence`, `ready_at`,
  `last_seen_*`, `subtype`, `matched_skill`, `title`, `signature`) ↔ Task 7
  `decide` updates (`dismiss_reason`, `snooze_until_run`, `decided_by`,
  `decided_at`). ✓
- `Store.record_candidate_decision_now(candidate_id, action, actor, when, *,
  note='', run_id=None)` — defined in Task 6 (storage helper), used by Task 6
  `promote_candidate` and Task 7 `decide`. ✓
- `Store.capability_run_ordinal(capability_id, run_id=None)` — Task 2 def ↔ Task
  5 (`+ 1` for this run) ↔ Task 7 `decide` (snooze base). ✓
- `promote_candidate(store, capability, candidate, *, now, actor, settings,
  dry_run=False)` — Task 6 def ↔ Task 6 tests ↔ Task 7 `promote` call. The Task 6
  interface list omits `settings=` in its prose — the **signature in Step 3 and
  the tests is authoritative**: `settings` is a required keyword arg.
- `update_rung1(...)` kw set — Task 5 interface ↔ Task 5 impl ↔ Task 5 test
  `_run` helper ↔ Task 5 wiring call. ✓

**4. Ambiguity resolved:**
- **Run ordinal vs run count.** For a fresh run, this run's row is not yet
  written, so ordinal = count = `capability_run_ordinal() + 1`. For
  `--replace-today`, the row exists: ordinal =
  `capability_run_ordinal(run_id)`, count = `capability_run_ordinal()`. Task 5
  Step 5 encodes both. `readiness_met` needs the *count* (how many runs exist);
  `next_status`'s `run_ordinal` is used only for unsnooze comparison.
- **Ladder notes never force `partial`.** Only scrape failures do (Phase B). A
  "Rung 1: N candidates observed" note is informational; `run.status` logic is
  unchanged (`"partial" if run_notes else "ok"` — and `run_notes` now includes
  ladder notes, so a run with candidates would wrongly read `partial`). **Fix in
  Task 5 wiring:** compute `status` from the *scrape* notes only —
  `status="partial" if notes else "ok"` where `notes` is the original `notes`
  arg, not `run_notes` after `.extend()`. Task 5 Step 5 must capture
  `scrape_partial = bool(notes)` before extending and use that for `status`.
- **`decide --action promote`** is not offered by `pheonix decide` — promotion
  is `pheonix promote` (writes files). `_DECISION_TRANSITIONS` has no `promote`
  key; the `DecisionAction` Literal still includes `"promote"` because
  `promote_candidate` records one.
- **`accept` allowed only from `ready`.** Matches §10.1 (`ready → accepted`).
  `pheonix promote --accept` is the one-step `ready → promoted` path and it
  flips to `accepted` first (Task 7 Step 6).

Fixes applied inline above where noted (Task 5 Step 5 status computation, Task 6
`settings=` kwarg).

