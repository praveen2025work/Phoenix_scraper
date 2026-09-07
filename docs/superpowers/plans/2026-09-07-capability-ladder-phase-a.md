# Capability Promotion Ladder — Phase A (Capability Entity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Capability` as a first-class entity — defined on disk in
`capabilities/<id>/capability.yaml`, mirrored into a `capabilities` SQLite table,
created and inspected through `pheonix capability` CLI verbs.

**Architecture:** Disk is the source of truth. `capability.py` owns the disk side
(read, write, scaffold the directory tree). `storage.py` gains a `capabilities`
table and CRUD that mirrors a `Capability` in and out. The CLI `sync` verb pushes
disk → DB. Nothing in the existing analysis pipeline changes; this phase adds a
new entity and its plumbing only.

**Tech Stack:** Python 3.11+, pydantic v2 (frozen models), pydantic-settings,
PyYAML, Typer, SQLite (stdlib `sqlite3`), pandas, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
(this plan implements §7.1–7.3 partial, §8.2, §8.5, §14 partial — the capability
entity, its yaml, its table, and its CRUD verbs. Scoped runs, the ladder, Rung 1
and Rung 2, the API, and the frontend are Phases B–G.)

## Global Constraints

- Python **>= 3.11** (`requires-python = ">=3.11"`); 3.11 syntax is used freely.
- Files stay **under 400 lines**. `capability.py` must not exceed it.
- **All functions return NEW objects** — never mutate an input argument.
- **Type hints on every function signature.**
- Data models are **frozen** — subclass `_Frozen` in `models.py`
  (`ConfigDict(frozen=True)`); mutable defaults via `Field(default_factory=...)`.
- **TDD:** write the test in `tests/test_<module>.py` first, watch it fail, then
  implement. Never write implementation before a failing test.
- Run a module's tests: `uv run pytest tests/test_<module>.py -q` from the repo
  root. Run everything: `uv run pytest -q` (must stay green — 538 tests today).
- Lint: `uv run ruff check src tests` (rules `E, F, I, UP, B`; line length 100).
- **No network, no live Phoenix in tests.**
- Commit message format: `<type>: <description>` — types `feat fix refactor docs
  test chore perf ci`. One commit per task (the final step of each task).
- The Python package is `phoenix_scraper`; the CLI command is `pheonix`.
- Settings read env vars with the prefix `PHEONIX_` (so `capabilities_dir` ←
  `PHEONIX_CAPABILITIES_DIR`). Blank env values already coerce to unset for
  string-or-none fields via the existing `_blank_to_none` validator (not needed
  for the new fields).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/config.py` | modify | add `capabilities_dir: Path`, `operator_name: str` to `Settings` |
| `src/phoenix_scraper/models.py` | modify | add `CapabilityFilter`, `Capability` frozen models |
| `src/phoenix_scraper/capability.py` | **create** | disk side: id validation, path helpers, `load_capability`, `dump_capability`, `write_capability`, `scaffold_capability`, `list_capability_ids`, `load_all_capabilities`, `capability_skill_dirs`, `capability_query_filters` |
| `src/phoenix_scraper/storage.py` | modify | `capabilities` table in `_SCHEMA`; `upsert_capability`, `get_capability`, `capabilities_frame`, `delete_capability`, `_capability_from_row` |
| `src/phoenix_scraper/cli.py` | modify | `capability` Typer sub-app: `new`, `sync`, `list`, `show`; `_settings` gains a `capabilities_dir` override |
| `tests/test_capability.py` | **create** | models + `capability.py` (Tasks 1–3) |
| `tests/test_capability_storage.py` | **create** | the `Store` capability methods (Task 4) |
| `tests/test_capability_cli.py` | **create** | the four CLI verbs (Tasks 5–6) |
| `.env.example` | modify | document `PHEONIX_CAPABILITIES_DIR`, `PHEONIX_OPERATOR_NAME` |
| `CONTRACTS.md` | modify | add the `capability.py` contract block |

---

## Task 1: Settings fields + Capability models

**Files:**
- Modify: `src/phoenix_scraper/config.py`
- Modify: `src/phoenix_scraper/models.py`
- Modify: `.env.example`
- Test: `tests/test_capability.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `Settings.capabilities_dir: Path` (default `Path("capabilities")`),
    `Settings.operator_name: str` (default `""`).
  - `models.CapabilityFilter(project: str | None = None, workflow_stage:
    str | None = None, asset_class: str | None = None, model_name: str | None =
    None, search: str | None = None)` — frozen.
  - `models.Capability(id: str, name: str, description: str = "", filter:
    CapabilityFilter = <factory>, window_days: int = 30, thresholds: dict[str,
    float] = <factory>, status: Literal["active", "paused"] = "active")` —
    frozen.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability.py`:

```python
"""Tests for Capability settings, models, and the capabilities/<id>/ disk layer."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from phoenix_scraper.config import Settings
from phoenix_scraper.models import Capability, CapabilityFilter

# Match the repo convention: never let a developer's real .env leak into a test.
_S = dict(_env_file=None)


class TestSettings:
    def test_capabilities_dir_defaults_to_capabilities(self) -> None:
        assert Settings(**_S).capabilities_dir == Path("capabilities")

    def test_capabilities_dir_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("PHEONIX_CAPABILITIES_DIR", "/tmp/caps")
        # _env_file=None disables the dotenv file, NOT os.environ — the var is read.
        assert Settings(**_S).capabilities_dir == Path("/tmp/caps")

    def test_operator_name_defaults_blank(self) -> None:
        assert Settings(**_S).operator_name == ""


class TestCapabilityModels:
    def test_defaults(self) -> None:
        cap = Capability(id="fobo", name="FOBO reconciliation")
        assert cap.description == ""
        assert cap.window_days == 30
        assert cap.status == "active"
        assert cap.thresholds == {}
        assert cap.filter == CapabilityFilter()

    def test_filter_is_frozen(self) -> None:
        f = CapabilityFilter(project="pnl-agent")
        with pytest.raises(ValidationError):
            f.project = "other"  # type: ignore[misc]

    def test_thresholds_default_is_not_shared(self) -> None:
        a = Capability(id="a", name="a")
        b = Capability(id="b", name="b")
        assert a.thresholds is not b.thresholds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability.py -q`
Expected: FAIL — `ImportError: cannot import name 'Capability' from 'phoenix_scraper.models'`.

- [ ] **Step 3: Add the Settings fields**

In `src/phoenix_scraper/config.py`, inside `class Settings`, after the
`skills_catalog` / `skills_dirs` / `pricing_path` block, add:

```python
    # Capabilities: each is a directory under this root with a capability.yaml
    # (source of truth) mirrored into the `capabilities` table by `pheonix
    # capability sync`.
    capabilities_dir: Path = Path("capabilities")
    # Default actor recorded on ladder decisions when the request omits one.
    operator_name: str = ""
```

- [ ] **Step 4: Add the Capability models**

In `src/phoenix_scraper/models.py`, after the `SkillEntry` class (before
`SkillMatch`), add:

```python
class CapabilityFilter(_Frozen):
    """The span selector for a capability — a subset of QueryFilters' dimensions."""

    project: str | None = None
    workflow_stage: str | None = None
    asset_class: str | None = None
    model_name: str | None = None
    search: str | None = None  # substring match on input_text


