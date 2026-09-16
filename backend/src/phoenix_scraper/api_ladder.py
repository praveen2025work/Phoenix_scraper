"""Ladder board / candidate / decision / promote HTTP routes."""

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import annotations as annotations_mod
from . import artifacts
from . import capability as capability_mod
from .config import Settings
from .ladder import (
    DECISION_TRANSITIONS,
    ensure_ready_if_qualified,
    resolve_thresholds,
)
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

logger = logging.getLogger(__name__)


class DecisionBody(BaseModel):
    action: str
    actor: str | None = None
    note: str = ""
    snooze_runs: int = 3


def _push_decision_annotation(
    store: Store,
    settings: Settings,
    candidate,
    action: str,
    *,
    actor: str,
    note: str = "",
) -> None:
    """Best-effort: mirror promote/reject onto Phoenix; never fail the local decision."""
    if action not in {"promote", "reject", "accept"}:
        return
    client = PhoenixClientWrapper(settings)
    if not client.available():
        return
    try:
        report = annotations_mod.push_ladder_decision(
            store, client, settings, candidate, action, actor=actor, note=note
        )
        logger.info(
            "pushed ladder %s annotation for %s: %d spans",
            action, candidate.candidate_id, report.stored,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Phoenix annotation push skipped for %s (%s): %s",
            candidate.candidate_id, action, exc,
        )


def _flip_ready_if_qualified(store: Store, settings: Settings, root, candidate):
    """Persist ready when met-bar evidence already satisfies current thresholds."""
    if candidate.status not in ("new", "accumulating"):
        return candidate
    try:
        cap = capability_mod.load_capability(root, candidate.capability_id)
    except (ValueError, FileNotFoundError, OSError):
        cap = store.get_capability(candidate.capability_id)
    if cap is None:
        return candidate
    thresholds = resolve_thresholds(cap, settings)
    sustained = (
        thresholds.rung2_sustained_runs
        if candidate.rung == "deterministic"
        else thresholds.rung1_sustained_runs
    )
    recent = store.recent_candidate_observations(
        candidate.candidate_id, max(sustained, 1)
    )
    run_count = store.capability_run_ordinal(candidate.capability_id)
    transition = ensure_ready_if_qualified(
        candidate,
        recent,
        capability_run_count=run_count,
        thresholds=thresholds,
    )
    if transition is None or transition.status != "ready":
        return candidate
    now = datetime.now(UTC)
    updates: dict = {"status": "ready"}
    if transition.set_ready_at and candidate.ready_at is None:
        updates["ready_at"] = now
    updated = candidate.model_copy(update=updates)
    store.upsert_candidate(updated)
    return updated


