"""Damaged stores are detected and repaired (PRD §7 reliability, D-035).

The vector table is derived data: when any of its files is damaged or missing,
the engine deletes what is left and re-embeds from SQLite. Search keeps working
on keywords meanwhile and says why. A damaged FTS index is rebuilt from the
chunk rows. A damaged SQLite database cannot be rebuilt from anything, so the
engine reports it instead of starting on it (test_database_damage.py).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from engine_support import make_engine, wait_status, wait_until

TEXTS = [f"Harbour note {i}: the ferry timetable changes for the winter season" for i in range(6)]


def seeded(tmp_path: Path) -> list[str]:
    engine, _ = make_engine(tmp_path)
    try:
        ids = [engine.import_text({"text": t, "label": "note"})["item"]["id"] for t in TEXTS]
        for item_id in ids:
            wait_status(engine, item_id, {"indexed"})
        return ids
    finally:
        engine.close()


def lance_dir(tmp_path: Path) -> Path:
    return next((tmp_path / "data" / "vectors").glob("*.lance"))


def garble_data(table: Path) -> None:
    for f in (table / "data").glob("*"):
        f.write_bytes(b"garbage" * 10)


def garble_manifests(table: Path) -> None:
    for f in (table / "_versions").glob("*"):
        f.write_bytes(b"garbage")


DAMAGE = {
    "data_files": garble_data,
    "manifests": garble_manifests,
    "table_deleted": lambda table: shutil.rmtree(table),
    "data_files_deleted": lambda table: shutil.rmtree(table / "data"),
}


def assert_whole(engine, ids: list[str]) -> None:
    report = engine.index_verify({})
    assert report["consistent"] and report["vector_index_ok"], report
    assert report["vector_rows"] == report["sqlite_chunks"] == len(ids)
    found = engine.search({"query": "ferry timetable winter"})
    assert found["semantic_available"] and found["semantic_unavailable_reason"] is None
    assert {r["item_id"] for r in found["results"]} == set(ids)


@pytest.mark.timeout(120)
@pytest.mark.parametrize("damage", DAMAGE, ids=list(DAMAGE))
def test_damaged_vector_table_is_rebuilt_at_startup(tmp_path, damage):
    ids = seeded(tmp_path)
    DAMAGE[damage](lance_dir(tmp_path))
    engine, _ = make_engine(tmp_path)
    try:
        wait_until(lambda: engine.index_verify({})["consistent"], timeout=60)
        assert_whole(engine, ids)
        # The status call never fails, damaged or not.
        assert engine.status({})["index"]["vectors"] == len(ids)
    finally:
        engine.close()


@pytest.mark.timeout(120)
def test_damage_found_while_running_falls_back_then_repairs(tmp_path):
    ids = seeded(tmp_path)
    engine, events = make_engine(tmp_path)
    try:
        assert engine.startup_reconciled.wait(30)
        wait_until(lambda: engine.index_verify({})["consistent"])
        # Damage the files under the running engine, then drop its open handle
        # (as a later read of a damaged file would).
        garble_data(lance_dir(tmp_path))
        engine.vectors._table = None

        found = engine.search({"query": "ferry timetable winter"})
        # Keyword results still come back, and the UI is told why meaning is off.
        assert {r["item_id"] for r in found["results"]} == set(ids)
        assert found["semantic_available"] is False
        assert found["semantic_unavailable_reason"] == "index_repairing"

        wait_until(lambda: any(m == "index.repaired" for m, _ in events.events), timeout=60)
        assert_whole(engine, ids)
        assert engine.status({})["index"]["repairing"] is False
    finally:
        engine.close()


@pytest.mark.timeout(120)
def test_damaged_table_waits_for_the_model_then_rebuilds(tmp_path):
    from support import HashEmbedder

    ids = seeded(tmp_path)
    garble_data(lance_dir(tmp_path))

    class Later(HashEmbedder):
        installed = False

        def available(self) -> bool:
            return self.installed

    embedder = Later()
    engine, _ = make_engine(tmp_path, embedder=embedder)
    try:
        # No model: nothing to rebuild with, so the table is left alone and
        # reported, and search is keyword-only for the usual reason.
        wait_until(lambda: not engine.index_verify({})["vector_index_ok"])
        assert lance_dir(tmp_path).exists()
        found = engine.search({"query": "ferry timetable winter"})
        assert found["semantic_unavailable_reason"] == "model_missing"
        assert len(found["results"]) == len(ids)

        embedder.installed = True
        engine._requeue_model_missing()  # what models.download / install_file call
        wait_until(lambda: engine.index_verify({})["consistent"], timeout=60)
        assert_whole(engine, ids)
    finally:
        engine.close()


@pytest.mark.timeout(120)
def test_damaged_fts_index_is_rebuilt_at_startup(tmp_path):
    import sqlite3

    ids = seeded(tmp_path)
    conn = sqlite3.connect(tmp_path / "data" / "db" / "omnirecall.sqlite")
    conn.execute("DELETE FROM chunks_fts_data WHERE id > 1")  # keep the structure record
    conn.commit()
    conn.close()

    engine, _ = make_engine(tmp_path)
    try:
        wait_until(lambda: engine.index_verify({})["consistent"], timeout=60)
        hits = engine.repo.keyword_search("timetable", 50)
        assert {h[1] for h in hits} == set(ids)
    finally:
        engine.close()
