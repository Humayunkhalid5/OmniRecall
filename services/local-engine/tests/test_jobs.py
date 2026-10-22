"""Persistent job runner: retries, backoff, exhaustion, cancellation, recovery."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from support import make_stores, new_text_item

from omnirecall.errors import EngineError
from omnirecall.ids import parse_utc
from omnirecall.jobs.queue import JobRunner
from omnirecall.storage.repository import STAGE_PROCESS


def runner_for(repo, handler, exhausted, retries=3, backoff=(10, 60, 300)):
    runner = JobRunner(
        repo, concurrency=1, max_retries=retries, backoff_s=list(backoff), on_exhausted=exhausted
    )
    runner.register(STAGE_PROCESS, handler)
    return runner


def test_success_marks_done(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    new_text_item(repo, "a")
    seen = []
    runner = runner_for(repo, lambda job, stop: seen.append(job.item_id), lambda j, c: None)
    runner.run_one(repo.claim_job())
    assert len(seen) == 1 and repo.job_counts() == {"done": 1}


def test_retry_backoff_schedule_then_exhaustion(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    item_id = new_text_item(repo, "b")
    exhausted = []

    def fail(job, stop):
        raise EngineError("ocr_timeout", "timeout")

    runner = runner_for(repo, fail, lambda j, c: exhausted.append((j.item_id, c)))
    delays = []
    for _attempt in range(4):
        job = repo.claim_job(now=datetime.now(UTC) + timedelta(days=1))
        assert job is not None
        before = datetime.now(UTC)
        runner.run_one(job)
        row = repo.db.conn.execute(
            "SELECT status, next_attempt_at, attempt_count FROM jobs"
        ).fetchone()
        if row["status"] == "pending":
            delays.append(round((parse_utc(row["next_attempt_at"]) - before).total_seconds()))
    assert delays == [10, 60, 300]
    assert exhausted == [(item_id, "ocr_timeout")]
    assert repo.job_counts() == {"failed": 1}


def test_backoff_delays_claim(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    new_text_item(repo, "c")

    def fail(job, stop):
        raise EngineError("busy", "busy")

    runner = runner_for(repo, fail, lambda j, c: None)
    runner.run_one(repo.claim_job())
    assert repo.claim_job() is None  # not due for 10 s
    assert repo.claim_job(now=datetime.now(UTC) + timedelta(seconds=11)) is not None


def test_permanent_errors_do_not_retry(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    new_text_item(repo, "d")
    exhausted = []

    def fail(job, stop):
        raise EngineError("unsupported_format", "nope")

    runner = runner_for(repo, fail, lambda j, c: exhausted.append(c))
    runner.run_one(repo.claim_job())
    assert exhausted == ["unsupported_format"] and repo.job_counts() == {"failed": 1}


def test_unexpected_exception_is_sanitized(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    new_text_item(repo, "e")

    def boom(job, stop):
        raise RuntimeError("contains private text")

    runner = runner_for(repo, boom, lambda j, c: None)
    runner.run_one(repo.claim_job())
    code = repo.db.conn.execute("SELECT last_error_code FROM jobs").fetchone()[0]
    assert code == "internal:RuntimeError"


def test_running_jobs_recovered_on_start(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    new_text_item(repo, "f")
    assert repo.claim_job() is not None  # engine "crashes" while running
    assert repo.job_counts() == {"running": 1}
    done = []
    runner = runner_for(repo, lambda job, stop: done.append(job.id), lambda j, c: None)
    runner.start()
    try:
        for _ in range(100):
            if done:
                break
            time.sleep(0.05)
    finally:
        runner.stop()
    assert len(done) == 1 and repo.job_counts() == {"done": 1}


def test_cancelled_job_is_not_failed(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    item_id = new_text_item(repo, "g")
    exhausted = []

    def cancel_then_fail(job, stop):
        repo.cancel_jobs(item_id)
        raise EngineError("x", "x")

    runner = runner_for(repo, cancel_then_fail, lambda j, c: exhausted.append(c))
    runner.run_one(repo.claim_job())
    assert exhausted == [] and repo.job_counts() == {"cancelled": 1}