class Capability(_Frozen):
    """A named analysis scope: a saved span filter plus an owned directory of
    skill files. Defined on disk in capabilities/<id>/capability.yaml; mirrored
    into the `capabilities` table."""

    id: str
    name: str
    description: str = ""
    filter: CapabilityFilter = Field(default_factory=CapabilityFilter)
    window_days: int = 30
    thresholds: dict[str, float] = Field(default_factory=dict)
    status: Literal["active", "paused"] = "active"
```

`Field` and `Literal` are already imported in `models.py` — confirm the import
lines read `from typing import Any, Literal` and `from pydantic import BaseModel,
ConfigDict, Field`. They do; no import change needed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Document the env vars**

In `.env.example`, after the `PHEONIX_SKILLS_DIRS=` line, add:

```bash
# Root directory for capability workspaces (capabilities/<id>/capability.yaml +
# skills/ + deterministic/). Created on `pheonix capability new`.
PHEONIX_CAPABILITIES_DIR=capabilities
# Name recorded as the actor on promotion-ladder decisions when a request or
# CLI flag doesn't supply one.
PHEONIX_OPERATOR_NAME=
```

- [ ] **Step 7: Lint and run the full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: ruff clean; all tests pass (was 538, now 544).

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/config.py src/phoenix_scraper/models.py .env.example tests/test_capability.py
git commit -m "feat: Capability and CapabilityFilter models, capabilities_dir setting"
```

---

## Task 2: `capability.py` — id validation, paths, load/dump

**Files:**
- Create: `src/phoenix_scraper/capability.py`
- Test: `tests/test_capability.py` (append)

**Interfaces:**
- Consumes: `models.Capability`, `models.CapabilityFilter` (Task 1).
- Produces:
  - `validate_id(cap_id: str) -> str` — returns `cap_id` or raises `ValueError`.
  - `capability_dir(root: Path, cap_id: str) -> Path`
  - `config_path(root: Path, cap_id: str) -> Path` (= `<root>/<id>/capability.yaml`)
  - `load_capability(root: Path, cap_id: str) -> Capability` — raises
    `FileNotFoundError` if no yaml, `ValueError` on malformed content.
  - `dump_capability(capability: Capability) -> str` — yaml text, stable key
    order, `load_capability` of the written file round-trips.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability.py`:

```python
import pytest

from phoenix_scraper import capability as cap_mod


class TestValidateId:
    @pytest.mark.parametrize("good", ["fobo", "flash-vs-formal", "plex2", "a1"])
    def test_accepts_kebab(self, good: str) -> None:
        assert cap_mod.validate_id(good) == good

    @pytest.mark.parametrize(
        "bad", ["", "1fobo", "FOBO", "fo bo", "fobo_recon", "-fobo", "a" * 65]
    )
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValueError):
            cap_mod.validate_id(bad)


class TestLoadDump:
    def _write(self, root: Path, cap_id: str, text: str) -> Path:
        d = root / cap_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / "capability.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_load_full(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "fobo",
            "id: fobo\nname: FOBO reconciliation\n"
            "description: Break triage.\n"
            "filter:\n  project: pnl-agent\n  workflow_stage: fobo_recon\n"
            "  asset_class: null\n"
            "window_days: 45\n"
            "thresholds:\n  rung1_min_users: 4\n"
            "status: paused\n",
        )
        cap = cap_mod.load_capability(tmp_path, "fobo")
        assert cap.id == "fobo"
        assert cap.name == "FOBO reconciliation"
        assert cap.filter.project == "pnl-agent"
        assert cap.filter.workflow_stage == "fobo_recon"
        assert cap.filter.asset_class is None
        assert cap.window_days == 45
        assert cap.thresholds == {"rung1_min_users": 4}
        assert cap.status == "paused"

    def test_load_minimal_fills_defaults(self, tmp_path: Path) -> None:
        self._write(tmp_path, "plex", "id: plex\nname: PLEX\n")
        cap = cap_mod.load_capability(tmp_path, "plex")
        assert cap.filter == CapabilityFilter()
        assert cap.window_days == 30
        assert cap.status == "active"

    def test_load_blank_filter_values_become_none(self, tmp_path: Path) -> None:
        self._write(
            tmp_path, "plex",
            "id: plex\nname: PLEX\nfilter:\n  project: '  '\n  search: ''\n",
        )
        cap = cap_mod.load_capability(tmp_path, "plex")
        assert cap.filter.project is None
        assert cap.filter.search is None

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            cap_mod.load_capability(tmp_path, "ghost")

    def test_load_non_mapping_raises(self, tmp_path: Path) -> None:
        self._write(tmp_path, "bad", "- just\n- a\n- list\n")
        with pytest.raises(ValueError):
            cap_mod.load_capability(tmp_path, "bad")

    def test_load_bad_status_falls_back_to_active(self, tmp_path: Path) -> None:
        self._write(tmp_path, "x", "id: x\nname: X\nstatus: wobbly\n")
        assert cap_mod.load_capability(tmp_path, "x").status == "active"

    def test_dump_round_trips(self, tmp_path: Path) -> None:
        original = Capability(
            id="fobo",
            name="FOBO",
            description="d",
            filter=CapabilityFilter(project="pnl-agent", asset_class="fx"),
            window_days=14,
            thresholds={"rung2_determinism_score": 0.9},
            status="paused",
        )
        (tmp_path / "fobo").mkdir()
        (tmp_path / "fobo" / "capability.yaml").write_text(
            cap_mod.dump_capability(original), encoding="utf-8"
        )
        assert cap_mod.load_capability(tmp_path, "fobo") == original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoenix_scraper.capability'`.

