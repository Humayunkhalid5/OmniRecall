"""Crash recovery: kill a real engine at each cross-store step, restart, and check.

Each case runs the engine in a child process that ends with os._exit() at one
point (see crash_child.py), so nothing is flushed, rolled back, or closed. A new
engine then opens the same data folder. It must finish or redo the interrupted
work, with no lost item, no duplicate chunk or vector, a consistent index, and,
for deletions, no recoverable bytes (bugs.md release checklist, OR-004, OR-017).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from engine_support import make_engine, wait_status, wait_until

CHILD = Path(__file__).with_name("crash_child.py")
CRASHED = 86
MARKER = "zq-crash-marker-41c7d2"
TEXTS = [
    f"Rotate the archive signing keys before {MARKER} the November audit window",
    "The ferry to the island leaves at seven from the north pier on weekdays",
    "Sourdough starter needs feeding twice a day while the kitchen is warm",
]

INDEX_FAULTS = [
    # The item row exists; no chunks yet.
    ("omnirecall.storage.repository:Repository.replace_chunks", "before"),
    # Chunks, FTS rows, and outbox committed; no vectors.
    ("omnirecall.storage.repository:Repository.replace_chunks", "after"),
    # Vectors written to LanceDB; the outbox still lists them.
    ("omnirecall.storage.vectors:VectorStore.upsert", "after"),
    # Every store written; the item is still `processing`.
    ("omnirecall.ingestion.pipeline:Pipeline.finalize", "before"),
]

DELETE_FAULTS = [
    # Tombstone written; nothing removed yet.
    ("omnirecall.storage.vectors:VectorStore.delete_items", "before"),
    # Vectors gone; SQLite rows and FTS entries remain.
    ("omnirecall.storage.vectors:VectorStore.delete_items", "after"),
    # Rows removed logically; freed pages and old LanceDB versions still on disk.
    ("omnirecall.storage.repository:Repository.optimize_fts", "before"),
    ("omnirecall.storage.vectors:VectorStore.compact_and_cleanup", "before"),
    # Physically clean; the item is not yet marked deleted.
    ("omnirecall.storage.db:Database.checkpoint", "after"),
]


def run_child(data_dir: Path, scenario: str, fault=None, **env) -> int:
    args = [sys.executable, str(CHILD), str(data_dir), scenario, *(fault or ())]
    done = subprocess.run(
        args,
        env=os.environ | {"CRASH_TEXTS": json.dumps(TEXTS)} | env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=120,
    )
    assert b"Traceback" not in done.stderr, done.stderr.decode()[-2000:]
    return done.returncode


def raw_hits(root: Path, needle: bytes) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and needle in p.read_bytes()]


def assert_healthy(engine, expected_items: int) -> None:
    report = engine.index_verify({})
    assert report["consistent"], report
    chunks = engine.db.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert engine.writer.vectors.count() == chunks
    unfinished = engine.db.conn.execute(
        "SELECT COUNT(*) FROM vector_outbox WHERE status != 'done'"
    ).fetchone()[0]
    assert unfinished == 0
    live = engine.db.conn.execute(
        "SELECT COUNT(*) FROM items WHERE status NOT IN ('deleted')"
    ).fetchone()[0]
    assert live == expected_items


@pytest.mark.timeout(180)
@pytest.mark.parametrize("fault", INDEX_FAULTS, ids=lambda f: f"{f[0].split('.')[-1]}-{f[1]}")
def test_crash_while_indexing_is_recovered(tmp_path, fault):
    data = tmp_path / "data"
    assert run_child(data, "index", fault) == CRASHED

    engine, _ = make_engine(tmp_path)
    try:
        ids = [r[0] for r in engine.db.conn.execute("SELECT id FROM items ORDER BY rowid")]
        assert ids, "the crash came before the first item was stored"
        for item_id in ids:
            assert wait_status(engine, item_id, {"indexed", "failed"}, timeout=60) == "indexed"
        # Importing the same texts again finds the existing items: no duplicates.
        for text in TEXTS:
            again = engine.import_text({"text": text, "label": "note"})
            wait_status(engine, again["item"]["id"], {"indexed"}, timeout=60)
        assert_healthy(engine, len(TEXTS))
        hits = engine.search({"query": "archive signing keys audit"})["results"]
        assert [h["source_label"] for h in hits].count("note") >= 1
        assert len({h["item_id"] for h in hits}) == len(hits)
        assert (
            hits[0]["snippet"]
            and MARKER in engine.get_item({"item_id": hits[0]["item_id"]})["chunks"][0]["text"]
        )
    finally:
        engine.close()


def seed(tmp_path: Path) -> tuple[str, list[str]]:
    """Index the texts without faults; return the marker item and its chunk hashes."""
    assert run_child(tmp_path / "data", "index") == 0
    engine, _ = make_engine(tmp_path)
    try:
        rows = engine.db.conn.execute(
            "SELECT item_id, text_hash FROM chunks WHERE text LIKE ?", (f"%{MARKER}%",)
        ).fetchall()
        return rows[0][0], [r[1] for r in rows]
    finally:
        engine.close()


@pytest.mark.timeout(180)
@pytest.mark.parametrize("fault", DELETE_FAULTS, ids=lambda f: f"{f[0].split('.')[-1]}-{f[1]}")
def test_crash_while_deleting_is_finished_and_physical(tmp_path, fault):
    victim, hashes = seed(tmp_path)
    data = tmp_path / "data"
    # Sanity: before deleting, the text is in SQLite and its hashes are in LanceDB.
    assert raw_hits(data / "db", MARKER.encode())
    assert all(raw_hits(data / "vectors", h.encode()) for h in hashes)
    assert run_child(data, "delete", fault, CRASH_VICTIM=victim) == CRASHED

    engine, _ = make_engine(tmp_path)
    try:
        # Hidden from search at once, even before cleanup resumes.
        assert all(
            h["item_id"] != victim
            for h in engine.search({"query": "archive signing keys audit"})["results"]
        )
        assert wait_status(engine, victim, {"deleted"}, timeout=60) == "deleted"
        assert_healthy(engine, len(TEXTS) - 1)
    finally:
        engine.close()
    # No content-derived bytes anywhere: text, or the chunk hashes LanceDB stores.
    # (The random item ID may remain: the `deleted` row keeps it by design.)
    assert raw_hits(data, MARKER.encode()) == []
    for text_hash in hashes:
        assert raw_hits(data, text_hash.encode()) == []


@pytest.mark.timeout(180)
def test_repeated_crashes_still_converge(tmp_path):
    """Crash at a different step on each restart; the index still ends up whole."""
    data = tmp_path / "data"
    for fault in INDEX_FAULTS:
        code = run_child(data, "index", fault)
        assert code in (CRASHED, 3), code  # 3: already indexed, fault not reached
    engine, _ = make_engine(tmp_path)
    try:
        wait_until(
            lambda: (
                engine.db.conn.execute(
                    "SELECT COUNT(*) FROM items WHERE status = 'indexed'"
                ).fetchone()[0]
                == len(TEXTS)
            ),
            timeout=60,
        )
        assert_healthy(engine, len(TEXTS))
    finally:
        engine.close()
