"""Cross-store writes: SQLite chunks + FTS + outbox, then LanceDB vectors.

SQLite and LanceDB cannot share a transaction (OR-004). Every vector change
is first recorded in `vector_outbox` in the same SQLite transaction as the
chunk change, then applied to LanceDB and marked done. Anything left pending
after a crash is replayed by `apply_pending_outbox`.
"""

from __future__ import annotations

import threading

import numpy as np

from omnirecall import logs
from omnirecall.embeddings.base import Embedder, Vectors
from omnirecall.storage.repository import ChunkRow, OutboxEntry, Repository
from omnirecall.storage.vectors import VectorStore

MAX_OUTBOX_ATTEMPTS = 5


class IndexWriter:
    def __init__(self, repo: Repository, vectors: VectorStore, embedder: Embedder) -> None:
        self.repo = repo
        self.vectors = vectors
        self.embedder = embedder
        # Serializes LanceDB writers (vector worker, deletion, rebuild) so a
        # delete can never interleave with an upsert of the same item.
        self.lock = threading.RLock()

    def embed_with_cache(self, chunks: list[ChunkRow], batch_size: int) -> dict[str, Vectors]:
        """Vectors by chunk ID, reusing cached vectors for identical text (D-011)."""
        cached = self.vectors.cached_vectors([c.text_hash for c in chunks])
        result: dict[str, Vectors] = {}
        todo: list[ChunkRow] = []
        for chunk in chunks:
            hit = cached.get(chunk.text_hash)
            if hit is not None:
                result[chunk.id] = hit
            else:
                todo.append(chunk)
        # Identical texts within this batch are embedded once.
        unique: dict[str, str] = {}
        for chunk in todo:
            unique.setdefault(chunk.text_hash, chunk.text)
        hashes = list(unique)
        computed: dict[str, Vectors] = {}
        for start in range(0, len(hashes), batch_size):
            batch = hashes[start : start + batch_size]
            vectors = self.embedder.embed([unique[h] for h in batch])
            for text_hash, vector in zip(batch, vectors, strict=True):
                computed[text_hash] = vector
        for chunk in todo:
            result[chunk.id] = computed[chunk.text_hash]
        logs.debug("embed_batch", count=len(chunks), reason=f"cached={len(chunks) - len(todo)}")
        return result

    def write_chunks(
        self, item_id: str, chunks: list[ChunkRow], vectors: dict[str, Vectors]
    ) -> None:
        entries = self.repo.replace_chunks(item_id, chunks, self.vectors.table_name)
        with self.lock:
            self._apply(entries, vectors)

    def _apply(self, entries: list[OutboxEntry], vectors: dict[str, Vectors]) -> None:
        upserts = [e for e in entries if e.operation == "upsert"]
        deletes = [e for e in entries if e.operation == "delete"]
        if deletes:
            self.vectors.delete_chunks([e.chunk_id for e in deletes])
        if upserts:
            chunk_rows = self.repo.get_chunks([e.chunk_id for e in upserts])
            records = [
                (cid, row.item_id, row.text_hash, vectors[cid])
                for cid, row in chunk_rows.items()
                if cid in vectors
            ]
            self.vectors.upsert(records)
        self.repo.mark_outbox([e.id for e in entries], "done")

    def apply_pending_batch(self, batch_size: int = 32, limit: int = 256) -> tuple[int, set[str]]:
        """Apply up to `limit` pending outbox entries in one LanceDB write.

        This is the normal ingestion path as well as crash replay: the
        pipeline commits chunks and outbox rows, and this worker embeds
        across items in batches. Returns (entries applied, item IDs upserted).
        """
        with self.lock:
            entries = [
                e
                for e in self.repo.pending_outbox(limit=limit)
                if e.vector_table == self.vectors.table_name
            ]
            if not entries:
                return 0, set()
            try:
                upserts = [e for e in entries if e.operation == "upsert"]
                chunk_rows = self.repo.get_chunks([e.chunk_id for e in upserts])
                vectors = self.embed_with_cache(list(chunk_rows.values()), batch_size)
                # Upserts whose chunk no longer exists are obsolete; _apply marks them done.
                self._apply(entries, vectors)
            except Exception as exc:
                logs.error("outbox_apply_failed", reason=type(exc).__name__, count=len(entries))
                self.repo.bump_outbox_attempts([e.id for e in entries], MAX_OUTBOX_ATTEMPTS)
                raise
            return len(entries), {row.item_id for row in chunk_rows.values()}

    def apply_pending_outbox(self, batch_size: int = 32) -> int:
        """Replay every pending vector write (startup reconciliation)."""
        applied = 0
        while True:
            try:
                count, _items = self.apply_pending_batch(batch_size, limit=500)
            except Exception:  # noqa: BLE001 - already logged; retried next run
                return applied
            if not count:
                return applied
            applied += count


def as_matrix(vectors: list[Vectors]) -> Vectors:
    return np.stack(vectors).astype(np.float32)