- [ ] **Step 3: Create the module**

Create `src/phoenix_scraper/capability.py`:

```python
"""The capability workspace: capabilities/<id>/ and its capability.yaml.

A capability is defined on disk — capability.yaml is the source of truth — and
mirrored into the `capabilities` table by `pheonix capability sync`. This module
owns the disk side only: id rules, path layout, reading, writing, scaffolding.
"""

import logging
import re
from pathlib import Path

import yaml

from .models import Capability, CapabilityFilter

logger = logging.getLogger(__name__)

CONFIG_NAME = "capability.yaml"
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_FILTER_KEYS = ("project", "workflow_stage", "asset_class", "model_name", "search")
_STATUSES = ("active", "paused")


def validate_id(cap_id: str) -> str:
    """Return ``cap_id`` unchanged, or raise ValueError if it is not a valid slug.

    Valid: 2-64 chars, lowercase ascii letters / digits / hyphens, first char a
    letter. Underscores are out so ids never collide with the ``<id>`` masks in
    normalize.py, and so a capability id is always a safe directory name.
    """
    if not _ID_RE.match(cap_id):
        raise ValueError(
            f"Invalid capability id {cap_id!r}: 2-64 chars, lowercase letters, "
            f"digits and hyphens, starting with a letter."
        )
    return cap_id


def capability_dir(root: Path, cap_id: str) -> Path:
    return Path(root) / cap_id


def config_path(root: Path, cap_id: str) -> Path:
    return capability_dir(root, cap_id) / CONFIG_NAME


def _clean(value: object) -> str | None:
    """Blank / whitespace-only yaml values mean 'unset', matching Settings."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_capability(root: Path, cap_id: str) -> Capability:
    """Parse ``capabilities/<cap_id>/capability.yaml`` into a Capability.

    Raises FileNotFoundError when the file is absent, ValueError when it is not a
    mapping or a nested section has the wrong shape. An unrecognised ``status``
    falls back to ``active`` rather than failing the load.
    """
    path = config_path(root, cap_id)
    if not path.is_file():
        raise FileNotFoundError(f"No {CONFIG_NAME} for capability {cap_id!r} at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    filter_raw = raw.get("filter") or {}
    if not isinstance(filter_raw, dict):
        raise ValueError(f"{path}: 'filter' must be a mapping")
    thresholds_raw = raw.get("thresholds") or {}
    if not isinstance(thresholds_raw, dict):
        raise ValueError(f"{path}: 'thresholds' must be a mapping")
    status = raw.get("status")
    return Capability(
        id=validate_id(str(raw.get("id") or cap_id)),
        name=str(raw.get("name") or cap_id),
        description=str(raw.get("description") or ""),
        filter=CapabilityFilter(**{k: _clean(filter_raw.get(k)) for k in _FILTER_KEYS}),
        window_days=int(raw.get("window_days", 30)),
        thresholds={str(k): float(v) for k, v in thresholds_raw.items()},
        status=status if status in _STATUSES else "active",
    )


def dump_capability(capability: Capability) -> str:
    """Serialise a Capability to capability.yaml text with a stable key order."""
    body = {
        "id": capability.id,
        "name": capability.name,
        "description": capability.description,
        "filter": {key: getattr(capability.filter, key) for key in _FILTER_KEYS},
        "window_days": capability.window_days,
        "thresholds": dict(capability.thresholds),
        "status": capability.status,
    }
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
```

Note the `thresholds` cast to `float` on load: the model types it `dict[str,
float]`, and `4` and `0.9` both need to survive the round-trip. `float(4)` ==
`4.0`; the test asserts `== {"rung1_min_users": 4}` which is `True` in Python
(`4.0 == 4`). Keep the cast.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/capability.py tests/test_capability.py
git commit -m "feat: capability.py load/dump for capability.yaml"
```

---

## Task 3: `capability.py` — scaffold, list, skill dirs, query filters

**Files:**
- Modify: `src/phoenix_scraper/capability.py`
- Modify: `CONTRACTS.md`
- Test: `tests/test_capability.py` (append)

**Interfaces:**
- Consumes: Task 2's `capability.py` functions; `models.QueryFilters`.
- Produces:
  - `write_capability(root: Path, capability: Capability) -> Path` — creates
    `<root>/<id>/{skills,deterministic}/` and writes `capability.yaml`; returns
    the yaml path.
  - `scaffold_capability(root: Path, cap_id: str, *, name: str = "", description:
    str = "", cap_filter: CapabilityFilter | None = None, window_days: int = 30)
    -> Capability` — raises `FileExistsError` if the yaml already exists.
  - `list_capability_ids(root: Path) -> list[str]` — sorted ids that have a yaml.
  - `load_all_capabilities(root: Path) -> list[Capability]` — skips malformed
    with a warning.
  - `capability_skill_dirs(root: Path, cap_id: str) -> list[Path]` —
    `[<root>/<id>/skills]` when it exists, else `[]`.
  - `capability_query_filters(capability: Capability, *, start: datetime | None =
    None, end: datetime | None = None, limit: int = 100_000) -> QueryFilters`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability.py`:

