"""Problem report: a content-free summary the user reads, then copies or saves.

Nothing here is sent anywhere (PRD §7, implementation plan Phase 7). The
report holds versions, the OS, counts, on/off states, and error codes. It
never holds captured text, queries, file names or paths, app names, or
exclusion rules, and recent log records are filtered again to a narrower
set of fields than the log itself allows, so item IDs are left out too.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from omnirecall import __version__
from omnirecall.api import protocol

# Log fields copied into a report: codes, counts, and durations only.
REPORT_LOG_FIELDS = (
    "ts",
    "level",
    "event",
    "method",
    "code",
    "error_code",
    "stage",
    "status",
    "source_type",
    "count",
    "attempt",
    "duration_ms",
    "model",
    "version",
    "reason",
)
LOG_TAIL_BYTES = 512 * 1024
LOG_RECORDS = 40


def recent_problems(log_file: Path, limit: int = LOG_RECORDS) -> list[dict[str, Any]]:
    """The last warning and error records from the engine log, re-filtered."""
    try:
        with open(log_file, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if len(tail) > 1 and size > LOG_TAIL_BYTES:
        tail = tail[1:]  # the first line may be cut in half
    records = []
    for line in tail:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("level") not in ("warning", "error"):
            continue
        records.append(
            {
                key: record[key]
                for key in REPORT_LOG_FIELDS
                if key in record and isinstance(record[key], str | int | float | bool)
            }
        )
    return records[-limit:]


def system_summary() -> dict[str, Any]:
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "packaged": bool(getattr(sys, "frozen", False)),
    }


def build_report(
    status: dict[str, Any],
    capture: dict[str, Any],
    failures: dict[str, int],
    exclusion_count: int,
    log_file: Path,
) -> dict[str, Any]:
    """Assemble the report from the engine's own status, with every path removed."""
    storage = {k: v for k, v in status.get("storage", {}).items() if k != "data_dir"}
    index = {k: v for k, v in status.get("index", {}).items() if k != "table"}
    return {
        "engine_version": __version__,
        "protocol_version": protocol.PROTOCOL_VERSION,
        "system": system_summary(),
        "items": status.get("items", {}),
        "failures_by_code": dict(sorted(failures.items())),
        "jobs": status.get("jobs", {}),
        "queue": status.get("queue", {}),
        "search_model": status.get("model", {}),
        "speech_model": status.get("transcription", {}),
        "index": index,
        "storage_bytes": storage,
        "capture": {
            "paused": capture.get("paused"),
            "sources": {
                name: {"enabled": s.get("enabled"), "active": s.get("active")}
                for name, s in capture.get("sources", {}).items()
            },
            "ocr_available": capture.get("ocr", {}).get("available"),
            "ocr_version": capture.get("ocr", {}).get("version"),
        },
        "exclusions": exclusion_count,
        "recent_problems": recent_problems(log_file),
    }


def count_failures(rows: list[tuple[str | None, str | None]]) -> dict[str, int]:
    """Failed items by source type and error code, e.g. ``image/ocr_timeout``."""
    return dict(Counter(f"{source or 'unknown'}/{code or 'unknown'}" for source, code in rows))


def format_report(report: dict[str, Any]) -> str:
    """Plain text for a GitHub issue: a short header, then the JSON as it is."""
    system = report["system"]
    lines = [
        "OmniRecall problem report",
        f"Version {report['engine_version']} (protocol {report['protocol_version']}), "
        f"{system['os']} {system['os_release']} {system['machine']}",
        "",
        "This report contains versions, counts, on/off states, and error codes only.",
        "It does not contain captured text, searches, file names, app names, or exclusions.",
        "",
        "```json",
        json.dumps(report, indent=2, sort_keys=False),
        "```",
    ]
    return "\n".join(lines) + "\n"
