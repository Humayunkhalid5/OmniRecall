"""A damaged database puts the engine in recovery mode (D-036).

SQLite is the only copy of the text, so nothing rebuilds it. The engine must
not start on a damaged file. It reports the damage and lets the user recover
the readable rows or start over, and either way it then starts normally.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from engine_support import make_engine, wait_status, wait_until

from omnirecall.api import protocol
from omnirecall.recovery import RecoveryEngine
from omnirecall.storage.salvage import check

ENGINE_CMD = [sys.executable, "-m", "omnirecall.api.server"]
PAGE = 4096


def db_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "db" / "omnirecall.sqlite"


def seed(tmp_path: Path, count: int = 120) -> list[str]:
    engine, _ = make_engine(tmp_path)
    try:
        ids = []
        for i in range(count):
            text = f"Entry {i}: notes on the lighthouse restoration, stage {i}. " * 12
            ids.append(engine.import_text({"text": text, "label": f"entry {i}"})["item"]["id"])
        for item_id in ids:
            wait_status(engine, item_id, {"indexed"})
        engine.exclusions_add({"rule_type": "app", "rule_value": "KeePassXC"})
        engine.capture_set_source({"source_type": "clipboard", "enabled": True})
        shot = engine.media_root / "screenshots" / "orphan.png"
        shot.write_bytes(b"\x89PNG orphan")
        engine.db.checkpoint()
        return ids
    finally:
        engine.close()


def damage_chunk_pages(path: Path, pages: int = 3) -> None:
    """Overwrite a few pages holding chunk text in the middle of the file.

    Pages are found by the sentence the seeds repeat, which only chunk rows
    hold (the keyword index stores single terms), so this works on SQLite
    builds without the `dbstat` table, such as the one in Windows Python.
    """
    data = bytearray(path.read_bytes())
    marker = b"notes on the lighthouse restoration"
    if marker not in data:
        marker = b"tide pools and kelp at site"
    leaves = [n for n in range(1, len(data) // PAGE) if marker in data[(n - 1) * PAGE : n * PAGE]]
    assert len(leaves) > pages * 2, "not enough chunk pages to damage"
    middle = leaves[len(leaves) // 2 : len(leaves) // 2 + pages]
    for page in middle:
        data[(page - 1) * PAGE : page * PAGE] = b"\xa5" * PAGE
    path.write_bytes(bytes(data))


def rpc(proc: subprocess.Popen[bytes], id_: int, method: str, params=None) -> dict:
    assert proc.stdin and proc.stdout
    msg = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    proc.stdin.write(json.dumps(msg).encode() + b"\n")
    proc.stdin.flush()
    while True:
        reply = json.loads(proc.stdout.readline())
        if reply.get("id") == id_:
            return reply


def spawn(tmp_path: Path) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        [*ENGINE_CMD, "--data-dir", str(tmp_path / "data")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.stdout
    assert json.loads(proc.stdout.readline())["method"] == "engine.ready"
    return proc


def stop(proc: subprocess.Popen[bytes]) -> None:
    assert proc.stdin
    proc.stdin.close()
    assert proc.wait(timeout=30) == 0


@pytest.mark.timeout(180)
def test_real_engine_starts_in_recovery_mode_and_recovers(tmp_path):
    ids = seed(tmp_path)
    damage_chunk_pages(db_file(tmp_path))
    assert check(db_file(tmp_path)) == "malformed"

    proc = spawn(tmp_path)
    try:
        health = rpc(proc, 1, "health", {"protocol_version": protocol.PROTOCOL_VERSION})
        assert health["result"]["ok"]
        status = rpc(proc, 2, "status")["result"]
        assert status["engine"] == "recovery"
        assert status["database"]["state"] == "damaged"
        assert status["database"]["reason"] == "malformed"
        # Normal calls are not served on a damaged database.
        assert rpc(proc, 3, "search", {"query": "lighthouse"})["error"]["code"] < 0
        assert "error" in rpc(proc, 4, "database.recover", {})  # needs confirm
        report = rpc(proc, 5, "database.recover", {"confirm": True})["result"]
        assert report["copied"]["items"] == len(ids)
        assert report["copied"]["chunks"] > 0
        assert report["media_removed"] == 1
        # The damaged pages held chunks of pasted notes, which cannot be re-read.
        assert report["lost"] > 0 and report["requeued"] == 0
        assert report["complete"] is False
        lost = report["lost"]
        assert rpc(proc, 6, "status")["result"]["database"]["state"] == "restart_needed"
        # One action per start: a reset now is refused until the restart.
        assert "error" in rpc(proc, 7, "database.reset", {"confirm": True})
    finally:
        stop(proc)
    assert check(db_file(tmp_path)) is None
    assert not (tmp_path / "data" / "media" / "screenshots" / "orphan.png").exists()

    # The next start is a normal engine with the recovered rows.
    engine, _ = make_engine(tmp_path)
    try:
        listed = engine.list_items({"limit": 500})["items"]
        assert {i["id"] for i in listed} == set(ids)
        wait_until(lambda: engine.index_verify({})["consistent"], timeout=60)
        hits = engine.search({"query": "lighthouse restoration"})["results"]
        assert hits
        # Capture is off until the user turns it back on; exclusions survived.
        assert engine.capture_get({})["sources"]["clipboard"]["enabled"] is False
        rules = engine.exclusions_list({})["exclusions"]
        assert [r["rule_value"] for r in rules] == ["KeePassXC"]
        # Items whose chunks were on the damaged pages are reprocessed or reported,
        # never shown as indexed with no text.
        failed = [i for i in listed if i["status"] == "failed"]
        assert len(failed) == lost
        assert {i["error_code"] for i in failed} == {"recovery_lost_text"}
        for item in listed:
            detail = engine.get_item({"item_id": item["id"]})
            assert detail["item"]["status"] != "indexed" or detail["chunk_count"] > 0
    finally:
        engine.close()


@pytest.mark.timeout(120)
def test_unreadable_file_can_only_be_reset(tmp_path):
    seed(tmp_path, count=3)
    db_file(tmp_path).write_bytes(b"this is not a database" * 400)
    (tmp_path / "data" / "db" / "omnirecall.sqlite-wal").unlink(missing_ok=True)
    assert check(db_file(tmp_path)) == "not_a_database"
    recovery = RecoveryEngine(tmp_path / "data", "not_a_database")
    from omnirecall.errors import EngineError

    with pytest.raises(EngineError) as info:
        recovery.recover({"confirm": True})
    assert info.value.code == "recovery_failed"
    assert not db_file(tmp_path).with_name("omnirecall.sqlite.recovering").exists()

    result = recovery.reset({"confirm": True})
    assert result["media_removed"] >= 1
    assert not db_file(tmp_path).exists()
    assert not (tmp_path / "data" / "vectors").exists()
    assert recovery.status({})["database"]["state"] == "restart_needed"
    with pytest.raises(EngineError):
        recovery.recover({"confirm": True})

    engine, _ = make_engine(tmp_path)
    try:
        assert engine.list_items({})["items"] == []
        new = engine.import_text({"text": "fresh start after a reset"})["item"]["id"]
        assert wait_status(engine, new, {"indexed"}) == "indexed"
    finally:
        engine.close()


def test_a_healthy_database_passes_the_startup_check(tmp_path):
    seed(tmp_path, count=2)
    assert check(db_file(tmp_path)) is None
    assert check(tmp_path / "missing.sqlite") is None


@pytest.mark.timeout(180)
def test_imported_files_that_lost_text_are_read_again(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(120):
        (docs / f"note{i}.txt").write_text(f"Field log {i}: tide pools and kelp at site {i}. " * 12)
    engine, _ = make_engine(tmp_path)
    try:
        ids = engine.import_paths({"paths": [str(docs)]})["item_ids"]
        for item_id in ids:
            wait_status(engine, item_id, {"indexed"})
        engine.db.checkpoint()
    finally:
        engine.close()
    damage_chunk_pages(db_file(tmp_path))

    report = RecoveryEngine(tmp_path / "data", "malformed").recover({"confirm": True})
    assert report["requeued"] > 0 and report["lost"] == 0

    engine, _ = make_engine(tmp_path)
    try:
        for item_id in ids:
            assert wait_status(engine, item_id, {"indexed", "failed"}, timeout=60) == "indexed"
            assert engine.get_item({"item_id": item_id})["chunk_count"] > 0
        wait_until(lambda: engine.index_verify({})["consistent"], timeout=60)
    finally:
        engine.close()


@pytest.mark.timeout(120)
def test_data_from_a_newer_version_is_reported_and_never_changed(tmp_path):
    seed(tmp_path, count=2)
    conn = sqlite3.connect(db_file(tmp_path))
    conn.execute("INSERT INTO schema_migrations VALUES (999, '2030-01-01T00:00:00Z')")
    conn.commit()
    conn.close()
    before = db_file(tmp_path).read_bytes()

    proc = spawn(tmp_path)
    try:
        status = rpc(proc, 1, "status")["result"]
        assert status["engine"] == "recovery"
        assert status["database"]["reason"] == "schema_too_new"
        for id_, method in enumerate(("database.recover", "database.reset"), start=2):
            reply = rpc(proc, id_, method, {"confirm": True})
            assert reply["error"]["data"]["code"] == "schema_too_new"
    finally:
        stop(proc)
    assert db_file(tmp_path).read_bytes() == before
    assert (tmp_path / "data" / "vectors").is_dir()


def test_errors_that_are_not_damage_do_not_offer_recovery(tmp_path, monkeypatch):
    """A locked file or a full disk must never lead to an offer to replace the database."""
    from omnirecall import app
    from omnirecall.api import server

    seed(tmp_path, count=1)

    def locked(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(app, "Engine", locked)
    started = []
    monkeypatch.setattr("omnirecall.recovery.RecoveryEngine.__init__", lambda *a: started.append(a))
    with pytest.raises(sqlite3.OperationalError):
        server.main(["--data-dir", str(tmp_path / "data")])
    assert started == []
    assert check(db_file(tmp_path)) is None


def test_a_locked_database_is_not_reported_as_damaged(tmp_path):
    path = tmp_path / "locked.sqlite"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE t (a)")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE")
    conn.execute("BEGIN EXCLUSIVE")
    conn.execute("INSERT INTO t VALUES (1)")
    try:
        assert check(path) is None
    finally:
        conn.execute("ROLLBACK")
        conn.close()
