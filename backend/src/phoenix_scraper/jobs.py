"""Background workers for capability runs — pooled threads, one run per capability.

Polls ``capability_jobs``; claims the oldest queued job whose capability is not
already running; executes ``run_capabilities`` and records the outcome. Opt-in via
``api.create_app(..., run_jobs=True)``.

``PHEONIX_JOB_WORKERS`` (default 2) controls pool size. Cancel is cooperative:
queued jobs finish immediately as cancelled; running jobs are flagged and abort
on the next progress tick.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from .capability_run import run_capabilities
from .config import Settings
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

logger = logging.getLogger(__name__)

_TRUNCATION_MARKERS = ("TRUNCATED:", "could not be narrowed", "never saw")


class JobCancelled(Exception):
    """Raised when an operator cancels a running capability job."""


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _job_finish_message(notes: tuple[str, ...] | list[str], *, ok: bool) -> str:
    for note in notes:
        if any(marker in note for marker in _TRUNCATION_MARKERS):
            return note[:500]
    if ok:
        return "Run complete"
    return "Run finished with errors"


class JobWorker:
    def __init__(
        self,
        settings: Settings,
        *,
        poll_seconds: float = 1.0,
        workers: int | None = None,
    ) -> None:
        self.settings = settings
        self.poll_seconds = poll_seconds
        self.workers = max(1, int(workers if workers is not None else settings.job_workers))
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._cancel_requested: set[str] = set()
        self._cancel_lock = threading.Lock()
        self._claim_lock = threading.Lock()

    def start(self) -> None:
        if any(t.is_alive() for t in self._threads):
            return
        self._stop.clear()
        self._wake.set()
        self._threads = []
        for i in range(self.workers):
            t = threading.Thread(
                target=self._loop, name=f"pheonix-jobs-{i}", daemon=True
            )
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout)
        self._threads = []

    def notify(self) -> None:
        self._wake.set()

    def is_alive(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def request_cancel(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancel_requested.add(job_id)
        self._wake.set()

    def _is_cancelled(self, job_id: str) -> bool:
        with self._cancel_lock:
            return job_id in self._cancel_requested

    def _clear_cancel(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancel_requested.discard(job_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                while not self._stop.is_set() and self.drain_once() is not None:
                    pass
            except Exception:  # noqa: BLE001
                logger.exception("job worker iteration failed")

    def drain_once(self) -> str | None:
        # Serialize claims so pooled workers don't race on the same SQLite row.
        with self._claim_lock:
            with Store(self.settings.db_path) as store:
                job = store.claim_next_job()
                if job is None:
                    return None
                job_id = job["job_id"]
        with Store(self.settings.db_path) as store:
            self._run(store, job)
        return job_id

    def _run(self, store: Store, job: dict) -> None:
        params = job["params"]
        job_id = job["job_id"]

        def on_progress(stage: str, progress: float, message: str) -> None:
            if self._is_cancelled(job_id):
                raise JobCancelled(f"job {job_id} cancelled")
            # Also honour cancel persisted by another process/API call.
            latest = store.get_job(job_id)
            if latest and str(latest.get("message") or "").startswith("cancel-requested"):
                raise JobCancelled(f"job {job_id} cancelled")
            store.update_job_progress(
                job_id, stage=stage, progress=progress, message=message
            )

        try:
            if self._is_cancelled(job_id):
                raise JobCancelled(f"job {job_id} cancelled")
            client = PhoenixClientWrapper(self.settings)
            results = run_capabilities(
                store,
                self.settings,
                capability_ids=[job["capability_id"]],
                client=client if client.available() else None,
                window_start=_parse_dt(params.get("from")),
                window_end=_parse_dt(params.get("to")),
                replace_today=bool(params.get("replace_today", False)),
                on_progress=on_progress,
            )
            if self._is_cancelled(job_id):
                raise JobCancelled(f"job {job_id} cancelled")
            run = results[0].run if results else None
            run_id = run.run_id if run else None
            notes = list(run.notes) if run else []
            store.finish_job(
                job_id,
                run_id=run_id,
                state="done",
                message=_job_finish_message(notes, ok=True),
            )
        except JobCancelled:
            store.finish_job(
                job_id,
                run_id=None,
                state="error",
                error="cancelled",
                message="Cancelled by operator",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("capability job %s failed", job_id)
            store.finish_job(
                job_id,
                run_id=None,
                state="error",
                error=f"{type(exc).__name__}: {exc}"[:2000],
                message=f"{type(exc).__name__}: {exc}"[:500],
            )
        finally:
            self._clear_cancel(job_id)
