"""Privacy suite (Phase 3 exit gate): nothing is captured while disabled or paused,
filtered copies leave no trace, and logs never carry captured content."""

from __future__ import annotations

import io

import pytest
from engine_support import make_engine, wait_status, wait_until

from omnirecall import logs
from omnirecall.errors import EngineError, SourceDisabledError, ValidationError

MARKER = "zebra-quokka-7719 meeting notes about the lighthouse budget"


@pytest.fixture
def engine(tmp_path):
    eng, recorder = make_engine(tmp_path)
    eng.recorder = recorder
    yield eng
    eng.close()


def item_count(engine) -> int:
    return int(engine.db.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])


def copy(engine, text, app="Notes", app_known=True):
    return engine.capture_clipboard({"text": text, "app": app, "app_known": app_known})


def enable(engine):
    return engine.capture_set_source({"source_type": "clipboard", "enabled": True})


def test_every_source_starts_off(engine):
    state = engine.capture_get({})
    assert state["paused"] is False and state["capturing"] is False
    for source in state["sources"].values():
        assert source == {"enabled": False, "paused": False, "active": False}


def test_disabled_source_records_nothing(engine):
    with pytest.raises(SourceDisabledError):
        copy(engine, MARKER)
    assert item_count(engine) == 0
    assert not list((engine.media_root / "incoming").iterdir())


def test_global_pause_and_source_pause_record_nothing(engine):
    enable(engine)
    engine.capture_pause({"paused": True})
    assert engine.capture_get({})["capturing"] is False
    with pytest.raises(SourceDisabledError):
        copy(engine, MARKER)
    engine.capture_pause({"paused": False})
    engine.capture_set_source({"source_type": "clipboard", "paused": True})
    with pytest.raises(SourceDisabledError):
        copy(engine, MARKER)
    assert item_count(engine) == 0
    engine.capture_set_source({"source_type": "clipboard", "paused": False})
    assert copy(engine, MARKER)["outcome"] == "captured"
    assert item_count(engine) == 1


def test_pause_survives_restart(tmp_path):
    eng, _ = make_engine(tmp_path)
    enable(eng)
    eng.capture_pause({"paused": True})
    eng.close()
    again, _ = make_engine(tmp_path)
    try:
        state = again.capture_get({})
        assert state["paused"] is True and state["sources"]["clipboard"]["enabled"] is True
        with pytest.raises(SourceDisabledError):
            copy(again, MARKER)
    finally:
        again.close()


def test_state_changes_are_announced_to_the_shell(engine):
    enable(engine)
    engine.capture_pause({"paused": True})
    states = [p for m, p in engine.recorder.events if m == "capture.state"]
    assert states[0]["capturing"] is True
    assert states[-1]["capturing"] is False and states[-1]["paused"] is True


def test_capture_pause_cannot_bypass_notification(engine):
    with pytest.raises(ValidationError):
        engine.settings_update({"changes": {"capture_paused": True}})


def test_disabling_clears_source_pause(engine):
    enable(engine)
    engine.capture_set_source({"source_type": "clipboard", "paused": True})
    state = engine.capture_set_source({"source_type": "clipboard", "enabled": False})
    assert state["sources"]["clipboard"] == {"enabled": False, "paused": False, "active": False}


def test_captured_copy_is_indexed_and_searchable(engine):
    enable(engine)
    out = copy(engine, MARKER, app="Firefox")
    assert out["outcome"] == "captured"
    assert wait_status(engine, out["item_id"], {"indexed"}) == "indexed"
    item = engine.repo.get_item(out["item_id"])
    assert item.source_type == "clipboard" and item.metadata["app"] == "Firefox"
    hits = engine.search({"query": "lighthouse budget", "filters": {"source_types": ["clipboard"]}})
    assert hits["results"][0]["item_id"] == out["item_id"]


def test_duplicate_copy_is_not_stored_twice(engine):
    enable(engine)
    first = copy(engine, MARKER)
    second = copy(engine, MARKER)
    assert second == {"outcome": "duplicate", "item_id": first["item_id"]}
    assert item_count(engine) == 1


