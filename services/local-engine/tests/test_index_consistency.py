"""SQLite ↔ LanceDB consistency across retries, crashes, orphans, and rebuilds."""

from __future__ import annotations

import numpy as np
from support import make_stores, new_text_item, simple_chunks

from omnirecall.storage.consistency import ConsistencyService
from omnirecall.storage.index import IndexWriter
from omnirecall.storage.states import ItemStatus

DOCS = {
    "photo": "Photosynthesis converts light energy into chemical energy inside chloroplasts. " * 2,
    "rust": "error E0382 borrow of moved value config consider cloning the value before the move. "
    * 2,
    "meet": "The quarterly review meeting moved to Thursday afternoon with the finance team. " * 2,
}


def index_doc(repo, writer, text):
    item_id = new_text_item(repo, text)
    repo.transition(item_id, ItemStatus.PROCESSING)
    chunks = simple_chunks(item_id, text)
    writer.write_chunks(item_id, chunks, writer.embed_with_cache(chunks, 32))
    repo.transition(item_id, ItemStatus.INDEXED)
    return item_id


def setup(tmp_path):
    db, repo, vectors, embedder = make_stores(tmp_path)
    writer = IndexWriter(repo, vectors, embedder)
    return db, repo, vectors, embedder, writer, ConsistencyService(repo, writer)


def search_ids(vectors, embedder, query, k=100):
    """All rows ranked; sorted by (distance, id) so ties compare deterministically."""
    hits = vectors.search(embedder.embed([query])[0], k)
    return sorted((round(h.distance, 5), h.chunk_id) for h in hits)


def test_write_is_consistent(tmp_path):
    _, repo, _vectors, _, writer, svc = setup(tmp_path)
    for text in DOCS.values():
        index_doc(repo, writer, text)
    report = svc.verify()
    assert report.consistent, report
    assert report.vector_rows == repo.chunk_count()


def test_retry_does_not_duplicate_vectors(tmp_path):
    _, repo, vectors, embedder, writer, svc = setup(tmp_path)
    item_id = index_doc(repo, writer, DOCS["photo"])
    chunks = repo.chunks_for_item(item_id)
    calls = embedder.texts_embedded
    for _ in range(3):
        writer.write_chunks(item_id, chunks, writer.embed_with_cache(chunks, 32))
    assert vectors.count() == len(chunks)
    assert embedder.texts_embedded == calls  # embedding cache hit every time
    assert svc.verify().consistent


def test_crash_between_sqlite_and_lancedb_is_recovered(tmp_path):
    _, repo, vectors, _, _writer, svc = setup(tmp_path)
    item_id = new_text_item(repo, DOCS["rust"])
    repo.transition(item_id, ItemStatus.PROCESSING)
    chunks = simple_chunks(item_id, DOCS["rust"])
    # Simulated crash: SQLite committed chunks + outbox, LanceDB never written.
    repo.replace_chunks(item_id, chunks, vectors.table_name)
    repo.transition(item_id, ItemStatus.INDEXED)
    before = svc.verify()
    assert not before.consistent and before.pending_outbox == len(chunks)
    after = svc.reconcile()
    assert after.consistent, after
    assert vectors.count() == len(chunks)


def test_outbox_delete_replayed_after_crash(tmp_path):
    _, repo, vectors, _, writer, svc = setup(tmp_path)
    item_id = index_doc(repo, writer, DOCS["meet"])
    chunks = repo.chunks_for_item(item_id)
    repo.replace_chunks(item_id, chunks[:1], vectors.table_name)  # crash before LanceDB delete
    assert vectors.count() == len(chunks)
    assert svc.reconcile().consistent
    assert vectors.count() == 1


def test_orphan_and_missing_vectors_are_repaired(tmp_path):
    _, repo, vectors, embedder, writer, svc = setup(tmp_path)
    keep = index_doc(repo, writer, DOCS["photo"])
    lost = index_doc(repo, writer, DOCS["rust"])
    orphan_id = "01890000-0000-7000-8000-000000000000"
    vectors.upsert([(orphan_id, keep, "0" * 64, embedder.embed(["orphan"])[0])])
    vectors.delete_items([lost])
    report = svc.verify()
    assert report.orphan_vectors == 1
    assert report.missing_vectors == len(repo.chunks_for_item(lost))
    assert svc.reconcile().consistent


def test_rebuild_preserves_results(tmp_path):
    _, repo, vectors, embedder, writer, svc = setup(tmp_path)
    for text in DOCS.values():
        index_doc(repo, writer, text)
    queries = ["chloroplast light energy", "moved value error", "finance meeting thursday"]
    before = [search_ids(vectors, embedder, q) for q in queries]
    report = svc.rebuild()
    assert report.consistent
    assert [search_ids(vectors, embedder, q) for q in queries] == before
    # Rebuild is repeatable.
    assert svc.rebuild().consistent
    assert [search_ids(vectors, embedder, q) for q in queries] == before


def test_rebuild_after_vector_table_loss_reembeds(tmp_path):
    _, repo, vectors, embedder, writer, svc = setup(tmp_path)
    for text in DOCS.values():
        index_doc(repo, writer, text)
    expected = vectors.count()
    vectors.drop()
    report = svc.rebuild()
    assert report.consistent and vectors.count() == expected
    hit = vectors.search(embedder.embed(["chloroplasts"])[0], 1)[0]
    assert repo.get_chunks([hit.chunk_id])[hit.chunk_id].text.count("chloroplasts")


def test_stuck_item_is_requeued(tmp_path):
    db, repo, _, _, _, svc = setup(tmp_path)
    item_id = new_text_item(repo, "lost job")
    db.conn.execute("DELETE FROM jobs WHERE item_id = ?", (item_id,))
    assert svc.verify().stuck_items == 1
    svc.reconcile()
    assert repo.job_counts() == {"pending": 1}


def test_vectors_are_normalized_and_dimension_checked(tmp_path):
    _, _, vectors, embedder, _, _ = setup(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        vectors.upsert(
            [("01890000-0000-7000-8000-000000000001", "x", "0" * 64, np.ones(10, np.float32))]
        )
    assert np.isclose(np.linalg.norm(embedder.embed(["abc def"])[0]), 1.0)
