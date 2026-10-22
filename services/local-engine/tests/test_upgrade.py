"""Data left by every released schema opens in the current engine (Phase 6).

Each fixture in tests/fixtures/upgrade is a data folder written by that
release's own code (see make_fixture.py there): items of every source, a
deleted item, exclusions, changed settings, the vector table, and a stored
screenshot. The current engine must migrate it in place and lose nothing.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from engine_support import make_engine, wait_status, wait_until

from omnirecall.storage import db as db_module
from omnirecall.storage.db import LATEST_SCHEMA_VERSION, Database

FIXTURES = Path(__file__).parent / "fixtures" / "upgrade"
ARCHIVES = sorted(FIXTURES.glob("*-schema*.zip"))


def unpack(archive: Path, tmp_path: Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        z.extractall(tmp_path)
        return json.loads(z.read("manifest.json"))


def schema_of(tmp_path: Path) -> int:
    conn = sqlite3.connect(tmp_path / "data" / "db" / "omnirecall.sqlite")
    try:
        return conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        conn.close()


def test_every_earlier_schema_has_a_fixture():
    """A schema change must ship with a fixture from the release before it."""
    covered = set()
    for archive in ARCHIVES:
        with zipfile.ZipFile(archive) as z:
            covered.add(json.loads(z.read("manifest.json"))["schema"])
    assert set(range(1, LATEST_SCHEMA_VERSION)) <= covered


@pytest.mark.timeout(120)
@pytest.mark.parametrize("archive", ARCHIVES, ids=[a.stem for a in ARCHIVES])
def test_released_data_opens_with_nothing_lost(tmp_path, archive):
    manifest = unpack(archive, tmp_path)
    assert schema_of(tmp_path) == manifest["schema"]
    media = tmp_path / "data" / "media" / manifest["media_uri"]
    assert media.is_file()

    engine, _ = make_engine(tmp_path)
    try:
        assert schema_of(tmp_path) == LATEST_SCHEMA_VERSION
        assert engine.startup_reconciled.wait(30)
        wait_until(lambda: engine.index_verify({})["consistent"], timeout=60)
        report = engine.index_verify({})
        assert report["vector_rows"] == report["sqlite_chunks"] == len(manifest["items"])

        listed = {i["id"]: i for i in engine.list_items({"limit": 100})["items"]}
        assert set(listed) == set(manifest["items"])
        for item_id, expected in manifest["items"].items():
            assert listed[item_id]["source_type"] == expected["source_type"]
            assert listed[item_id]["status"] == "indexed"
            detail = engine.get_item({"item_id": item_id})
            assert detail["chunk_count"] > 0
            found = engine.search({"query": expected["find"]})
            assert found["semantic_available"]
            assert found["results"][0]["item_id"] == item_id

        # The deleted item stays deleted: no row returns and its text is not searchable.
        assert engine.repo.get_item(manifest["deleted"]).status == "deleted"
        hits = engine.search({"query": manifest["deleted_text"]})["results"]
        assert manifest["deleted"] not in {h["item_id"] for h in hits}
        assert engine.repo.keyword_search("locker", 50) == []

        settings = engine.settings_get({})["settings"]
        assert settings["first_run_completed"] is True
        assert settings["results_shown"] == 30
        rules = {r["rule_value"] for r in engine.exclusions_list({})["exclusions"]}
        assert rules == {"KeePassXC", "locker code"}
        sources = engine.capture_get({})["sources"]
        assert sources["clipboard"]["enabled"] is True
        assert sources["screenshot"]["enabled"] is False

        shot = next(k for k, v in manifest["items"].items() if v["source_type"] == "screenshot")
        assert engine.repo.get_item(shot).media_uri == manifest["media_uri"]
        assert media.is_file()

        # New work on the upgraded data uses the new schema.
        new = engine.import_text({"text": "Written after the upgrade: harbour crane schedule"})
        assert wait_status(engine, new["item"]["id"], {"indexed"}) == "indexed"
        assert (
            engine.search({"query": "harbour crane"})["results"][0]["item_id"]
            == (new["item"]["id"])
        )
    finally:
        engine.close()


@pytest.mark.timeout(120)
@pytest.mark.parametrize("archive", ARCHIVES[:1], ids=[a.stem for a in ARCHIVES[:1]])
def test_the_real_engine_starts_normally_on_released_data(tmp_path, archive):
    unpack(archive, tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "omnirecall.api.server", "--data-dir", str(tmp_path / "data")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.stdin and proc.stdout
    try:
        assert json.loads(proc.stdout.readline())["method"] == "engine.ready"
        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"status","params":{}}\n')
        proc.stdin.flush()
        while True:
            reply = json.loads(proc.stdout.readline())
            if reply.get("id") == 1:
                break
        assert reply["result"]["engine"] != "recovery"
        assert reply["result"]["items"]["indexed"] == 4
    finally:
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
    assert schema_of(tmp_path) == LATEST_SCHEMA_VERSION


def test_a_failed_migration_leaves_the_data_as_it_was(tmp_path, monkeypatch):
    """Each migration is one transaction: a failure part-way changes nothing."""
    archive = ARCHIVES[0]
    unpack(archive, tmp_path)
    path = tmp_path / "data" / "db" / "omnirecall.sqlite"
    before = schema_of(tmp_path)
    real = db_module._migrations()
    broken = "ALTER TABLE items ADD COLUMN half_done TEXT;\nSELECT no_such_function();\n"
    monkeypatch.setattr(
        db_module, "_migrations", lambda: [*real, (LATEST_SCHEMA_VERSION + 1, broken)]
    )
    monkeypatch.setattr(db_module, "LATEST_SCHEMA_VERSION", LATEST_SCHEMA_VERSION + 1)

    database = Database(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            database.migrate()
        columns = {r[1] for r in database.conn.execute("PRAGMA table_info(items)")}
        # Earlier migrations committed; the broken one left no trace.
        assert database.schema_version() == LATEST_SCHEMA_VERSION > before
        assert "half_done" not in columns
        assert database.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 5
    finally:
        database.close()
