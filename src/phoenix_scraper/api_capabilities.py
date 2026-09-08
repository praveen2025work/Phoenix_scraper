"""Capability CRUD + run-trigger HTTP routes (mounted under the protected router)."""

import json
import shutil
from contextlib import contextmanager
from datetime import datetime

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
            cap = cap.model_copy(update=updates)
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