```python
from datetime import UTC, datetime

from phoenix_scraper.models import QueryFilters


class TestScaffold:
    def test_creates_tree_and_yaml(self, tmp_path: Path) -> None:
        cap = cap_mod.scaffold_capability(
            tmp_path, "fobo", name="FOBO", description="triage",
            cap_filter=CapabilityFilter(project="pnl-agent", workflow_stage="fobo_recon"),
            window_days=21,
        )
        assert cap.id == "fobo" and cap.window_days == 21
        assert (tmp_path / "fobo" / "capability.yaml").is_file()
        assert (tmp_path / "fobo" / "skills").is_dir()
        assert (tmp_path / "fobo" / "deterministic").is_dir()
        # round-trips through disk
        assert cap_mod.load_capability(tmp_path, "fobo") == cap

    def test_rejects_duplicate(self, tmp_path: Path) -> None:
        cap_mod.scaffold_capability(tmp_path, "fobo", name="FOBO")
        with pytest.raises(FileExistsError):
            cap_mod.scaffold_capability(tmp_path, "fobo", name="again")

    def test_rejects_bad_id(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            cap_mod.scaffold_capability(tmp_path, "Bad_Id", name="x")


class TestListing:
    def test_lists_only_dirs_with_yaml(self, tmp_path: Path) -> None:
        cap_mod.scaffold_capability(tmp_path, "fobo", name="FOBO")
        cap_mod.scaffold_capability(tmp_path, "plex", name="PLEX")
        (tmp_path / "not-a-cap").mkdir()
        assert cap_mod.list_capability_ids(tmp_path) == ["fobo", "plex"]

    def test_list_missing_root_is_empty(self, tmp_path: Path) -> None:
        assert cap_mod.list_capability_ids(tmp_path / "nope") == []

    def test_load_all_skips_malformed(self, tmp_path: Path, caplog) -> None:
        cap_mod.scaffold_capability(tmp_path, "good", name="Good")
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "capability.yaml").write_text("- nope\n", encoding="utf-8")
        caps = cap_mod.load_all_capabilities(tmp_path)
        assert [c.id for c in caps] == ["good"]


class TestSkillDirs:
    def test_returns_skills_dir_when_present(self, tmp_path: Path) -> None:
        cap_mod.scaffold_capability(tmp_path, "fobo", name="FOBO")
        assert cap_mod.capability_skill_dirs(tmp_path, "fobo") == [
            tmp_path / "fobo" / "skills"
        ]

    def test_empty_when_absent(self, tmp_path: Path) -> None:
        assert cap_mod.capability_skill_dirs(tmp_path, "ghost") == []


class TestQueryFilters:
    def test_maps_every_filter_dimension(self) -> None:
        cap = Capability(
            id="fobo", name="FOBO",
            filter=CapabilityFilter(
                project="pnl-agent", workflow_stage="fobo_recon",
                asset_class="fx", model_name="claude", search="break",
            ),
        )
        start = datetime(2026, 8, 1, tzinfo=UTC)
        end = datetime(2026, 9, 1, tzinfo=UTC)
        qf = cap_mod.capability_query_filters(cap, start=start, end=end, limit=500)
        assert isinstance(qf, QueryFilters)
        assert qf.project == "pnl-agent"
        assert qf.workflow_stage == "fobo_recon"
        assert qf.asset_class == "fx"
        assert qf.model_name == "claude"
        assert qf.search == "break"
        assert qf.start == start and qf.end == end and qf.limit == 500

    def test_defaults(self) -> None:
        qf = cap_mod.capability_query_filters(Capability(id="a", name="a"))
        assert qf.start is None and qf.end is None and qf.limit == 100_000
        assert qf.project is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability.py -q`
Expected: FAIL — `AttributeError: module 'phoenix_scraper.capability' has no attribute 'scaffold_capability'`.

- [ ] **Step 3: Implement**

Add to `src/phoenix_scraper/capability.py`. First extend the imports:

```python
from datetime import datetime

from .models import Capability, CapabilityFilter, QueryFilters
```

(Replace the existing `from .models import Capability, CapabilityFilter` line;
add the `datetime` import next to the stdlib imports.)

Then append these functions:

```python
def write_capability(root: Path, capability: Capability) -> Path:
    """Create the capability's directory tree and write its capability.yaml."""
    cap_dir = capability_dir(root, capability.id)
    (cap_dir / "skills").mkdir(parents=True, exist_ok=True)
    (cap_dir / "deterministic").mkdir(parents=True, exist_ok=True)
    path = cap_dir / CONFIG_NAME
    path.write_text(dump_capability(capability), encoding="utf-8")
    return path


def scaffold_capability(
    root: Path,
    cap_id: str,
    *,
    name: str = "",
    description: str = "",
    cap_filter: CapabilityFilter | None = None,
    window_days: int = 30,
) -> Capability:
    """Create a new capabilities/<id>/ workspace. Raises FileExistsError if one
    is already there, ValueError if the id is invalid."""
    validate_id(cap_id)
    if config_path(root, cap_id).exists():
        raise FileExistsError(
            f"Capability {cap_id!r} already exists at {config_path(root, cap_id)}"
        )
    capability = Capability(
        id=cap_id,
        name=name or cap_id,
        description=description,
        filter=cap_filter or CapabilityFilter(),
        window_days=window_days,
    )
    write_capability(root, capability)
    return capability


def list_capability_ids(root: Path) -> list[str]:
    """Sorted ids of every capabilities/<id>/ that contains a capability.yaml."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(
        path.parent.name
        for path in root.glob(f"*/{CONFIG_NAME}")
        if path.is_file()
    )


def load_all_capabilities(root: Path) -> list[Capability]:
    """Every loadable capability under root; malformed ones are skipped + logged."""
    out: list[Capability] = []
    for cap_id in list_capability_ids(root):
        try:
            out.append(load_capability(root, cap_id))
        except (ValueError, FileNotFoundError) as exc:
            logger.warning("Skipping capability %s: %s", cap_id, exc)
    return out


def capability_skill_dirs(root: Path, cap_id: str) -> list[Path]:
    """The skill directories to fold into this capability's skill scan."""
    skills = capability_dir(root, cap_id) / "skills"
    return [skills] if skills.is_dir() else []


def capability_query_filters(
    capability: Capability,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100_000,
) -> QueryFilters:
    """The capability's span filter as a QueryFilters, with an optional window."""
    f = capability.filter
    return QueryFilters(
        project=f.project,
        workflow_stage=f.workflow_stage,
        asset_class=f.asset_class,
        model_name=f.model_name,
        search=f.search,
        start=start,
        end=end,
        limit=limit,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability.py -q`
Expected: PASS.

- [ ] **Step 5: Check the file length**

Run: `wc -l src/phoenix_scraper/capability.py`
Expected: under 400. (If close, that is fine for this phase — no split needed
below ~250.)

- [ ] **Step 6: Add the CONTRACTS.md block**

In `CONTRACTS.md`, after the `## skills.py` section, insert:

