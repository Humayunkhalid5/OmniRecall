"""Deletion removes every store and leaves no recoverable bytes (OR-017)."""

from __future__ import annotations

from pathlib import Path

from support import make_stores, new_text_item, simple_chunks

from omnirecall.storage.consistency import ConsistencyService
from omnirecall.storage.deletion import DeletionService
from omnirecall.storage.index import IndexWriter
from omnirecall.storage.states import ItemStatus

MARKER = "zq-unique-marker-7f3a9c-omnirecall"


def raw_scan(root: Path, needle: bytes) -> list[Path]:
    hits = []
    for path in root.rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            hits.append(path)
    return hits


def build(tmp_path):
    db, repo, vectors, embedder = make_stores(tmp_path)
    writer = IndexWriter(repo, vectors, embedder)
    media = tmp_path / "media"
    (media / "imports").mkdir(parents=True)
    return db, repo, vectors, writer, DeletionService(db, repo, vectors, media), media


def index(repo, writer, text, media_uri=None):
    item_id = new_text_item(repo, text, label=f"label {MARKER}" if MARKER in text else "other")
    if media_uri:
        repo.db.conn.execute(
            "UPDATE items SET media_uri = ?, media_status = 'present' WHERE id = ?",
            (media_uri, item_id),
        )
    repo.transition(item_id, ItemStatus.PROCESSING)
    chunks = simple_chunks(item_id, text)
    writer.write_chunks(item_id, chunks, writer.embed_with_cache(chunks, 32))
    repo.transition(item_id, ItemStatus.INDEXED)
    return item_id


def test_delete_is_physical(tmp_path):
    db, repo, vectors, writer, deletion, media = build(tmp_path)
    keep = index(repo, writer, "unrelated note about gardening and tomatoes " * 5)
    media_file = media / "imports" / "victim.txt"
    media_file.write_text(MARKER)
    victim = index(
        repo,
        writer,
        f"secret {MARKER} appears in this chunk text " * 5,
        media_uri="imports/victim.txt",
    )
    victim_chunks = repo.chunks_for_item(victim)
    victim_hashes = [c.text_hash for c in victim_chunks]
    victim_vectors = [v.tobytes() for v in writer.embed_with_cache(victim_chunks, 32).values()]
    db.checkpoint()
    assert raw_scan(tmp_path / "vectors", victim_hashes[0].encode())
    assert raw_scan(tmp_path / "vectors", victim_vectors[0])
    # Sanity: before deletion the marker and the item ID are on disk.
    assert raw_scan(tmp_path / "db", MARKER.encode())
    assert raw_scan(tmp_path / "vectors", victim.encode())

    assert deletion.request(victim) == "deleting"
    assert repo.get_item(victim).status == "deleting"
    assert all(h[1] != victim for h in repo.keyword_search("secret", 10))
    assert deletion.process() == 1

    item = repo.get_item(victim)
    assert item.status == "deleted"
    assert item.content_hash is None and item.source_label is None and item.media_uri is None
    assert repo.chunks_for_item(victim) == []
    assert not media_file.exists()
    assert victim not in vectors.all_item_ids()
    assert raw_scan(tmp_path / "db", MARKER.encode()) == []
    # No content-derived bytes remain in LanceDB: text hashes and raw vectors.
    for chunk_hash in victim_hashes:
        assert raw_scan(tmp_path / "vectors", chunk_hash.encode()) == []
    for vector_bytes in victim_vectors:
        assert raw_scan(tmp_path / "vectors", vector_bytes) == []
    # Only LanceDB's transaction log may still name the opaque item ID in the
    # delete predicate (documented in design.md §7); no data file does.
    leftovers = raw_scan(tmp_path / "vectors", victim.encode())
    assert all("_transactions" in p.parts or p.suffix == ".manifest" for p in leftovers)
    # The other item is untouched and the stores agree.
    assert repo.get_item(keep).status == "indexed"
    assert ConsistencyService(repo, writer).verify().consistent


def test_delete_is_idempotent_and_reimport_allowed(tmp_path):
    _, repo, _, writer, deletion, _ = build(tmp_path)
    text = "reimport me later please " * 4
    item_id = index(repo, writer, text)
    deletion.request(item_id)
    deletion.request(item_id)
    deletion.process()
    assert deletion.process() == 0
    again = new_text_item(repo, text)
    assert again != item_id


def test_interrupted_delete_resumes(tmp_path):
    _, repo, vectors, writer, deletion, _ = build(tmp_path)
    item_id = index(repo, writer, "resume after crash " * 6)
    deletion.request(item_id)
    vectors.delete_items([item_id])  # crash after step 1
    assert repo.open_tombstones()
    assert deletion.process() == 1
    assert repo.get_item(item_id).status == "deleted"


def test_media_outside_root_is_never_deleted(tmp_path):
    _, repo, _, writer, deletion, _ = build(tmp_path)
    outside = tmp_path / "user-file.txt"
    outside.write_text("keep me")
    item_id = index(repo, writer, "traversal attempt " * 5, media_uri="../user-file.txt")
    deletion.request(item_id)
    deletion.process()
    assert outside.exists()


def test_clear_all(tmp_path):
    _db, repo, vectors, writer, deletion, media = build(tmp_path)
    for i in range(3):
        index(repo, writer, f"document number {i} {MARKER} " * 4)
    (media / "imports" / "a.png").write_bytes(b"x")
    assert deletion.clear_all() == 3
    assert repo.status_counts() == {} and vectors.count() == 0
    assert list((media / "imports").iterdir()) == []
    assert raw_scan(tmp_path / "db", MARKER.encode()) == []
