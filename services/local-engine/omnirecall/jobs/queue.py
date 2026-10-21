"""Persistent job runner with bounded concurrency, retries, and backoff.

Jobs live in SQLite before any work begins (rules.md §2.5). Workers claim
jobs atomically; a failure is retried with the configured backoff until the
retry budget is spent. On startup, jobs left `running` are re-queued.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from omnirecall import logs
from omnirecall.errors import EngineError
from omnirecall.ids import parse_utc
from omnirecall.storage.repository import Job, Repository

StageHandler = Callable[[Job, Callable[[], bool]], None]
ExhaustedHandler = Callable[[Job, str], None]


class JobRunner:
    def __init__(
        self,
        repo: Repository,
        concurrency: int,
        max_retries: int,
        backoff_s: list[int],
        on_exhausted: ExhaustedHandler,
    ) -> None:
        self.repo = repo
        self.concurrency = concurrency
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.on_exhausted = on_exhausted
        self._handlers: dict[str, StageHandler] = {}
        self._stop = threading.Event()
        self._wake = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._active = 0
        self._active_lock = threading.Lock()

    def register(self, stage: str, handler: StageHandler) -> None:
        self._handlers[stage] = handler

    @property
    def active(self) -> int:
        with self._active_lock:
            return self._active

    def start(self) -> None:
        self._stop.clear()
        recovered = self.repo.reset_running_jobs()
        if recovered:
            logs.info("jobs_recovered", count=recovered)
        for index in range(self.concurrency):
            thread = threading.Thread(target=self._loop, name=f"job-worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def wake(self) -> None:
        with self._wake:
            self._wake.notify_all()

    def stop(self, timeout: float = 30.0) -> None:
        with self._wake:
            self._stop.set()
            self._wake.notify_all()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def stopping(self) -> bool:
        return self._stop.is_set()

    def _wait_time(self) -> float:
        due = self.repo.next_job_due()
        if due is None:
            return 5.0
        seconds = (parse_utc(due) - datetime.now(UTC)).total_seconds()
        return max(0.05, min(seconds, 5.0))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.repo.claim_job()
            except Exception as exc:  # noqa: BLE001 - keep the worker alive; retry shortly
                logs.error("job_claim_failed", reason=type(exc).__name__)
                job = None
            if job is None:
                timeout = self._wait_time()
                with self._wake:
                    if not self._stop.is_set():
                        self._wake.wait(timeout=timeout)
                continue
            self.run_one(job)

    def run_one(self, job: Job) -> None:
        handler = self._handlers.get(job.stage)
        with self._active_lock:
            self._active += 1
        try:
            if handler is None:
                raise EngineError("unknown_stage", "Unknown job stage")
            handler(job, self.stopping)
            if self.repo.job_status(job.id) == "running":
                self.repo.complete_job(job.id)
        except EngineError as exc:
            self._fail(job, exc.code)
        except Exception as exc:  # noqa: BLE001 - recorded as a sanitized error code
            self._fail(job, f"internal:{type(exc).__name__}")
        finally:
            with self._active_lock:
                self._active -= 1

    def _fail(self, job: Job, code: str) -> None:
        if self.repo.job_status(job.id) == "cancelled":
            return
        # Errors that retrying cannot fix go straight to failed.
        retryable = code not in PERMANENT_ERRORS
        will_retry = retryable and self.repo.fail_job(job, code, self.backoff_s, self.max_retries)
        if not retryable:
            self.repo.fail_job(job, code, self.backoff_s, max_retries=-1)
        logs.warning("job_failed", job_id=job.id, error_code=code, attempt=job.attempt_count + 1)
        if not will_retry:
            self.on_exhausted(job, code)


PERMANENT_ERRORS = frozenset(
    {
        "unsupported_format",
        "limit_exceeded",
        "invalid_params",
        "not_found",
        "extraction_empty",
        "model_missing",
        "source_missing",
        "payload_missing",
        "encrypted_file",
        "malformed_file",
        "binary_content",
        "unsupported_source",
    }
)