````markdown
## capability.py  (the capabilities/<id>/ disk layer — capability.yaml is source of truth)
```python
CONFIG_NAME = "capability.yaml"

def validate_id(cap_id: str) -> str
    # 2-64 chars, ^[a-z][a-z0-9-]{1,63}$; returns it or raises ValueError.
def config_path(root: Path, cap_id: str) -> Path        # <root>/<id>/capability.yaml
def load_capability(root: Path, cap_id: str) -> Capability
    # FileNotFoundError if absent; ValueError if not a mapping / bad section.
    # Unknown status -> "active". Blank filter values -> None.
def dump_capability(capability: Capability) -> str      # yaml text; load round-trips
def write_capability(root: Path, capability: Capability) -> Path
    # mkdir <id>/skills, <id>/deterministic; write capability.yaml; return its path
def scaffold_capability(root, cap_id, *, name="", description="",
                        cap_filter=None, window_days=30) -> Capability
    # FileExistsError if capability.yaml already there; ValueError on bad id
def list_capability_ids(root: Path) -> list[str]        # sorted; only dirs with a yaml
def load_all_capabilities(root: Path) -> list[Capability]   # skips malformed (warns)
def capability_skill_dirs(root: Path, cap_id: str) -> list[Path]   # [<id>/skills] or []
def capability_query_filters(capability, *, start=None, end=None,
                             limit=100_000) -> QueryFilters
```
````

- [ ] **Step 7: Lint and full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/capability.py tests/test_capability.py CONTRACTS.md
git commit -m "feat: capability scaffolding, listing, and query-filter mapping"
```

---

## Task 4: `storage.py` — `capabilities` table + CRUD

**Files:**
- Modify: `src/phoenix_scraper/storage.py`
- Test: `tests/test_capability_storage.py` (create)

**Interfaces:**
- Consumes: `models.Capability`, `models.CapabilityFilter`.
- Produces (methods on `Store`):
  - `upsert_capability(self, capability: Capability) -> None` — insert or update
    by `capability_id`; sets `updated_at` every time, `created_at` only on
    insert.
  - `get_capability(self, capability_id: str) -> Capability | None`
  - `capabilities_frame(self) -> pd.DataFrame` — all rows, ordered by
    `capability_id`.
  - `delete_capability(self, capability_id: str) -> bool` — `True` if a row was
    removed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_storage.py`:

```python
"""Tests for the capabilities table CRUD on Store."""

from phoenix_scraper.models import Capability, CapabilityFilter


def _cap(cap_id: str = "fobo", **over) -> Capability:
    base = dict(
        id=cap_id,
        name="FOBO reconciliation",
        description="Break triage.",
        filter=CapabilityFilter(project="pnl-agent", workflow_stage="fobo_recon"),
        window_days=30,
        thresholds={"rung1_min_users": 4.0},
        status="active",
    )
    base.update(over)
    return Capability(**base)


class TestCapabilityCrud:
    def test_upsert_then_get_round_trips(self, tmp_store) -> None:
        cap = _cap()
        tmp_store.upsert_capability(cap)
        assert tmp_store.get_capability("fobo") == cap

    def test_get_unknown_is_none(self, tmp_store) -> None:
        assert tmp_store.get_capability("nope") is None

    def test_upsert_updates_in_place(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap())
        tmp_store.upsert_capability(_cap(name="Renamed", status="paused"))
        got = tmp_store.get_capability("fobo")
        assert got.name == "Renamed"
        assert got.status == "paused"
        assert len(tmp_store.capabilities_frame()) == 1

    def test_created_at_is_stable_across_updates(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap())
        first = tmp_store.capabilities_frame().iloc[0]["created_at"]
        tmp_store.upsert_capability(_cap(name="Renamed"))
        row = tmp_store.capabilities_frame().iloc[0]
        assert row["created_at"] == first
        assert row["updated_at"] >= first

    def test_frame_sorted_by_id(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap("plex", name="PLEX"))
        tmp_store.upsert_capability(_cap("fobo"))
        assert list(tmp_store.capabilities_frame()["capability_id"]) == ["fobo", "plex"]

    def test_delete(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap())
        assert tmp_store.delete_capability("fobo") is True
        assert tmp_store.delete_capability("fobo") is False
        assert tmp_store.get_capability("fobo") is None

    def test_null_filter_fields_survive(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap(filter=CapabilityFilter()))
        assert tmp_store.get_capability("fobo").filter == CapabilityFilter()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_storage.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'upsert_capability'`.

- [ ] **Step 3: Add the table to the schema**

In `src/phoenix_scraper/storage.py`, inside the `_SCHEMA` string, after the
`sessions` table definition (before the closing `"""`), add:

```sql

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    filter_project TEXT,
    filter_workflow_stage TEXT,
    filter_asset_class TEXT,
    filter_model_name TEXT,
    filter_search TEXT,
    window_days INTEGER NOT NULL DEFAULT 30,
    thresholds_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 4: Extend the storage imports**

At the top of `storage.py`, add `Capability` and `CapabilityFilter` to the
`from .models import (...)` block (keep the list alphabetically ordered as it is
now — insert `Capability,` and `CapabilityFilter,` before `PromptCluster,`).

- [ ] **Step 5: Add the CRUD methods**

In `storage.py`, add a new section just before `# ---- internals ----------`:

```python
    # ---- capabilities -----------------------------------------------------
    def upsert_capability(self, capability: Capability) -> None:
        """Mirror a Capability into the table. created_at is preserved on update."""
        now = _iso(datetime.now(UTC))
        f = capability.filter
        self._conn.execute(
            "INSERT INTO capabilities (capability_id, name, description, "
            "filter_project, filter_workflow_stage, filter_asset_class, "
            "filter_model_name, filter_search, window_days, thresholds_json, "
            "status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(capability_id) DO UPDATE SET "
            "name=excluded.name, description=excluded.description, "
            "filter_project=excluded.filter_project, "
            "filter_workflow_stage=excluded.filter_workflow_stage, "
            "filter_asset_class=excluded.filter_asset_class, "
            "filter_model_name=excluded.filter_model_name, "
            "filter_search=excluded.filter_search, "
            "window_days=excluded.window_days, "
            "thresholds_json=excluded.thresholds_json, "
            "status=excluded.status, updated_at=excluded.updated_at",
            (
                capability.id, capability.name, capability.description,
                f.project, f.workflow_stage, f.asset_class, f.model_name, f.search,
                capability.window_days, json.dumps(capability.thresholds),
                capability.status, now, now,
            ),
        )
        self._conn.commit()

    def get_capability(self, capability_id: str) -> Capability | None:
        row = self._conn.execute(
            "SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,)
        ).fetchone()
        return _capability_from_row(row) if row is not None else None

    def capabilities_frame(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM capabilities ORDER BY capability_id", self._conn
        )

    def delete_capability(self, capability_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM capabilities WHERE capability_id = ?", (capability_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0
```

