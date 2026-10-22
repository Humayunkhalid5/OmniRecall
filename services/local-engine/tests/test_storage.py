"""Schema, migrations, state machine, repository, and FTS."""

from __future__ import annotations

import sqlite3

import pytest
from support import make_stores, new_text_item, simple_chunks

from omnirecall.errors import EngineError
from omnirecall.ids import chunk_id, parse_utc, utc_now, uuid7
from omnirecall.storage.db import LATEST_SCHEMA_VERSION, Database
from omnirecall.storage.repository import NewItem
from omnirecall.storage.states import (
    TRANSITIONS,
    InvalidTransitionError,
    ItemStatus,
    check_transition,
)


def test_migrations_apply_once(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    assert db.migrate() == list(range(1, LATEST_SCHEMA_VERSION + 1))
    assert db.migrate() == []
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name in (
        "items",
        "chunks",
        "jobs",
        "vector_outbox",
        "tombstones",
        "sources",
        "exclusions",
        "settings",
        "schema_migrations",
        "chunks_fts",
    ):
        assert name in tables
    assert db.conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    assert db.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_newer_schema_is_refused(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.migrate()
    db.conn.execute("INSERT INTO schema_migrations VALUES (999, ?)", (utc_now(),))
    with pytest.raises(EngineError) as info:
        db.migrate()
    assert info.value.code == "schema_too_new"


def test_ids_and_timestamps():
    a, b = uuid7(), uuid7()
    assert a != b and a < b and a[14] == "7"
    assert chunk_id("i", 0, "v1") == chunk_id("i", 0, "v1") != chunk_id("i", 1, "v1")
    stamp = utc_now()
    assert stamp.endswith("Z") and len(stamp) == 24
    assert parse_utc(stamp).tzinfo is not None


@pytest.mark.parametrize("current", list(ItemStatus))
def test_transition_table(current):
    for target in ItemStatus:
        if target in TRANSITIONS[current]:
            check_transition(current, target)
        else:
            with pytest.raises(InvalidTransitionError):
                check_transition(current, target)


def test_duplicate_content_is_not_reingested(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    first = new_text_item(repo, "hello world")
    again = new_text_item(repo, "hello world")
    assert first == again
    assert repo.status_counts() == {"queued": 1}
    assert repo.job_counts() == {"pending": 1}


def test_skipped_item_keeps_only_hash_and_reason(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    item, created = repo.create_skipped_item(
        NewItem(
            source_type="clipboard",
            captured_at=utc_now(),
            content_hash="a" * 64,
            source_label="secret label",
        ),
        reason="excluded_pattern",
    )
    assert created and item.status == "skipped" and item.skip_reason == "excluded_pattern"
    assert item.source_label is None and item.source_uri is None
    assert repo.job_counts() == {}


def test_invalid_status_rejected_by_schema(tmp_path):
    db, repo, _, _ = make_stores(tmp_path)
    item_id = new_text_item(repo, "x")
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("UPDATE items SET status = 'bogus' WHERE id = ?", (item_id,))


def test_replace_chunks_is_idempotent_and_fts_tracks(tmp_path):
    _, repo, vectors, _ = make_stores(tmp_path)
    item_id = new_text_item(repo, "doc")
    text = "The Calvin cycle fixes carbon dioxide in the stroma of chloroplasts. " * 3
    chunks = simple_chunks(item_id, text)
    for _ in range(3):  # retries
        repo.replace_chunks(item_id, chunks, vectors.table_name)
    assert repo.chunk_count() == len(chunks)
    assert len({c.id for c in repo.chunks_for_item(item_id)}) == len(chunks)
    repo.transition(item_id, ItemStatus.PROCESSING)
    repo.transition(item_id, ItemStatus.INDEXED)
    hits = repo.keyword_search('"calvin"', 10)
    assert hits and all(h[1] == item_id for h in hits)
    # Shrinking the chunk set removes stale rows from FTS too.
    repo.replace_chunks(item_id, chunks[:1], vectors.table_name)
    assert repo.chunk_count() == 1
    assert repo.fts_integrity_ok()


def test_keyword_search_hides_non_indexed(tmp_path):
    _, repo, vectors, _ = make_stores(tmp_path)
    item_id = new_text_item(repo, "doc")
    repo.replace_chunks(item_id, simple_chunks(item_id, "thylakoid membrane"), vectors.table_name)
    assert repo.keyword_search("thylakoid", 10) == []


def test_exclusions_crud(tmp_path):
    _, repo, _, _ = make_stores(tmp_path)
    eid = repo.create_exclusion("app", "KeePassXC")
    repo.update_exclusion(eid, None, False)
    assert repo.list_exclusions()[0]["enabled"] is False
    repo.delete_exclusion(eid)
    assert repo.list_exclusions() == []
    with pytest.raises(EngineError):
        repo.delete_exclusion(eid)
