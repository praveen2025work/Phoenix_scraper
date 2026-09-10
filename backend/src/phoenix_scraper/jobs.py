"""Background worker for capability runs — one daemon thread, one run at a time.

Polls the capability_jobs table every `poll_seconds`; runs the oldest queued job
via run_capabilities and records the outcome back on the row. Opt-in: only
api.create_app(..., run_jobs=True) starts it.
"""

import logging
import threading
from datetime import datetime

from .capability_run import run_capabilities
from .config import Settings
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

logger = logging.getLogger(__name__)

_TRUNCATION_MARKERS = ("TRUNCATED:", "could not be narrowed", "never saw")


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _job_finish_message(notes: tuple[str, ...] | list[str], *, ok: bool) -> str:
    """Surface truncation hard-warnings first; otherwise a short stage summary."""
    for note in notes:
        if any(marker in note for marker in _TRUNCATION_MARKERS):
            return note[:500]
    if ok:
        return "Run complete"
    return "Run finished with errors"


class JobWorker:
    def __init__(self, settings: Settings, *, poll_seconds: float = 1.0) -> None:
        self.settings = settings
        self.poll_seconds = poll_seconds
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="pheonix-jobs", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.drain_once()
            except Exception:  # noqa: BLE001 — the worker thread must never die
                logger.exception("job worker iteration failed")

    def drain_once(self) -> str | None:
        with Store(self.settings.db_path) as store:
            job = store.claim_next_job()
            if job is None:
                return None
            self._run(store, job)
            return job["job_id"]

    def _run(self, store: Store, job: dict) -> None:
        params = job["params"]
        job_id = job["job_id"]

        def on_progress(stage: str, progress: float, message: str) -> None:
            store.update_job_progress(
                job_id, stage=stage, progress=progress, message=message
            )

        try:
            client = PhoenixClientWrapper(self.settings)
            results = run_capabilities(
                store, self.settings, capability_ids=[job["capability_id"]],
                client=client if client.available() else None,
                window_start=_parse_dt(params.get("from")),
                window_end=_parse_dt(params.get("to")),
                replace_today=bool(params.get("replace_today", False)),
                on_progress=on_progress,
            )
            run = results[0].run if results else None
            run_id = run.run_id if run else None
            notes = list(run.notes) if run else []
            store.finish_job(
                job_id, run_id=run_id, state="done",
                message=_job_finish_message(notes, ok=True),
            )
        except Exception as exc:  # noqa: BLE001 — infra failure -> job error
            logger.exception("capability job %s failed", job_id)
            store.finish_job(
                job_id, run_id=None, state="error",
                error=f"{type(exc).__name__}: {exc}"[:2000],
                message=f"{type(exc).__name__}: {exc}"[:500],
            )