@pytest.mark.parametrize(
    ("text", "outcome"),
    [
        ("x" * (100 * 1024 + 1), "too_large"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA\n", "sensitive"),
        ("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE", "sensitive"),
        ("card 4111 1111 1111 1111 exp 12/29", "sensitive"),
        ("Tr0ub4dor&3xYz!", "sensitive"),
        ("   \n\t ", "empty"),
    ],
    # Short IDs: the 100 KB text as an ID overflows Windows' environment limit.
    ids=["too_large", "private_key", "aws_key", "card", "password", "empty"],
)
def test_filtered_copies_leave_no_trace(engine, text, outcome):
    enable(engine)
    assert copy(engine, text) == {"outcome": outcome}
    assert item_count(engine) == 0
    assert not list((engine.media_root / "incoming").iterdir())
    assert engine.capture_get({})["session"]["clipboard"] == {outcome: 1}


def test_secret_filter_can_be_turned_off(engine):
    enable(engine)
    engine.settings_update({"changes": {"clipboard_detect_secrets": False}})
    assert copy(engine, "Tr0ub4dor&3xYz!")["outcome"] == "captured"


def test_app_exclusion_is_case_insensitive_and_ignores_suffix(engine):
    enable(engine)
    engine.exclusions_add({"rule_type": "app", "rule_value": "1Password"})
    assert copy(engine, MARKER, app="1password.exe") == {"outcome": "excluded_app"}
    assert copy(engine, MARKER, app="1Password.app") == {"outcome": "excluded_app"}
    assert item_count(engine) == 0
    assert copy(engine, MARKER, app="Notes")["outcome"] == "captured"


def test_app_exclusion_fails_closed_when_app_is_unknown(engine):
    enable(engine)
    assert copy(engine, MARKER, app=None, app_known=False)["outcome"] == "captured"
    engine.exclusions_add({"rule_type": "app", "rule_value": "KeePassXC"})
    assert copy(engine, "another note", app=None, app_known=False) == {"outcome": "app_unknown"}


def test_text_exclusion_is_literal_and_case_insensitive(engine):
    enable(engine)
    engine.exclusions_add({"rule_type": "pattern", "rule_value": "Project Falcon"})
    assert copy(engine, "notes on PROJECT FALCON launch") == {"outcome": "excluded_pattern"}
    # Regex syntax is matched literally, never evaluated.
    engine.exclusions_add({"rule_type": "pattern", "rule_value": "(a+)+$"})
    assert copy(engine, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!")["outcome"] == "captured"


def test_disabled_exclusion_stops_applying(engine):
    enable(engine)
    rule = engine.exclusions_add({"rule_type": "pattern", "rule_value": "lighthouse"})
    assert copy(engine, MARKER) == {"outcome": "excluded_pattern"}
    engine.exclusions_update({"id": rule["id"], "enabled": False})
    assert copy(engine, MARKER)["outcome"] == "captured"
    engine.exclusions_remove({"id": rule["id"]})
    assert engine.exclusions_list({})["exclusions"][1:] == []


def test_exclusion_validation(engine, tmp_path):
    with pytest.raises(ValidationError):
        engine.exclusions_add_path({"rule_type": "path", "rule_value": "relative/dir"})
    with pytest.raises(Exception):  # noqa: B017 - folders only through the shell dialog
        engine.exclusions_add({"rule_type": "path", "rule_value": str(tmp_path)})
    with pytest.raises(ValidationError):
        engine.exclusions_add({"rule_type": "pattern", "rule_value": "ab"})
    with pytest.raises(Exception):  # noqa: B017 - pydantic rejects the unknown type
        engine.exclusions_add({"rule_type": "regex", "rule_value": ".*"})
    first = engine.exclusions_add({"rule_type": "app", "rule_value": "Signal"})
    again = engine.exclusions_add({"rule_type": "app", "rule_value": " signal "})
    assert first["id"] == again["id"]


def test_folder_exclusion_applies_to_imports(engine, tmp_path):
    root = tmp_path / "docs"
    (root / "private").mkdir(parents=True)
    (root / "public.txt").write_text("public quarterly plan")
    (root / "private" / "diary.txt").write_text("private diary entry")
    engine.exclusions_add_path({"rule_type": "path", "rule_value": str(root / "private")})
    summary = engine.import_paths({"paths": [str(root)]})
    assert summary["queued"] == 1
    assert {"name": "private", "code": "excluded_path"} in summary["rejected"]
    direct = engine.import_paths({"paths": [str(root / "private" / "diary.txt")]})
    assert direct["queued"] == 0 and direct["rejected"][0]["code"] == "excluded_path"


def test_app_data_folder_is_never_imported(engine):
    summary = engine.import_paths({"paths": [str(engine.data_dir)]})
    assert summary["queued"] == 0
    assert summary["rejected"][0]["code"] == "excluded_path"


def test_logs_never_contain_captured_text_or_queries(engine, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(logs, "_stream", stream)
    monkeypatch.setattr(logs, "_min_level", 0)  # the most verbose level must be clean too
    enable(engine)
    engine.exclusions_add({"rule_type": "pattern", "rule_value": "secret-project-omega"})
    out = copy(engine, MARKER)
    copy(engine, "secret-project-omega roadmap")
    copy(engine, "Tr0ub4dor&3xYz!")
    wait_status(engine, out["item_id"], {"indexed"})
    engine.search({"query": "zebra quokka lighthouse"})
    pasted = engine.import_text({"text": "pasted walrus-harbor-5521 text"})["item"]["id"]
    wait_status(engine, pasted, {"indexed"})
    engine.delete_item({"item_id": out["item_id"]})
    wait_status(engine, out["item_id"], {"deleted"})
    log = stream.getvalue()
    for needle in ("zebra", "quokka", "lighthouse", "omega", "Tr0ub4dor", "walrus", "Notes"):
        assert needle not in log, needle
    assert "clipboard_capture" in log


def test_clipboard_item_deletion_is_physical(engine):
    enable(engine)
    out = copy(engine, MARKER)
    wait_status(engine, out["item_id"], {"indexed"})
    engine.delete_item({"item_id": out["item_id"]})
    wait_status(engine, out["item_id"], {"deleted"})
    engine.db.checkpoint()
    for path in engine.data_dir.rglob("*"):
        if path.is_file() and path.suffix != ".log":
            assert b"zebra-quokka-7719" not in path.read_bytes(), path


def test_shell_only_methods_reject_bad_input(engine):
    enable(engine)
    with pytest.raises(Exception):  # noqa: B017 - pydantic validation
        engine.capture_clipboard({"text": ""})
    with pytest.raises(Exception):  # noqa: B017
        engine.capture_set_source({"source_type": "microphone", "enabled": True})


def test_capture_while_queue_full_is_reported(engine):
    enable(engine)
    engine.runner.stop()
    engine.settings_update({"changes": {"queue_capacity": 10}})
    for i in range(10):
        copy(engine, f"note number {i} about the harbor")
    with pytest.raises(EngineError) as info:
        copy(engine, "one more note about the harbor")
    assert info.value.code == "queue_full"
    engine.runner.start()
    wait_until(lambda: engine.status({})["queue"]["active"] == 0)
