"""Consistency checks, reconciliation, and index rebuild (rules.md §4.5, §4.9)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
import pyarrow as pa

from omnirecall import logs
from omnirecall.storage.index import IndexWriter
from omnirecall.storage.repository import STAGE_PROCESS, Repository
from omnirecall.storage.states import ItemStatus


@dataclass
class ConsistencyReport:
    sqlite_chunks: int
    vector_rows: int
    missing_vectors: int
    orphan_vectors: int
    pending_outbox: int
    stuck_items: int
    fts_ok: bool
    vector_index_ok: bool = True

    @property
    def consistent(self) -> bool:
        return (
            self.vector_index_ok
            and self.missing_vectors == 0
            and self.orphan_vectors == 0
            and self.pending_outbox == 0
            and self.stuck_items == 0
            and self.fts_ok
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"consistent": self.consistent}


class ConsistencyService:
    def __init__(
        self,
        repo: Repository,
        writer: IndexWriter,
        batch_size: int = 32,
        on_repaired: Callable[[ConsistencyReport], None] | None = None,
    ) -> None:
        self.repo = repo
        self.writer = writer
        self.batch_size = batch_size
        self.on_repaired = on_repaired or (lambda _report: None)

    def _stuck_items(self) -> list[str]:
        """Items queued/processing with no live job, e.g. after a lost job row."""
        rows = self.repo.db.conn.execute(
            "SELECT i.id FROM items i WHERE i.status IN ('queued','processing') AND NOT EXISTS ("
            "SELECT 1 FROM jobs j WHERE j.item_id = i.id AND j.status IN ('pending','running')) "
            "AND NOT EXISTS (SELECT 1 FROM vector_outbox o JOIN chunks c ON c.id = o.chunk_id "
            "WHERE c.item_id = i.id AND o.status = 'pending')"
        )
        return [r["id"] for r in rows]

    def verify(self) -> ConsistencyReport:
        sqlite_ids = self.repo.indexed_chunk_ids()
        all_sqlite = self.repo.all_chunk_ids()
        try:
            vector_ids = self.writer.vectors.all_chunk_ids()
            vector_ok = True
        except Exception:  # noqa: BLE001 - unreadable table: report it, repair elsewhere
            vector_ids, vector_ok = set(), False
        return ConsistencyReport(
            sqlite_chunks=len(all_sqlite),
            vector_rows=len(vector_ids),
            missing_vectors=len(sqlite_ids - vector_ids),
            orphan_vectors=len(vector_ids - all_sqlite),
            pending_outbox=len(self.repo.pending_outbox(limit=100_000)),
            stuck_items=len(self._stuck_items()),
            fts_ok=self.repo.fts_integrity_ok(),
            vector_index_ok=vector_ok,
        )

    def repair_damaged(self) -> ConsistencyReport | None:
        """If the vector table is damaged, delete it and re-embed from SQLite."""
        if not self.writer.embedder.available() or not self.discard_if_damaged():
            return None
        report = self.rebuild()
        self.on_repaired(report)
        return report

    def discard_if_damaged(self) -> bool:
        """Delete the vector table if any of it is unreadable (D-035). True if it was."""
        with self.writer.lock:
            if self.writer.vectors.check():
                return False
            logs.error("vector_index_damaged")
            self.writer.vectors.discard()
            return True

    def reconcile(self) -> ConsistencyReport:
        """Repair divergence; SQLite wins. Safe to run at every startup."""
        # Without the model a damaged table is kept until vectors can be rebuilt.
        repaired = self.repair_damaged()
        if repaired is not None:
            return repaired
        self.writer.apply_pending_outbox(self.batch_size)
        all_sqlite = self.repo.all_chunk_ids()
        vector_ids = self.writer.vectors.all_chunk_ids()
        orphans = sorted(vector_ids - all_sqlite)
        if orphans:
            self.writer.vectors.delete_chunks(orphans)
        missing = sorted(self.repo.indexed_chunk_ids() - vector_ids)
        if missing:
            rows = list(self.repo.get_chunks(missing).values())
            vectors = self.writer.embed_with_cache(rows, self.batch_size)
            self.writer.vectors.upsert(
                [(r.id, r.item_id, r.text_hash, vectors[r.id]) for r in rows]
            )
        for item_id in self._stuck_items():
            self.repo.enqueue_job(item_id, STAGE_PROCESS)
        if not self.repo.fts_integrity_ok():
            self.repo.rebuild_fts()
        report = self.verify()
        logs.info(
            "reconciled",
            count=len(orphans) + len(missing),
            status="consistent" if report.consistent else "inconsistent",
        )
        return report

    def rebuild(self) -> ConsistencyReport:
        """Rebuild FTS and the vector table from SQLite without losing data.

        Vectors are rebuilt into a side table first; the live table is only
        replaced once the side table is complete. Valid existing vectors are
        reused through the embedding cache; anything else is re-embedded.
        """
        self.discard_if_damaged()
        store = self.writer.vectors
        side = f"{store.table_name}__rebuild"
        store.drop_named(side)
        try:
            existing = store.read_all()
        except Exception:  # noqa: BLE001 - corrupted table: re-embed everything
            logs.warning("vector_table_unreadable")
            existing = None
        cache: dict[str, np.ndarray] = {}
        if existing is not None and existing.num_rows:
            for text_hash, vector in zip(
                existing.column("text_hash").to_pylist(),
                existing.column("vector").to_pylist(),
                strict=True,
            ):
                if vector is not None and len(vector) == store.dimension:
                    cache.setdefault(text_hash, np.asarray(vector, dtype=np.float32))
        batches: list[pa.Table] = []
        for rows in self.repo.iter_chunks(batch_size=256):
            indexed = [r for r in rows if self._item_status(r.item_id) == ItemStatus.INDEXED.value]
            if not indexed:
                continue
            todo = [r for r in indexed if r.text_hash not in cache]
            if todo:
                computed = self.writer.embed_with_cache(todo, self.batch_size)
                for r in todo:
                    cache[r.text_hash] = computed[r.id]
            batches.append(
                store.rows([(r.id, r.item_id, r.text_hash, cache[r.text_hash]) for r in indexed])
            )
        data = pa.concat_tables(batches) if batches else store.schema().empty_table()
        store.write_table(side, data)
        store.write_table(store.table_name, data)
        store.drop_named(side)
        self.repo.rebuild_fts()
        self.repo.optimize_fts()
        report = self.verify()
        logs.info("index_rebuilt", count=data.num_rows)
        return report

    def _item_status(self, item_id: str) -> str:
        row = self.repo.db.conn.execute(
            "SELECT status FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return str(row["status"]) if row else ""
