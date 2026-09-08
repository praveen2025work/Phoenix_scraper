"""Ladder board / candidate / decision / promote HTTP routes."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import artifacts
from . import capability as capability_mod
from .config import Settings
from .ladder import DECISION_TRANSITIONS
from .storage import Store


class DecisionBody(BaseModel):
    action: str
    actor: str | None = None
    note: str = ""
    snooze_runs: int = 3


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
            store.upsert_candidate(c.model_copy(update=updates))
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
        return {
            "paths": list(result.paths),
            "contents": [{"path": p, "body": b} for p, b in result.contents],
            "wrote_files": result.wrote_files,
        }

    @router.post("/candidates/{cid}/promote")
    def promote(cid: str, accept: bool = Query(default=False)) -> dict:
        return _promote(cid, accept=accept, dry_run=False)

    @router.get("/candidates/{cid}/artifact/preview")
    def preview(cid: str) -> dict:
        return _promote(cid, accept=False, dry_run=True)

    return router