def ladder_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    root = settings.capabilities_dir

    @contextmanager
    def _store():
        store = Store(settings.db_path)
        try:
            yield store
        finally:
            store.close()

    @router.get("/capabilities/{cap_id}/candidates")
    def board(
        cap_id: str,
        rung: str | None = Query(default=None),
        status: str | None = Query(default=None),
        fmt: str = "json",
    ):
        from .api import _frame_response
        with _store() as store:
            df = store.candidates_frame(cap_id, rung=rung, status=status)
            # Unlock Accept for rows whose evidence already qualifies under
            # current thresholds (no extra analysis run required).
            if fmt != "csv":
                for cid in list(df["candidate_id"]) if not df.empty else []:
                    c = store.get_candidate(str(cid))
                    if c is not None:
                        _flip_ready_if_qualified(store, settings, root, c)
                df = store.candidates_frame(cap_id, rung=rung, status=status)
        if fmt == "csv":
            return _frame_response(df, fmt, "candidates")
        # JSON: hand back candidate objects (json fields parsed), not raw columns.
        rows = json.loads(df.to_json(orient="records"))
        for row in rows:
            row["current_evidence"] = json.loads(row.pop("current_evidence_json", "{}") or "{}")
            row["promoted_artifact_paths"] = json.loads(
                row.pop("promoted_artifact_paths_json", "[]") or "[]"
            )
        return JSONResponse(content=rows)

    @router.get("/candidates/{cid}")
    def candidate_detail(cid: str) -> dict:
        with _store() as store:
            c = store.get_candidate(cid)
            if c is None:
                raise HTTPException(status_code=404, detail="No such candidate")
            c = _flip_ready_if_qualified(store, settings, root, c)
            obs = store.candidate_observations_frame(cid)
            decisions = store.candidate_decisions_frame(cid)
        obs_records = json.loads(obs.to_json(orient="records"))
        for row in obs_records:
            row["signals"] = json.loads(row.pop("signals_json", "{}") or "{}")
        return {
            "candidate": c.model_dump(mode="json"),
            "observations": obs_records,
            "decisions": json.loads(decisions.to_json(orient="records")),
        }

    @router.post("/candidates/{cid}/decision")
    def decide(cid: str, body: DecisionBody) -> dict:
        who = body.actor or settings.operator_name or "unknown"
        if body.action not in DECISION_TRANSITIONS:
            raise HTTPException(status_code=422, detail=f"Unknown action {body.action!r}")
        allowed, target = DECISION_TRANSITIONS[body.action]
        now = datetime.now(UTC)
        with _store() as store:
            c = store.get_candidate(cid)
            if c is None:
                raise HTTPException(status_code=404, detail="No such candidate")
            if body.action == "accept":
                c = _flip_ready_if_qualified(store, settings, root, c)
            if c.status not in allowed:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot {body.action} from status {c.status!r}",
                )
            store.record_candidate_decision_now(cid, body.action, who, now, note=body.note)
            updates: dict = {"status": target, "decided_by": who, "decided_at": now}
            if body.action == "reject":
                updates["dismiss_reason"] = body.note
                updates["current_evidence"] = {
                    **c.current_evidence,
                    "count_at_rejection": c.current_evidence.get("count", 0),
                    "n_users_at_rejection": c.current_evidence.get("n_users", 0),
                }
            if body.action == "snooze":
                ordinal = store.capability_run_ordinal(c.capability_id)
                updates["snooze_until_run"] = ordinal + body.snooze_runs
            updated = c.model_copy(update=updates)
            store.upsert_candidate(updated)
            _push_decision_annotation(
                store, settings, updated, body.action, actor=who, note=body.note
            )
        return {"candidate_id": cid, "from": c.status, "to": target, "actor": who}

    def _promote(cid: str, *, accept: bool, dry_run: bool) -> dict:
        who = settings.operator_name or "api"
        now = datetime.now(UTC)
        with _store() as store:
            c = store.get_candidate(cid)
            if c is None:
                raise HTTPException(status_code=404, detail="No such candidate")
            if c.status == "ready" and accept and not dry_run:
                c = c.model_copy(update={"status": "accepted"})
                store.upsert_candidate(c)
            if c.status != "accepted" and not dry_run:
                raise HTTPException(
                    status_code=409,
                    detail=f"Candidate is {c.status!r}; accept it first",
                )
            try:
                cap = capability_mod.load_capability(root, c.capability_id)
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            result = artifacts.promote_candidate(
                store, cap, c, now=now, actor=who, settings=settings, dry_run=dry_run,
            )
            if result.wrote_files and not dry_run:
                promoted = store.get_candidate(cid) or c
                _push_decision_annotation(
                    store, settings, promoted, "promote", actor=who
                )
        return {
            "paths": list(result.paths),
            "contents": [
                {
                    "path": p,
                    "body": b,
                    "current_body": dict(result.current_bodies).get(p),
                }
                for p, b in result.contents
            ],
            "wrote_files": result.wrote_files,
        }

    @router.post("/candidates/{cid}/promote")
    def promote(cid: str, accept: bool = Query(default=False)) -> dict:
        return _promote(cid, accept=accept, dry_run=False)

    @router.get("/candidates/{cid}/artifact/preview")
    def preview(cid: str) -> dict:
        return _promote(cid, accept=False, dry_run=True)

    return router