- [ ] **Step 6: Add the row → model helper**

At the bottom of `storage.py`, next to `_evaluation_row`, add:

```python
def _capability_from_row(row: sqlite3.Row) -> Capability:
    return Capability(
        id=row["capability_id"],
        name=row["name"],
        description=row["description"],
        filter=CapabilityFilter(
            project=row["filter_project"],
            workflow_stage=row["filter_workflow_stage"],
            asset_class=row["filter_asset_class"],
            model_name=row["filter_model_name"],
            search=row["filter_search"],
        ),
        window_days=row["window_days"],
        thresholds=json.loads(row["thresholds_json"]),
        status=row["status"],
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_storage.py -q`
Expected: PASS.

- [ ] **Step 8: Confirm the schema change is backward compatible**

Run: `uv run pytest tests/test_storage.py -q`
Expected: PASS — `executescript` runs `CREATE TABLE IF NOT EXISTS`, so existing
DBs gain the table on next open and no existing test is affected.

- [ ] **Step 9: Lint and full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 10: Commit**

```bash
git add src/phoenix_scraper/storage.py tests/test_capability_storage.py
git commit -m "feat: capabilities table and CRUD on Store"
```

---

## Task 5: CLI — `pheonix capability new` and `sync`

**Files:**
- Modify: `src/phoenix_scraper/cli.py`
- Test: `tests/test_capability_cli.py` (create)

**Interfaces:**
- Consumes: `capability.py` (Tasks 2–3), `Store` capability methods (Task 4),
  `Settings.capabilities_dir`.
- Produces:
  - CLI `pheonix capability new <id> [--name --description --project --stage
    --asset-class --search --window-days --db --capabilities-dir]` — scaffolds
    the dir and upserts the row; exit 1 with a red message on a bad/duplicate
    id.
  - CLI `pheonix capability sync [<id>] [--db --capabilities-dir]` — one id, or
    all of them when omitted; upserts each into the DB; prints a line per
    capability. Exit 1 if a named id has no yaml.
  - `_settings(..., capabilities_dir: Path | None = None)` gains the override.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_cli.py`:

```python
"""CLI tests for `pheonix capability` verbs."""

from pathlib import Path

from typer.testing import CliRunner

from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.storage import Store

runner = CliRunner()


def _invoke(*args: str) -> object:
    return runner.invoke(cli_app, list(args))


