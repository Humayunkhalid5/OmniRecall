"""Structured, content-free diagnostics (rules.md §3.6).

Log records go to stderr (stdout carries JSON-RPC) and to the app log file.
Only an allow-listed set of fields is emitted; anything else is dropped so
captured text, queries, or paths cannot leak through an accidental kwarg.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from omnirecall.ids import utc_now

# Fields that may appear in a log record. Values must be codes, counts, IDs,
# or durations — never user content.
ALLOWED_FIELDS = frozenset(
    {
        "event",
        "level",
        "method",
        "code",
        "error_code",
        "item_id",
        "job_id",
        "chunk_id",
        "stage",
        "status",
        "source_type",
        "count",
        "attempt",
        "duration_ms",
        "bytes",
        "model",
        "table",
        "version",
        "reason",
        "pid",
    }
)

_lock = threading.Lock()
_stream: TextIO = sys.stderr
_file: TextIO | None = None
_min_level = 20
_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


def configure(log_dir: Path | None, level: str = "info") -> None:
    global _file, _min_level
    _min_level = _LEVELS.get(level, 20)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        _file = open(log_dir / "engine.log", "a", encoding="utf-8")  # noqa: SIM115


def _emit(level: str, event: str, fields: dict[str, Any]) -> None:
    if _LEVELS[level] < _min_level:
        return
    record: dict[str, Any] = {"ts": utc_now(), "level": level, "event": event}
    for key, value in fields.items():
        if key in ALLOWED_FIELDS and isinstance(value, str | int | float | bool | type(None)):
            record[key] = value
    line = json.dumps(record, separators=(",", ":"))
    with _lock:
        print(line, file=_stream, flush=True)
        if _file is not None:
            _file.write(line + "\n")
            _file.flush()


def debug(event: str, **fields: Any) -> None:
    _emit("debug", event, fields)


def info(event: str, **fields: Any) -> None:
    _emit("info", event, fields)


def warning(event: str, **fields: Any) -> None:
    _emit("warning", event, fields)


def error(event: str, **fields: Any) -> None:
    _emit("error", event, fields)
