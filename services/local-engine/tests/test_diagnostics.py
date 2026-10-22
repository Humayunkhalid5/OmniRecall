"""Problem report (Phase 7): useful counts and codes, and none of the user's content."""

from __future__ import annotations

import json

import pytest
from engine_support import make_engine, wait_status

from omnirecall import diagnostics, logs

MARKER = "zebra-quokka-7719 notes about the lighthouse budget"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    log_dir = tmp_path / "data" / "logs"
    log_dir.mkdir(parents=True)
    handle = open(log_dir / "engine.log", "a", encoding="utf-8")  # noqa: SIM115
    monkeypatch.setattr(logs, "_file", handle)
    eng, _recorder = make_engine(tmp_path)
    yield eng
    eng.close()
    handle.close()


def test_report_has_counts_and_codes_but_no_content(engine, tmp_path):
    engine.capture_set_source({"source_type": "clipboard", "enabled": True})
    engine.exclusions_add({"rule_type": "app", "rule_value": "KeePassXC"})
    engine.exclusions_add({"rule_type": "pattern", "rule_value": "Project Falcon"})
    copied = engine.capture_clipboard({"text": MARKER, "app": "Notes", "app_known": True})
    wait_status(engine, copied["item_id"], {"indexed"})
    engine.search({"query": "walrus harbor"})
    bad = tmp_path / "private-tax-return.pdf"
    bad.write_bytes(b"not really a pdf")
    imported = engine.import_paths({"paths": [str(bad)]})
    failed_id = imported["item_ids"][0]
    wait_status(engine, failed_id, {"failed"})

    out = engine.diagnostics_report({})
    text = out["text"]
    report = out["report"]

    assert report["items"]["indexed"] == 1
    assert report["items"]["failed"] == 1
    assert list(report["failures_by_code"]) == ["file/malformed_file"]
    assert report["exclusions"] == 2
    assert report["capture"]["sources"]["clipboard"] == {"enabled": True, "active": True}
    assert report["search_model"]["installed"] is True
    assert any(r.get("error_code") == "malformed_file" for r in report["recent_problems"])
    assert json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0]) == report

    for needle in (
        "zebra",
        "quokka",
        "lighthouse",
        "walrus",
        "KeePassXC",
        "Falcon",
        "Notes",
        "private-tax-return",
        str(tmp_path),
        copied["item_id"],
        failed_id,
    ):
        assert needle not in text, needle


def test_recent_problems_reads_only_the_tail_and_keeps_report_fields(tmp_path):
    log = tmp_path / "engine.log"
    filler = json.dumps({"level": "info", "event": "item_indexed", "count": 1})
    lines = [filler] * 20_000
    lines.append(
        json.dumps(
            {
                "ts": "2026-10-22T00:00:00Z",
                "level": "error",
                "event": "job_failed",
                "error_code": "ocr_timeout",
                "item_id": "01a1",
                "unexpected": "anything",
            }
        )
    )
    lines.append("not json")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert log.stat().st_size > diagnostics.LOG_TAIL_BYTES
    assert diagnostics.recent_problems(log) == [
        {
            "ts": "2026-10-22T00:00:00Z",
            "level": "error",
            "event": "job_failed",
            "error_code": "ocr_timeout",
        }
    ]
    assert diagnostics.recent_problems(tmp_path / "missing.log") == []