class TestCapabilityNew:
    def test_creates_dir_and_row(self, tmp_path: Path) -> None:
        caps = tmp_path / "caps"
        db = tmp_path / "c.db"
        result = _invoke(
            "capability", "new", "fobo",
            "--name", "FOBO reconciliation",
            "--project", "pnl-agent", "--stage", "fobo_recon",
            "--window-days", "21",
            "--capabilities-dir", str(caps), "--db", str(db),
        )
        assert result.exit_code == 0, result.output
        assert (caps / "fobo" / "capability.yaml").is_file()
        store = Store(db)
        try:
            cap = store.get_capability("fobo")
            assert cap is not None
            assert cap.name == "FOBO reconciliation"
            assert cap.filter.project == "pnl-agent"
            assert cap.window_days == 21
        finally:
            store.close()

    def test_duplicate_exits_1(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        assert _invoke("capability", "new", "fobo", *common).exit_code == 0
        dup = _invoke("capability", "new", "fobo", *common)
        assert dup.exit_code == 1
        assert "already exists" in dup.output

    def test_bad_id_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "new", "Bad_Id",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 1
        assert "Invalid capability id" in result.output


class TestCapabilitySync:
    def test_sync_all_after_hand_edit(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--name", "FOBO", *common)
        # hand-edit the yaml the way a user would
        yaml_path = caps / "fobo" / "capability.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace("status: active", "status: paused"),
            encoding="utf-8",
        )
        result = _invoke("capability", "sync", *common)
        assert result.exit_code == 0, result.output
        store = Store(db)
        try:
            assert store.get_capability("fobo").status == "paused"
        finally:
            store.close()

    def test_sync_unknown_id_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "sync", "ghost",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_cli.py -q`
Expected: FAIL — `capability` is not a command (`result.exit_code == 2`), so the
first assertion `exit_code == 0` fails.

- [ ] **Step 3: Thread `capabilities_dir` through `_settings`**

In `src/phoenix_scraper/cli.py`, update `_settings`:

```python
def _settings(
    db: Path | None = None,
    export_dir: Path | None = None,
    project: str | None = None,
    capabilities_dir: Path | None = None,
) -> Settings:
    base = load_settings()
    updates: dict[str, object] = {
        key: value
        for key, value in (
            ("db_path", db),
            ("export_dir", export_dir),
            ("project", project),
            ("capabilities_dir", capabilities_dir),
        )
        if value is not None
    }
    return base.model_copy(update=updates) if updates else base
```

- [ ] **Step 4: Add the import, option singletons, and the sub-app**

**Import.** The file already has `from .models import (AnalysisResult,
AnnotationSyncReport, PromptCluster, QueryFilters, ScrapeReport,)`. Add
`Capability` and `CapabilityFilter` into that parenthesised list (keep it sorted:
`AnalysisResult, AnnotationSyncReport, Capability, CapabilityFilter,
PromptCluster, QueryFilters, ScrapeReport`). Then add one new module import line
next to `from . import skills as skills_mod`:

```python
from . import capability as capability_mod
```

**Option singletons.** This file never inlines `typer.Option` / `typer.Argument`
in a signature — every option is a module-level `*Opt` / `*Arg` singleton (this
is deliberate; inline calls trip ruff `B008`). `ProjectOpt`, `StageOpt`,
`AssetClassOpt`, `SearchOpt`, `DbOpt` already exist and are reusable as-is
(all default `None`). Near the other singletons (after `WriteUpdatesOpt`), add:

```python
CapabilitiesDirOpt = typer.Option(
    None, "--capabilities-dir", help="Override the capabilities root directory."
)
CapIdArg = typer.Argument(..., help="Capability id (kebab-case, e.g. fobo).")
CapIdOptionalArg = typer.Argument(
    None, help="One capability id; omit to act on all of them."
)
CapNameOpt = typer.Option("", "--name", help="Display name.")
CapDescriptionOpt = typer.Option("", "--description", help="One-line description.")
CapWindowDaysOpt = typer.Option(30, "--window-days", help="Default from/to span in days.")
```

**Sub-app.** After `app = typer.Typer(...)` and the `_init_logging` callback
(near the top, before the first `@app.command()`), add:

```python
capability_app = typer.Typer(
    name="capability",
    help="Create, inspect, and sync capability workspaces.",
    no_args_is_help=True,
)
app.add_typer(capability_app, name="capability")
```

- [ ] **Step 5: Implement `new` and `sync`**

Append to `cli.py` after the last `@app.command()` (the `serve` command), before
the `# ---- helpers ---` divider:

```python
@capability_app.command("new")
def capability_new(
    cap_id: str = CapIdArg,
    name: str = CapNameOpt,
    description: str = CapDescriptionOpt,
    project: str | None = ProjectOpt,
    stage: str | None = StageOpt,
    asset_class: str | None = AssetClassOpt,
    search: str | None = SearchOpt,
    window_days: int = CapWindowDaysOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Scaffold capabilities/<id>/ and mirror it into the database."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    try:
        cap = capability_mod.scaffold_capability(
            settings.capabilities_dir,
            cap_id,
            name=name,
            description=description,
            cap_filter=CapabilityFilter(
                project=project,
                workflow_stage=stage,
                asset_class=asset_class,
                search=search,
            ),
            window_days=window_days,
        )
    except (ValueError, FileExistsError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    with _open_store(settings) as store:
        store.upsert_capability(cap)
    typer.echo(
        f"Created capability '{cap.id}' -> "
        f"{capability_mod.config_path(settings.capabilities_dir, cap.id)}"
    )


@capability_app.command("sync")
def capability_sync(
    cap_id: str | None = CapIdOptionalArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Re-read capability.yaml from disk into the capabilities table."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    root = settings.capabilities_dir
    if cap_id is not None:
        try:
            caps = [capability_mod.load_capability(root, cap_id)]
        except (ValueError, FileNotFoundError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
    else:
        caps = capability_mod.load_all_capabilities(root)
    if not caps:
        typer.echo("No capabilities found.")
        return
    with _open_store(settings) as store:
        for cap in caps:
            store.upsert_capability(cap)
            typer.echo(f"synced {cap.id} (status={cap.status})")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_cli.py -q`
Expected: PASS.

- [ ] **Step 7: Lint and full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/cli.py tests/test_capability_cli.py
git commit -m "feat: pheonix capability new and sync"
```

---

## Task 6: CLI — `pheonix capability list` and `show`

**Files:**
- Modify: `src/phoenix_scraper/cli.py`
- Modify: `tests/test_capability_cli.py` (append)
- Modify: `README.md`

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces:
  - CLI `pheonix capability list [--db --capabilities-dir]` — a table of ids
    from disk, each annotated with whether it is synced to the DB and its
    status.
  - CLI `pheonix capability show <id> [--capabilities-dir]` — the parsed
    capability's fields and the count of files in `skills/` and `deterministic/`.
    Exit 1 if the id has no yaml.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability_cli.py`:

```python
class TestCapabilityList:
    def test_lists_disk_capabilities_with_sync_state(self, tmp_path: Path) -> None:
        caps, db = tmp_path / "caps", tmp_path / "c.db"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--name", "FOBO", *common)
        _invoke("capability", "new", "plex", "--name", "PLEX", *common)
        # drop plex's row so it exists on disk but is "not synced"
        store = Store(db)
        try:
            store.delete_capability("plex")
        finally:
            store.close()
        result = _invoke("capability", "list", *common)
        assert result.exit_code == 0, result.output
        assert "fobo" in result.output and "plex" in result.output
        assert "not synced" in result.output  # plex

    def test_list_empty(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "list",
            "--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"),
        )
        assert result.exit_code == 0
        assert "No capabilities" in result.output


class TestCapabilityShow:
    def test_shows_fields_and_file_counts(self, tmp_path: Path) -> None:
        caps = tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(tmp_path / "c.db"))
        _invoke(
            "capability", "new", "fobo", "--name", "FOBO reconciliation",
            "--project", "pnl-agent", *common,
        )
        (caps / "fobo" / "skills" / "a.md").write_text("x", encoding="utf-8")
        result = _invoke("capability", "show", "fobo", "--capabilities-dir", str(caps))
        assert result.exit_code == 0, result.output
        assert "FOBO reconciliation" in result.output
        assert "pnl-agent" in result.output
        assert "skills: 1" in result.output

    def test_show_unknown_exits_1(self, tmp_path: Path) -> None:
        result = _invoke(
            "capability", "show", "ghost", "--capabilities-dir", str(tmp_path / "caps")
        )
        assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_cli.py -q -k "List or Show"`
Expected: FAIL — no such command `list` (exit code 2).

- [ ] **Step 3: Implement `list` and `show`**

`show` reuses the `CapIdArg` singleton added in Task 5. Append to `cli.py` after
`capability_sync`:

```python
@capability_app.command("list")
def capability_list(
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """List capability workspaces on disk and whether each is synced to the DB."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    ids = capability_mod.list_capability_ids(settings.capabilities_dir)
    if not ids:
        typer.echo("No capabilities found.")
        return
    with _open_store(settings) as store:
        synced = {
            row["capability_id"]: row["status"]
            for row in store.capabilities_frame().to_dict("records")
        }
    typer.echo(f"{'id':<24} {'status':<10} synced")
    typer.echo("-" * 44)
    for cap_id in ids:
        status = synced.get(cap_id, "-")
        mark = "yes" if cap_id in synced else "not synced"
        typer.echo(f"{cap_id:<24} {status:<10} {mark}")


def _format_filter(f: CapabilityFilter) -> str:
    parts = [
        f"{label}={value}"
        for label, value in (
            ("project", f.project),
            ("stage", f.workflow_stage),
            ("asset_class", f.asset_class),
            ("model", f.model_name),
            ("search", f.search),
        )
        if value
    ]
    return ", ".join(parts) if parts else "(none — all spans)"


@capability_app.command("show")
def capability_show(
    cap_id: str = CapIdArg,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Print a capability's parsed fields and its file counts."""
    settings = _settings(capabilities_dir=capabilities_dir)
    root = settings.capabilities_dir
    try:
        cap = capability_mod.load_capability(root, cap_id)
    except (ValueError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    cap_dir = capability_mod.capability_dir(root, cap_id)
    skills_dir, det_dir = cap_dir / "skills", cap_dir / "deterministic"
    n_skills = len(list(skills_dir.glob("*.md"))) if skills_dir.is_dir() else 0
    n_det = len(list(det_dir.glob("*.py"))) if det_dir.is_dir() else 0
    typer.echo(f"id:          {cap.id}")
    typer.echo(f"name:        {cap.name}")
    typer.echo(f"description: {cap.description or '-'}")
    typer.echo(f"status:      {cap.status}")
    typer.echo(f"window_days: {cap.window_days}")
    typer.echo(f"filter:      {_format_filter(cap.filter)}")
    if cap.thresholds:
        typer.echo(f"thresholds:  {cap.thresholds}")
    typer.echo(f"files:       skills: {n_skills}, deterministic: {n_det}")
```

`_format_filter` is a plain module-level helper (put it next to the other
`_`-prefixed helpers at the bottom of `cli.py` if you prefer; keeping it beside
`show` is also fine). The `show` test asserts `"pnl-agent"` and `"skills: 1"`
appear in the output.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_cli.py -q`
Expected: PASS (all capability CLI tests).

- [ ] **Step 5: Add a README section**

In `README.md`, insert a new `## Capabilities` section immediately after the
`## Skills catalog inputs` section and before `## Dashboard UI`. The section body
is exactly this (a heading, a paragraph, one fenced `bash` block, a closing
paragraph — no nested fences):

> `## Capabilities`
>
> A **capability** is a named analysis scope — a saved span filter plus an owned
> directory of skill files — for one workflow (FOBO recon, PLEX,
> flash-vs-formal, …). `capability.yaml` on disk is the source of truth; the
> `capabilities` table mirrors it.
>
> ```bash
> pheonix capability new fobo --name "FOBO reconciliation" \
>     --project pnl-agent --stage fobo_recon --window-days 30
> pheonix capability list
> pheonix capability show fobo
> pheonix capability sync            # re-read every capability.yaml into the DB
> ```
>
> `new` scaffolds `capabilities/fobo/` with `capability.yaml`, `skills/`, and
> `deterministic/`. Edit the yaml directly and run `sync` to apply changes. Set
> `PHEONIX_CAPABILITIES_DIR` to relocate the root.

(Strip the leading `> ` quote markers — they are only here to keep the block
distinct in this plan.)

- [ ] **Step 6: Lint and full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (was 538, now ~562 with the phase's new tests).

- [ ] **Step 7: Commit**

```bash
git add src/phoenix_scraper/cli.py tests/test_capability_cli.py README.md
git commit -m "feat: pheonix capability list and show; README capabilities section"
```

---

## Self-Review

**1. Spec coverage (Phase A slice):**

| Spec element | Task |
|---|---|
| §7.3 `Capability`, `CapabilityFilter` models | Task 1 |
| §14 `capabilities_dir`, `operator_name` settings | Task 1 |
| §8.2 `capability.yaml` schema + parsing (blank→none, unknown status→active) | Task 2 |
| §8.1 directory layout (`skills/`, `deterministic/`) | Task 3 (`write_capability`) |
| §8.2 `capability_skill_dirs` auto-wiring helper | Task 3 |
| §10.2 step 4 filter→`QueryFilters` mapping (`capability_query_filters`) | Task 3 |
| §7.2 `capabilities` table (mirror of yaml, `created_at` stable) | Task 4 |
| §8.5 `pheonix capability new` | Task 5 |
| §8.5 `pheonix capability sync` (hand-edit → DB) | Task 5 |
| §8.5 `pheonix capability list`, `show` | Task 6 |
| §15 CONTRACTS.md block for `capability.py` | Task 3 |

Deferred to later phases (correctly out of Phase A): `capability_runs` and all
ladder tables (B/C), `run_capability_analysis` (B), `DELETE /capabilities` and
the rest of the API (E), `--purge` (E — the CLI has no delete verb in A; DB rows
are dropped in tests via `Store.delete_capability` directly, which is enough
surface for now).

**2. Placeholder scan:** No `TBD`/`TODO`/"handle edge cases"/"similar to Task N".
Every code step contains literal code. Task 6's `show` output builder was
rewritten as an explicit `_format_filter` helper (the earlier `str or "fallback"`
one-liner was wrong — `"prefix" + ""` is truthy, so the fallback never fired).

**3. Type consistency:**
- `scaffold_capability(root, cap_id, *, name, description, cap_filter,
  window_days)` — same signature in Task 3 interfaces, Task 3 impl, Task 5 call
  site, CONTRACTS block. ✓
- `capability_query_filters(capability, *, start, end, limit=100_000)` —
  consistent Task 3 ↔ CONTRACTS. ✓
- `Store.upsert_capability(capability) -> None`, `get_capability(id) ->
  Capability | None`, `capabilities_frame() -> DataFrame`, `delete_capability(id)
  -> bool` — consistent Task 4 ↔ Tasks 5–6 call sites. ✓
- `capability_mod` is the import alias used in every CLI task. ✓
- CLI options follow the repo's module-level singleton pattern (no inline
  `typer.Option`/`typer.Argument`; ruff `B008`). `CapIdArg` is defined in Task 5
  and reused by `show` in Task 6; `ProjectOpt`/`StageOpt`/`AssetClassOpt`/
  `SearchOpt`/`DbOpt` are reused as-is. ✓
- Tests construct `Settings(_env_file=None, ...)` — the repo convention that
  keeps a developer's real `.env` out of the run (Task 1). ✓
- `CapabilityFilter` fields (`project, workflow_stage, asset_class, model_name,
  search`) — identical in models (Task 1), yaml keys `_FILTER_KEYS` (Task 2),
  table columns (Task 4), `_capability_from_row` (Task 4), CLI options (Task 5:
  `--project/--stage/--asset-class/--search`; `model_name` intentionally not a
  `new` flag — set via yaml + `sync`). ✓

**4. Ambiguity:** `thresholds` is `dict[str, float]`; yaml ints (`rung1_min_users:
4`) load as `4.0` and compare equal to `4` — the Task 2 test asserts this
deliberately. Later phases that read a count threshold must `int(...)` it; noted
here so it is not a surprise in Phase C.

---

## Execution Handoff

**Plan complete and saved to
`docs/superpowers/plans/2026-09-07-capability-ladder-phase-a.md`. Two execution
options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task,
review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans,
batch execution with checkpoints for review.

**Which approach?**
