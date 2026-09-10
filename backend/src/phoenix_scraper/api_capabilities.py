"""Capability CRUD + run-trigger HTTP routes (mounted under the protected router)."""

import json
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
import pandas as pd

from . import capability as capability_mod
from . import skill_coverage
from .capability_run import run_capabilities
from .config import Settings
from .models import Capability, CapabilityFilter
from .phoenix_client import PhoenixClientWrapper
from .storage import Store


def _aware(dt: datetime) -> datetime:
    """Force UTC-aware — Pydantic accepts naive ISO strings which crash vs now(UTC)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class CapabilityCreate(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    filter: CapabilityFilter = Field(default_factory=CapabilityFilter)
    window_days: int = 30
    thresholds: dict[str, float] = Field(default_factory=dict)


class CapabilityPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    filter: CapabilityFilter | None = None
    window_days: int | None = None
    thresholds: dict[str, float] | None = None
    status: str | None = None


class RunRequest(BaseModel):
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    replace_today: bool = False

    model_config = {"populate_by_name": True}

    @field_validator("from_", "to")
    @classmethod
    def _utc_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class JobRequest(BaseModel):
    """SPA enqueue requires a closed [from, to] so scrapes can subdivide safely."""

    from_: datetime = Field(alias="from")
    to: datetime
    replace_today: bool = False

    model_config = {"populate_by_name": True}

    @field_validator("from_", "to")
    @classmethod
    def _utc_aware(cls, value: datetime) -> datetime:
        return _aware(value)


# A capability's own skill files are loose `<cap>/skills/<name>.md`. Keep the
# name a kebab slug so it can never escape the directory or collide with the
# `<id>` masks normalize.py writes.
_SKILL_FILENAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}\.md$")

# Skill files are hand-sized markdown; a megabyte is already absurd for one.
_MAX_SKILL_BYTES = 1_000_000


class SkillFileBody(BaseModel):
    filename: str
    content: str


class FilterPreview(BaseModel):
    """Try a span filter without saving or running anything.

    Prefer an explicit operator ``from``/``to`` (the run window). ``window_days``
    remains as a fallback when no absolute range is supplied.
    """

    filter: CapabilityFilter = Field(default_factory=CapabilityFilter)
    window_days: int | None = Field(default=None, gt=0)
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    samples: int = Field(default=8, ge=0, le=50)

    model_config = {"populate_by_name": True}

    @field_validator("from_", "to")
    @classmethod
    def _utc_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


def capability_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    root = settings.capabilities_dir

    @contextmanager
    def _store():
        store = Store(settings.db_path)
        try:
            yield store
        finally:
            store.close()

    def _summary(store: Store, cap: Capability) -> dict:
        runs = store.capability_runs_frame(cap.id, limit=1)
        last = runs.iloc[0].to_dict() if len(runs) else None
        cands = store.candidates_frame(cap.id)
        by: dict[str, dict[str, int]] = {"skill": {}, "deterministic": {}}
        for row in cands.to_dict("records"):
            bucket = by.setdefault(row["rung"], {})
            bucket[row["status"]] = bucket.get(row["status"], 0) + 1
        return {
            "id": cap.id, "name": cap.name, "status": cap.status,
            "filter": cap.filter.model_dump(),
            "window_days": cap.window_days,
            "last_run": last, "candidates": by,
        }

    @router.get("/capabilities")
    def list_capabilities() -> list[dict]:
        with _store() as store:
            rows = store.capabilities_frame().to_dict("records")
            caps = [store.get_capability(row["capability_id"]) for row in rows]
            return [_summary(store, c) for c in caps if c is not None]

    @router.post("/capabilities", status_code=201)
    def create_capability(body: CapabilityCreate) -> dict:
        try:
            capability_mod.validate_id(body.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if capability_mod.config_path(root, body.id).exists():
            raise HTTPException(status_code=409, detail=f"Capability {body.id!r} exists")
        cap = Capability(
            id=body.id, name=body.name or body.id, description=body.description,
            filter=body.filter, window_days=body.window_days,
            thresholds=body.thresholds,
        )
        capability_mod.write_capability(root, cap)
        with _store() as store:
            store.upsert_capability(cap)
            return _summary(store, cap)

    @router.post("/capabilities/preview")
    def preview_filter(body: FilterPreview) -> dict:
        """What would this filter catch? Counts, the values present, and real
        matched prompts — so a search pattern can be tuned before it is saved."""
        from .models import QueryFilters

        now = datetime.now(UTC)
        start, end, window_days = _preview_window(body, now)
        f = body.filter
        qf = QueryFilters(
            project=f.project, workflow_stage=f.workflow_stage,
            asset_class=f.asset_class, model_name=f.model_name,
            search=f.search, search_any=f.search_any,
            start=start, end=end, limit=100_000,
        )
        with _store() as store:
            spans = store.spans_frame(qf)
            total = store.span_count()
        base = {
            "n_spans_in_store": total,
            "window_days": window_days,
            "from": start.isoformat(),
            "to": end.isoformat(),
        }
        if spans.empty:
            return {
                **base,
                "n_spans": 0, "n_llm_spans": 0, "n_users": 0, "n_sessions": 0,
                "distinct": {"workflow_stage": [], "asset_class": [], "project": []},
                "sample_prompts": [],
            }
        llm = spans[spans["span_kind"] == "LLM"] if "span_kind" in spans else spans
        prompts = [
            p for p in (llm["input_text"].fillna("").astype(str) if "input_text" in llm
                        else [])
            if p.strip()
        ]

        def distinct(column: str) -> list[str]:
            if column not in spans:
                return []
            return sorted({str(v) for v in spans[column].dropna() if str(v).strip()})

        return {
            **base,
            "n_spans": int(len(spans)),
            "n_llm_spans": int(len(llm)),
            "n_users": int(spans["user_id"].nunique()) if "user_id" in spans else 0,
            "n_sessions": (
                int(spans["session_id"].nunique()) if "session_id" in spans else 0
            ),
            "distinct": {
                "workflow_stage": distinct("workflow_stage"),
                "asset_class": distinct("asset_class"),
                "project": distinct("project"),
            },
            "sample_prompts": prompts[: body.samples],
        }

    @router.get("/capabilities/{cap_id}")
    def get_capability(cap_id: str) -> dict:
        cap_dir = capability_mod.capability_dir(root, cap_id)
        skills_dir = cap_dir / "skills"
        skill_files = (
            sorted(p.name for p in skills_dir.glob("*.md"))
            if skills_dir.is_dir()
            else []
        )
        with _store() as store:
            cap = store.get_capability(cap_id)
            if cap is None:
                raise HTTPException(status_code=404, detail=f"No capability {cap_id!r}")
            return {
                "capability": cap.model_dump(),
                "summary": _summary(store, cap),
                "skill_files": skill_files,
            }

    @router.patch("/capabilities/{cap_id}")
    def patch_capability(cap_id: str, body: CapabilityPatch) -> dict:
        with _store() as store:
            cap = store.get_capability(cap_id)
        if cap is None:
            raise HTTPException(status_code=404, detail=f"No capability {cap_id!r}")
        updates = dict(body.model_dump(exclude_none=True))
        try:
            # Re-validate rather than model_copy: model_copy skips validation, so a
            # patched `filter` would stay a plain dict and blow up on dump_capability.
            cap = Capability.model_validate({**cap.model_dump(), **updates})
        except Exception as exc:  # noqa: BLE001 — pydantic validation -> 422
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        capability_mod.write_capability(root, cap)
        with _store() as store:
            store.upsert_capability(cap)
            return {"capability": cap.model_dump()}

    @router.delete("/capabilities/{cap_id}")
    def delete_capability(cap_id: str, purge: bool = Query(default=False)) -> dict:
        with _store() as store:
            removed = store.delete_capability(cap_id)
        if purge:
            shutil.rmtree(
                capability_mod.capability_dir(root, cap_id), ignore_errors=True
            )
        return {"deleted": removed, "purged": purge}

    @router.post("/capabilities/{cap_id}/sync")
    def sync_capability(cap_id: str) -> dict:
        try:
            cap = capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        with _store() as store:
            store.upsert_capability(cap)
            return {"capability": cap.model_dump()}

    def _skills_dir(cap_id: str):
        """`<capabilities_dir>/<id>/skills`, verified to belong to a real capability."""
        try:
            capability_mod.validate_id(cap_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not capability_mod.config_path(root, cap_id).is_file():
            raise HTTPException(status_code=404, detail=f"No capability {cap_id!r}")
        return capability_mod.capability_dir(root, cap_id) / "skills"

    def _skill_row(path) -> dict:
        from .skills import scan_skill_files

        entries = scan_skill_files([path])
        entry = entries[0] if entries else None
        return {
            "filename": path.name,
            "bytes": path.stat().st_size,
            # False when the frontmatter is missing/malformed — the run silently
            # skips such a file, so say so instead of pretending it landed.
            "valid": entry is not None,
            "name": entry.name if entry else None,
            "description": entry.description if entry else None,
            "n_example_prompts": len(entry.example_prompts) if entry else 0,
        }

    @router.get("/capabilities/{cap_id}/skills")
    def list_skill_files(cap_id: str) -> list[dict]:
        skills_dir = _skills_dir(cap_id)
        if not skills_dir.is_dir():
            return []
        return [_skill_row(p) for p in sorted(skills_dir.glob("*.md"))]

    @router.post("/capabilities/{cap_id}/skills", status_code=201)
    def put_skill_file(cap_id: str, body: SkillFileBody) -> dict:
        skills_dir = _skills_dir(cap_id)
        filename = body.filename.strip().lower()
        if not filename.endswith(".md"):
            filename += ".md"
        if not _SKILL_FILENAME_RE.match(filename):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid skill filename {filename!r}: lowercase letters, digits "
                "and hyphens, starting with a letter, ending in .md.",
            )
        if len(body.content.encode("utf-8")) > _MAX_SKILL_BYTES:
            raise HTTPException(status_code=413, detail="Skill file is too large.")
        skills_dir.mkdir(parents=True, exist_ok=True)
        path = skills_dir / filename
        existed = path.is_file()
        path.write_text(body.content, encoding="utf-8")
        row = _skill_row(path)
        if not row["valid"]:
            # Written, but the miner will skip it — a 201 that quietly does
            # nothing is worse than saying why.
            path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail="No usable YAML frontmatter: a skill file needs `---` "
                "delimiters with at least a `name:` field.",
            )
        row["replaced"] = existed
        return row

    @router.delete("/capabilities/{cap_id}/skills/{filename}")
    def delete_skill_file(cap_id: str, filename: str) -> dict:
        skills_dir = _skills_dir(cap_id)
        if not _SKILL_FILENAME_RE.match(filename):
            raise HTTPException(status_code=400, detail="Invalid skill filename")
        path = skills_dir / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"No skill file {filename!r}")
        path.unlink()
        return {"deleted": filename}

    _register_run_routes(router, settings, _store)
    return router


def _preview_window(
    body: FilterPreview, now: datetime
) -> tuple[datetime, datetime, int]:
    """Resolve the operator-picked preview window (absolute range wins)."""
    if body.from_ is not None or body.to is not None:
        end = body.to or now
        if body.from_ is not None:
            start = body.from_
        else:
            days = body.window_days or 30
            start = end - timedelta(days=days)
        window_days = max(1, int((end - start).total_seconds() // 86_400))
        return start, end, window_days
    days = body.window_days or 30
    return now - timedelta(days=days), now, days


def _run_summary(row: dict) -> dict:
    out = dict(row)
    out["notes"] = json.loads(row.get("notes_json") or "[]")
    out["skill_hashes"] = json.loads(row.get("skill_hashes_json") or "{}")
    out.pop("notes_json", None)
    out.pop("skill_hashes_json", None)
    return out


def _funnel_from_run(
    row: dict, *, n_uncovered: int, n_unmatched: int
) -> dict:
    """Funnel counts + which stage emptied (for Results empty states)."""
    n_spans = int(row.get("n_spans") or 0)
    n_in_scope = int(row.get("n_in_scope_spans") or 0)
    n_clusters = int(row.get("n_clusters") or 0)
    n_rung1 = int(row.get("n_rung1_candidates") or 0)
    n_rung2 = int(row.get("n_rung2_candidates") or 0)
    empty_at: str | None = None
    empty_reason: str | None = None
    notes = row.get("notes") if isinstance(row.get("notes"), list) else []
    for note in notes:
        if isinstance(note, str) and note.startswith("funnel empty at "):
            rest = note[len("funnel empty at "):]
            empty_at = rest.split(":", 1)[0].strip()
            empty_reason = note
            break
        if isinstance(note, str) and note.startswith("funnel clear at "):
            empty_reason = note
            break
    if empty_at is None and empty_reason is None:
        if n_in_scope == 0:
            empty_at, empty_reason = "in_scope", "No in-scope spans in this window."
        elif n_clusters == 0:
            empty_at, empty_reason = "clusters", "In-scope spans produced no clusters."
        elif n_uncovered == 0 and n_unmatched == 0 and n_clusters > 0:
            empty_reason = "All clusters are covered by uploaded skills."
    return {
        "n_spans": n_spans,
        "n_in_scope_spans": n_in_scope,
        "n_clusters": n_clusters,
        "n_uncovered": n_uncovered,
        "n_unmatched": n_unmatched,
        "n_rung1_candidates": n_rung1,
        "n_rung2_candidates": n_rung2,
        "empty_at": empty_at,
        "empty_reason": empty_reason,
    }


def _records(df) -> list[dict]:  # noqa: ANN001
    if df is None or getattr(df, "empty", True):
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _candidate_records(df) -> list[dict]:  # noqa: ANN001
    """Candidate rows with JSON blob columns parsed (same shape as GET /candidates)."""
    rows = _records(df)
    for row in rows:
        row["current_evidence"] = json.loads(row.pop("current_evidence_json", "{}") or "{}")
        row["promoted_artifact_paths"] = json.loads(
            row.pop("promoted_artifact_paths_json", "[]") or "[]"
        )
    return rows


def _build_run_results(
    store: Store, settings: Settings, cap_id: str, run_id: str, row: dict
) -> dict:
    from .capability_run import load_capability_skills

    summary = _run_summary(row)
    notes = summary.get("notes") or []
    warnings = [
        n for n in notes
        if isinstance(n, str) and (
            n.startswith("TRUNCATED:")
            or "could not be narrowed" in n
            or "never saw" in n
        )
    ]

    try:
        cap = capability_mod.load_capability(settings.capabilities_dir, cap_id)
        skills = load_capability_skills(settings, cap)
    except (ValueError, FileNotFoundError):
        skills = []

    snap = store.capability_run_snapshot_frame(cap_id, run_id)
    previous = store.previous_capability_run_id(cap_id, before=run_id)
    deltas = skill_coverage.cluster_deltas(
        snap, store.capability_run_snapshot_frame(cap_id, previous)
    )
    if snap.empty:
        annotated = snap
        uncovered = skill_coverage.uncovered_queries(annotated, deltas)
        updates = skill_coverage.suggested_updates(
            uncovered, skills, max_prompts=settings.max_suggested_prompts
        )
    else:
        clusters_df = snap.loc[
            :, ["cluster_id", "signature", "representative", "count", "n_users",
                "first_seen", "last_seen"]
        ]
        matched = snap.loc[snap["skill_name"].notna() & (snap["skill_name"] != "")]
        matches_df = (
            matched.loc[:, ["cluster_id", "skill_name"]].assign(score=0.0)
            if not matched.empty
            else pd.DataFrame(columns=["cluster_id", "skill_name", "score"])
        )
        annotated = skill_coverage.annotate_coverage(
            clusters_df, matches_df, skills,
            threshold=settings.skill_coverage_threshold,
        )
        uncovered = skill_coverage.uncovered_queries(annotated, deltas)
        updates = skill_coverage.suggested_updates(
            uncovered, skills, max_prompts=settings.max_suggested_prompts
        )

    cands = store.candidates_observed_in_run(cap_id, run_id)
    if cands.empty:
        rung1, rung2 = [], []
    else:
        rung1 = _candidate_records(cands[cands["rung"] == "skill"])
        rung2 = _candidate_records(cands[cands["rung"] == "deterministic"])

    n_unmatched = 0
    if not snap.empty and "skill_name" in snap.columns:
        blank = snap["skill_name"].isna() | (snap["skill_name"].astype(str) == "")
        n_unmatched = int(blank.sum())

    funnel = _funnel_from_run(
        summary,
        n_uncovered=int(len(uncovered)),
        n_unmatched=n_unmatched,
    )
    return {
        "capability_id": cap_id,
        "run_id": run_id,
        "status": summary.get("status"),
        "window_start": summary.get("window_start"),
        "window_end": summary.get("window_end"),
        "notes": notes,
        "warnings": warnings,
        "skill_hashes": summary.get("skill_hashes") or {},
        "funnel": funnel,
        "uncovered": _records(uncovered),
        "suggested_skill_updates": _records(updates),
        "rung1_candidates": rung1,
        "rung2_candidates": rung2,
        "previous_run_id": previous,
    }


def _gap_rows(snap) -> list[dict]:  # noqa: ANN001
    """Clusters that are unmatched or matched-but-not-covered (skill gaps)."""
    if snap is None or getattr(snap, "empty", True):
        return []
    rows = []
    for rec in snap.to_dict("records"):
        skill = rec.get("skill_name")
        unmatched = skill is None or str(skill).strip() == ""
        covered = int(rec.get("covered") or 0) == 1
        if unmatched or not covered:
            rows.append(
                {
                    "cluster_id": rec.get("cluster_id"),
                    "representative": rec.get("representative") or "",
                    "count": int(rec.get("count") or 0),
                    "n_users": int(rec.get("n_users") or 0),
                    "skill_name": None if unmatched else str(skill),
                    "covered": covered,
                    "reason": "unmatched" if unmatched else "uncovered",
                }
            )
    return rows


_STATUS_RANK = {
    "new": 0,
    "accumulating": 1,
    "insufficient_data": 2,
    "ready": 3,
    "accepted": 4,
    "promoted": 5,
    "snoozed": -1,
    "rejected": -2,
    "stale": -3,
}


def _skill_hash_diff(from_hashes: dict, to_hashes: dict) -> dict:
    from_keys = set(from_hashes)
    to_keys = set(to_hashes)
    changed = [
        {"filename": name, "from": from_hashes[name], "to": to_hashes[name]}
        for name in sorted(from_keys & to_keys)
        if from_hashes[name] != to_hashes[name]
    ]
    return {
        "added": sorted(to_keys - from_keys),
        "removed": sorted(from_keys - to_keys),
        "changed": changed,
        "unchanged": sorted(
            name for name in from_keys & to_keys if from_hashes[name] == to_hashes[name]
        ),
    }


def _candidates_advancing(from_cands, to_cands) -> list[dict]:  # noqa: ANN001
    """Candidates that moved to a higher ladder status between two runs."""
    if to_cands is None or getattr(to_cands, "empty", True):
        return []
    from_by_id = {}
    if from_cands is not None and not getattr(from_cands, "empty", True):
        from_by_id = {
            row["candidate_id"]: row for row in from_cands.to_dict("records")
        }
    advancing = []
    for row in to_cands.to_dict("records"):
        cid = row["candidate_id"]
        to_status = str(row.get("status") or "")
        prev = from_by_id.get(cid)
        if prev is None:
            advancing.append(
                {
                    "candidate_id": cid,
                    "rung": row.get("rung"),
                    "title": row.get("title") or "",
                    "from_status": None,
                    "to_status": to_status,
                    "change": "new",
                }
            )
            continue
        from_status = str(prev.get("status") or "")
        if _STATUS_RANK.get(to_status, -99) > _STATUS_RANK.get(from_status, -99):
            advancing.append(
                {
                    "candidate_id": cid,
                    "rung": row.get("rung"),
                    "title": row.get("title") or "",
                    "from_status": from_status,
                    "to_status": to_status,
                    "change": "advanced",
                }
            )
    return advancing


def _build_run_compare(
    store: Store, cap_id: str, from_run: str, to_run: str
) -> dict:
    """Diff two versions: skill hashes, gaps closed/new, candidates advancing."""
    from_row = store.get_capability_run(cap_id, from_run)
    to_row = store.get_capability_run(cap_id, to_run)
    if from_row is None:
        raise HTTPException(status_code=404, detail=f"No such run: {from_run}")
    if to_row is None:
        raise HTTPException(status_code=404, detail=f"No such run: {to_run}")

    from_summary = _run_summary(from_row)
    to_summary = _run_summary(to_row)
    from_snap = store.capability_run_snapshot_frame(cap_id, from_run)
    to_snap = store.capability_run_snapshot_frame(cap_id, to_run)

    from_gaps = {g["cluster_id"]: g for g in _gap_rows(from_snap)}
    to_gaps = {g["cluster_id"]: g for g in _gap_rows(to_snap)}
    closed_ids = set(from_gaps) - set(to_gaps)
    new_ids = set(to_gaps) - set(from_gaps)

    from_cands = store.candidates_observed_in_run(cap_id, from_run)
    to_cands = store.candidates_observed_in_run(cap_id, to_run)

    return {
        "capability_id": cap_id,
        "from_run": {
            "run_id": from_run,
            "window_start": from_summary.get("window_start"),
            "window_end": from_summary.get("window_end"),
            "skill_hashes": from_summary.get("skill_hashes") or {},
            "n_gaps": len(from_gaps),
        },
        "to_run": {
            "run_id": to_run,
            "window_start": to_summary.get("window_start"),
            "window_end": to_summary.get("window_end"),
            "skill_hashes": to_summary.get("skill_hashes") or {},
            "n_gaps": len(to_gaps),
        },
        "skill_hash_changes": _skill_hash_diff(
            from_summary.get("skill_hashes") or {},
            to_summary.get("skill_hashes") or {},
        ),
        "gaps_closed": [from_gaps[cid] for cid in sorted(closed_ids)],
        "gaps_new": [to_gaps[cid] for cid in sorted(new_ids)],
        "candidates_advancing": _candidates_advancing(from_cands, to_cands),
        "cluster_deltas": _records(
            skill_coverage.cluster_deltas(to_snap, from_snap)
        ),
    }


def _register_run_routes(router: APIRouter, settings: Settings, _store) -> None:  # noqa: ANN001
    root = settings.capabilities_dir

    @router.post("/capabilities/{cap_id}/runs")
    def trigger_run(cap_id: str, body: RunRequest) -> dict:
        try:
            capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        client = PhoenixClientWrapper(settings)
        with _store() as store:
            results = run_capabilities(
                store, settings, capability_ids=[cap_id],
                client=client if client.available() else None,
                window_start=body.from_, window_end=body.to,
                replace_today=body.replace_today,
            )
            row = store.capability_runs_frame(cap_id, limit=1).iloc[0].to_dict()
        summary = _run_summary(row)
        summary["previous_run_id"] = results[0].previous_run_id
        summary["status"] = results[0].run.status
        return summary

    @router.get("/capabilities/{cap_id}/runs")
    def run_history(cap_id: str, fmt: str = "json"):
        from .api import _frame_response
        with _store() as store:
            df = store.capability_runs_frame(cap_id)
        return _frame_response(df, fmt, "capability_runs")

    # Registered before /runs/{run_id} so "delta" / "compare" are not read as run ids.
    @router.get("/capabilities/{cap_id}/runs/delta")
    def run_delta(
        cap_id: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None),
        fmt: str = "json",
    ):
        from .api import _frame_response
        with _store() as store:
            latest = to or store.previous_capability_run_id(cap_id)
            prev = from_ or store.previous_capability_run_id(cap_id, before=latest)
            df = skill_coverage.cluster_deltas(
                store.capability_run_snapshot_frame(cap_id, latest),
                store.capability_run_snapshot_frame(cap_id, prev),
            )
        return _frame_response(df, fmt, "capability_run_delta")

    @router.get("/capabilities/{cap_id}/runs/compare")
    def run_compare(
        cap_id: str,
        from_run: str = Query(..., alias="from_run"),
        to_run: str = Query(..., alias="to_run"),
    ) -> dict:
        """Side-by-side last vs this version: gaps closed/new, skill hashes, candidates."""
        with _store() as store:
            return _build_run_compare(store, cap_id, from_run, to_run)

    # Registered before /runs/{run_id} so "results" is not swallowed as a run id
    # when someone hits a typo path — actual results live under .../runs/{id}/results.
    @router.get("/capabilities/{cap_id}/runs/{run_id}/results")
    def run_results(cap_id: str, run_id: str) -> dict:
        with _store() as store:
            row = store.get_capability_run(cap_id, run_id)
            if row is None:
                raise HTTPException(status_code=404, detail="No such run")
            return _build_run_results(store, settings, cap_id, run_id, row)

    @router.get("/capabilities/{cap_id}/runs/{run_id}")
    def one_run(cap_id: str, run_id: str) -> dict:
        with _store() as store:
            row = store.get_capability_run(cap_id, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="No such run")
        return _run_summary(row)

    @router.post("/capabilities/{cap_id}/jobs", status_code=202)
    def enqueue_run_job(cap_id: str, body: JobRequest) -> dict:
        try:
            capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if body.to <= body.from_:
            raise HTTPException(
                status_code=422,
                detail="Job window requires to > from (closed [from, to] range).",
            )
        job_id = uuid.uuid4().hex
        params = {
            "from": body.from_.isoformat(),
            "to": body.to.isoformat(),
            "replace_today": body.replace_today,
        }
        with _store() as store:
            store.enqueue_job(job_id, cap_id, params)
        return {
            "job_id": job_id,
            "capability_id": cap_id,
            "state": "queued",
            "stage": "queued",
            "progress": 0.0,
            "message": None,
        }

    @router.get("/capabilities/{cap_id}/jobs")
    def list_run_jobs(cap_id: str, fmt: str = "json"):
        from .api import _frame_response
        with _store() as store:
            df = store.capability_jobs_frame(cap_id)
        return _frame_response(df, fmt, "capability_jobs")

    @router.get("/capabilities/{cap_id}/jobs/{job_id}")
    def one_run_job(cap_id: str, job_id: str) -> dict:
        with _store() as store:
            job = store.get_job(job_id)
        if job is None or job["capability_id"] != cap_id:
            raise HTTPException(status_code=404, detail="No such job")
        return job
