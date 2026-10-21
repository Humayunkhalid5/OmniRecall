"""LanceDB vector index (not the source of truth; rules.md §2.3).

One table per embedding model and dimension, `chunks__<model>__<dim>`, so
incompatible vectors can never share a table (rules.md §4.8).
"""

from __future__ import annotations

import re
import threading
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from omnirecall.embeddings.base import Vectors

_SAFE_ID = re.compile(r"^[0-9a-f-]{36}$")
_SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    item_id: str
    distance: float


def _quote_ids(values: Iterable[str], pattern: re.Pattern[str]) -> str:
    """Build a SQL IN list from validated identifiers only (no user text)."""
    safe = []
    for value in values:
        if not pattern.match(value):
            raise ValueError("unsafe identifier in vector filter")
        safe.append(f"'{value}'")
    return ", ".join(safe)


class VectorStore:
    def __init__(self, root: Path, table_name: str, dimension: int, model_id: str) -> None:
        import lancedb

        root.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(root))
        self.root = root
        self.table_name = table_name
        self.dimension = dimension
        self.model_id = model_id
        self._lock = threading.RLock()
        self._table: Any = None
        self._writes_since_compaction = 0

    def _exists(self, name: str) -> bool:
        token: str | None = None
        while True:
            page = self._db.list_tables(page_token=token) if token else self._db.list_tables()
            if name in page.tables:
                return True
            token = page.page_token
            if not token:
                return False

    def schema(self) -> pa.Schema:
        return pa.schema(
            [
                pa.field("chunk_id", pa.string(), nullable=False),
                pa.field("item_id", pa.string(), nullable=False),
                pa.field("text_hash", pa.string(), nullable=False),
                pa.field("embedding_model", pa.string(), nullable=False),
                pa.field("vector", pa.list_(pa.float32(), self.dimension), nullable=False),
            ]
        )

    def _open(self, create: bool = True) -> Any:
        if self._table is None:
            if self._exists(self.table_name):
                self._table = self._db.open_table(self.table_name)
            elif create:
                self._table = self._db.create_table(self.table_name, schema=self.schema())
        return self._table

    def rows(self, records: list[tuple[str, str, str, Vectors]]) -> pa.Table:
        vectors = np.stack([r[3] for r in records]).astype(np.float32)
        if vectors.shape[1] != self.dimension:
            raise ValueError("vector dimension does not match table")
        flat = pa.array(vectors.reshape(-1), type=pa.float32())
        return pa.Table.from_arrays(
            [
                pa.array([r[0] for r in records], pa.string()),
                pa.array([r[1] for r in records], pa.string()),
                pa.array([r[2] for r in records], pa.string()),
                pa.array([self.model_id] * len(records), pa.string()),
                pa.FixedSizeListArray.from_arrays(flat, self.dimension),
            ],
            schema=self.schema(),
        )

    def upsert(self, records: list[tuple[str, str, str, Vectors]]) -> None:
        """Insert or replace by chunk_id. Records: (chunk_id, item_id, text_hash, vector)."""
        if not records:
            return
        with self._lock:
            table = self._open()
            (
                table.merge_insert("chunk_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(self.rows(records))
            )
            self._after_write()

    COMPACT_EVERY = 64

    def _after_write(self) -> None:
        """Each write adds a LanceDB version and fragment; compact periodically."""
        self._writes_since_compaction += 1
        if self._writes_since_compaction >= self.COMPACT_EVERY:
            self.compact_and_cleanup()

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return
            for start in range(0, len(chunk_ids), 500):
                batch = chunk_ids[start : start + 500]
                table.delete(f"chunk_id IN ({_quote_ids(batch, _SAFE_ID)})")

    def delete_items(self, item_ids: list[str]) -> None:
        if not item_ids:
            return
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return
            for start in range(0, len(item_ids), 500):
                batch = item_ids[start : start + 500]
                table.delete(f"item_id IN ({_quote_ids(batch, _SAFE_ID)})")

    def search(self, query: Vectors, limit: int) -> list[VectorHit]:
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return []
            result = (
                table.search(query.astype(np.float32), vector_column_name="vector")
                .distance_type("cosine")
                .limit(limit)
                .select(["chunk_id", "item_id", "_distance"])
                .to_arrow()
                .to_pydict()
            )
        return [
            VectorHit(chunk_id=c, item_id=i, distance=float(d))
            for c, i, d in zip(
                result["chunk_id"], result["item_id"], result["_distance"], strict=True
            )
        ]

    def cached_vectors(self, text_hashes: list[str]) -> dict[str, Vectors]:
        """Embedding cache lookup by text hash for this table's model."""
        if not text_hashes:
            return {}
        found: dict[str, Vectors] = {}
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return {}
            unique = sorted(set(text_hashes))
            for start in range(0, len(unique), 500):
                batch = unique[start : start + 500]
                rows = (
                    table.search()
                    .where(f"text_hash IN ({_quote_ids(batch, _SAFE_HASH)})")
                    .select(["text_hash", "vector"])
                    .limit(len(batch) * 4)
                    .to_arrow()
                    .to_pydict()
                )
                for text_hash, vector in zip(rows["text_hash"], rows["vector"], strict=True):
                    found.setdefault(text_hash, np.asarray(vector, dtype=np.float32))
        return found

    def all_chunk_ids(self) -> set[str]:
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return set()
            ids = table.to_arrow().column("chunk_id").to_pylist()
        return set(ids)

    def all_item_ids(self) -> set[str]:
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return set()
            ids = table.to_arrow().column("item_id").to_pylist()
        return set(ids)

    def read_all(self) -> pa.Table | None:
        with self._lock:
            table = self._open(create=False)
            return None if table is None else table.to_arrow()

    def write_table(self, name: str, data: pa.Table) -> None:
        """Create table `name` holding `data` (used by rebuild)."""
        with self._lock:
            if self._exists(name):
                self._db.drop_table(name)
            created = self._db.create_table(name, schema=self.schema())
            if data.num_rows:
                created.add(data)
            if name == self.table_name:
                self._table = created

    def drop_named(self, name: str) -> None:
        with self._lock:
            if self._exists(name):
                self._db.drop_table(name)
            if name == self.table_name:
                self._table = None

    def count(self) -> int:
        with self._lock:
            table = self._open(create=False)
            return 0 if table is None else int(table.count_rows())

    def compact_and_cleanup(self) -> None:
        """Compact files and drop old versions so deleted rows leave the disk."""
        with self._lock:
            table = self._open(create=False)
            if table is None:
                return
            # The engine is the only process using this table, so dropping every
            # old version immediately is safe and required for physical deletion.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                table.optimize(cleanup_older_than=timedelta(0), delete_unverified=True)
            self._writes_since_compaction = 0

    def drop(self) -> None:
        with self._lock:
            if self._exists(self.table_name):
                self._db.drop_table(self.table_name)
            self._table = None

    def disk_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
