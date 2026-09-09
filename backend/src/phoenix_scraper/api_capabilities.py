"""Capability CRUD + run-trigger HTTP routes (mounted under the protected router)."""

import json
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import capability as capability_mod
from . import skill_coverage
from .capability_run import run_capabilities
from .config import Settings
from .models import Capability, CapabilityFilter
from .phoenix_client import PhoenixClientWrapper
from .storage import Store


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


class JobRequest(BaseModel):
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    replace_today: bool = False

    model_config = {"populate_by_name": True}


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
    """Try a span filter without saving or running anything."""

    filter: CapabilityFilter = Field(default_factory=CapabilityFilter)
    window_days: int = Field(default=30, gt=0)
    samples: int = Field(default=8, ge=0, le=50)


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
        f = body.filter
        qf = QueryFilters(
            project=f.project, workflow_stage=f.workflow_stage,
            asset_class=f.asset_class, model_name=f.model_name,
            search=f.search, search_any=f.search_any,
            start=now - timedelta(days=body.window_days), end=now, limit=100_000,
        )
        with _store() as store:
            spans = store.spans_frame(qf)
            total = store.span_count()
        if spans.empty:
            return {
                "n_spans": 0, "n_llm_spans": 0, "n_users": 0, "n_sessions": 0,
                "n_spans_in_store": total, "window_days": body.window_days,
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
            "n_spans": int(len(spans)),
            "n_llm_spans": int(len(llm)),
            "n_users": int(spans["user_id"].nunique()) if "user_id" in spans else 0,
            "n_sessions": (
                int(spans["session_id"].nunique()) if "session_id" in spans else 0
            ),
            "n_spans_in_store": total,
            "window_days": body.window_days,
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


def _run_summary(row: dict) -> dict:
    out = dict(row)
    out["notes"] = json.loads(row.get("notes_json") or "[]")
    return out


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

    # Registered before /runs/{run_id} so "delta" is not read as a run id.
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

    @router.get("/capabilities/{cap_id}/runs/{run_id}")
    def one_run(cap_id: str, run_id: str) -> dict:
        with _store() as store:
            df = store.capability_runs_frame(cap_id, limit=200)
        match = df[df["run_id"] == run_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="No such run")
        return _run_summary(match.iloc[0].to_dict())

    @router.post("/capabilities/{cap_id}/jobs", status_code=202)
    def enqueue_run_job(cap_id: str, body: JobRequest) -> dict:
        try:
            capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        job_id = uuid.uuid4().hex
        params = {
            "from": body.from_.isoformat() if body.from_ else None,
            "to": body.to.isoformat() if body.to else None,
            "replace_today": body.replace_today,
        }
        with _store() as store:
            store.enqueue_job(job_id, cap_id, params)
        return {"job_id": job_id, "capability_id": cap_id, "state": "queued"}

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
