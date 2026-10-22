"""SQLite data access for items, chunks, jobs, outbox, tombstones, sources, exclusions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from omnirecall.errors import NotFoundError
from omnirecall.ids import format_utc, utc_now, uuid7
from omnirecall.storage.db import Database
from omnirecall.storage.states import ItemStatus, JobStatus, check_transition

STAGE_PROCESS = "process"
STAGE_DELETE = "delete"


@dataclass
class Item:
    id: str
    source_type: str
    source_label: str | None
    source_uri: str | None
    captured_at: str
    content_hash: str | None
    media_uri: str | None
    media_status: str
    metadata: dict[str, Any]
    status: str
    error_code: str | None
    skip_reason: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Item:
        return cls(
            id=row["id"],
            source_type=row["source_type"],
            source_label=row["source_label"],
            source_uri=row["source_uri"],
            captured_at=row["captured_at"],
            content_hash=row["content_hash"],
            media_uri=row["media_uri"],
            media_status=row["media_status"],
            metadata=json.loads(row["metadata_json"]),
            status=row["status"],
            error_code=row["error_code"],
            skip_reason=row["skip_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class NewItem:
    source_type: str
    captured_at: str
    content_hash: str | None
    source_label: str | None = None
    source_uri: str | None = None
    media_uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkRow:
    id: str
    item_id: str
    ordinal: int
    text: str
    start_offset: int | None
    end_offset: int | None
    text_hash: str
    chunker_version: str
    embedding_model: str


@dataclass
class Job:
    id: str
    item_id: str
    stage: str
    status: str
    attempt_count: int
    next_attempt_at: str | None
    last_error_code: str | None


@dataclass
class OutboxEntry:
    id: str
    chunk_id: str
    operation: str
    vector_table: str
    attempt_count: int


ITEM_COLUMNS = (
    "id, source_type, source_label, source_uri, captured_at, content_hash, media_uri, "
    "media_status, metadata_json, status, error_code, skip_reason, created_at, updated_at"
)


CHUNK_COLUMNS = (
    "id, item_id, ordinal, text, start_offset, end_offset, text_hash, chunker_version, "
    "embedding_model"
)


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- items -------------------------------------------------------------

    def find_by_hash(self, source_type: str, content_hash: str) -> Item | None:
        row = self.db.conn.execute(
            f"SELECT {ITEM_COLUMNS} FROM items WHERE source_type = ? AND content_hash = ?",  # noqa: S608
            (source_type, content_hash),
        ).fetchone()
        return Item.from_row(row) if row else None

    def create_item(self, new: NewItem) -> tuple[Item, bool]:
        """Persist an item and its processing job in one transaction.

        Returns (item, created). An existing item with the same source type and
        content hash is returned instead of creating a duplicate.
        """
        with self.db.write() as conn:
            if new.content_hash is not None:
                existing = self.find_by_hash(new.source_type, new.content_hash)
                if existing is not None:
                    return existing, False
            now = utc_now()
            item_id = uuid7()
            conn.execute(
                f"INSERT INTO items ({ITEM_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",  # noqa: S608
                (
                    item_id,
                    new.source_type,
                    new.source_label,
                    new.source_uri,
                    new.captured_at,
                    new.content_hash,
                    new.media_uri,
                    "present" if new.media_uri else "none",
                    json.dumps(new.metadata, separators=(",", ":")),
                    ItemStatus.QUEUED.value,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            self._insert_job(conn, item_id, STAGE_PROCESS, now)
        return self.get_item(item_id), True

    def create_skipped_item(self, new: NewItem, reason: str) -> tuple[Item, bool]:
        """Record a duplicate/excluded capture: hash and reason only, no content."""
        with self.db.write() as conn:
            if new.content_hash is not None:
                existing = self.find_by_hash(new.source_type, new.content_hash)
                if existing is not None:
                    return existing, False
            now = utc_now()
            item_id = uuid7()
            conn.execute(
                "INSERT INTO items (id, source_type, captured_at, content_hash, status, "
                "skip_reason, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    new.source_type,
                    new.captured_at,
                    new.content_hash,
                    ItemStatus.SKIPPED.value,
                    reason,
                    now,
                    now,
                ),
            )
        return self.get_item(item_id), True

    def get_item(self, item_id: str) -> Item:
        row = self.db.conn.execute(
            f"SELECT {ITEM_COLUMNS} FROM items WHERE id = ?",  # noqa: S608
            (item_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Item")
        return Item.from_row(row)

    def get_items(self, item_ids: list[str]) -> dict[str, Item]:
        found: dict[str, Item] = {}
        for start in range(0, len(item_ids), 500):
            batch = item_ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            for row in self.db.conn.execute(
                f"SELECT {ITEM_COLUMNS} FROM items WHERE id IN ({marks})",  # noqa: S608
                batch,
            ):
                found[row["id"]] = Item.from_row(row)
        return found

    def list_items(
        self, statuses: list[str] | None = None, limit: int = 50, offset: int = 0
    ) -> list[Item]:
        sql = f"SELECT {ITEM_COLUMNS} FROM items"  # noqa: S608
        args: list[Any] = []
        if statuses:
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        sql += " ORDER BY captured_at DESC, id DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        return [Item.from_row(r) for r in self.db.conn.execute(sql, args)]

    def status_counts(self) -> dict[str, int]:
        rows = self.db.conn.execute("SELECT status, COUNT(*) AS n FROM items GROUP BY status")
        return {r["status"]: int(r["n"]) for r in rows}

    def transition(
        self,
        item_id: str,
        target: ItemStatus,
        error_code: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        def apply(c: sqlite3.Connection) -> None:
            row = c.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise NotFoundError("Item")
            if row["status"] == target.value:
                return  # idempotent
            check_transition(row["status"], target.value)
            c.execute(
                "UPDATE items SET status = ?, error_code = ?, updated_at = ? WHERE id = ?",
                (target.value, error_code, utc_now(), item_id),
            )

        if conn is not None:
            apply(conn)
        else:
            with self.db.write() as c:
                apply(c)

    def set_metadata(self, item_id: str, updates: dict[str, Any]) -> None:
        with self.db.write() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("Item")
            merged = json.loads(row["metadata_json"]) | updates
            conn.execute(
                "UPDATE items SET metadata_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, separators=(",", ":")), utc_now(), item_id),
            )

    def items_with_media(
        self, source_types: list[str] | None = None, captured_before: str | None = None
    ) -> list[Item]:
        """Items whose app-owned media is still present, oldest first."""
        sql = f"SELECT {ITEM_COLUMNS} FROM items WHERE media_status = 'present'"  # noqa: S608
        args: list[Any] = []
        if source_types:
            sql += f" AND source_type IN ({','.join('?' * len(source_types))})"
            args.extend(source_types)
        if captured_before:
            sql += " AND captured_at < ?"
            args.append(captured_before)
        sql += " ORDER BY captured_at, id"
        return [Item.from_row(r) for r in self.db.conn.execute(sql, args)]

    def set_media_status(self, item_id: str, status: str, clear_uri: bool = False) -> None:
        with self.db.write() as conn:
            if clear_uri:
                conn.execute(
                    "UPDATE items SET media_status = ?, media_uri = NULL, updated_at = ? "
                    "WHERE id = ?",
                    (status, utc_now(), item_id),
                )
            else:
                conn.execute(
                    "UPDATE items SET media_status = ?, updated_at = ? WHERE id = ?",
                    (status, utc_now(), item_id),
                )

    # ---- chunks ------------------------------------------------------------

    def chunks_for_item(self, item_id: str) -> list[ChunkRow]:
        rows = self.db.conn.execute(
            "SELECT id, item_id, ordinal, text, start_offset, end_offset, text_hash, "
            "chunker_version, embedding_model FROM chunks WHERE item_id = ? ORDER BY ordinal",
            (item_id,),
        )
        return [ChunkRow(**dict(r)) for r in rows]

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, ChunkRow]:
        found: dict[str, ChunkRow] = {}
        for start in range(0, len(chunk_ids), 500):
            batch = chunk_ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            sql = f"SELECT {CHUNK_COLUMNS} FROM chunks WHERE id IN ({marks})"  # noqa: S608
            for row in self.db.conn.execute(sql, batch):
                found[row["id"]] = ChunkRow(**dict(row))
        return found

    def replace_chunks(
        self, item_id: str, chunks: list[ChunkRow], vector_table: str
    ) -> list[OutboxEntry]:
        """Atomically make `chunks` the item's chunk set and queue vector writes.

        Retries with the same deterministic chunk IDs leave exactly one copy.
        """
        now = utc_now()
        entries: list[OutboxEntry] = []
        with self.db.write() as conn:
            existing = {
                r["id"]: r["text_hash"]
                for r in conn.execute(
                    "SELECT id, text_hash FROM chunks WHERE item_id = ?", (item_id,)
                )
            }
            new_ids = {c.id for c in chunks}
            removed = [cid for cid in existing if cid not in new_ids]
            for cid in removed:
                conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
                entries.append(self._outbox(conn, cid, "delete", vector_table, now))
            for chunk in chunks:
                if existing.get(chunk.id) == chunk.text_hash:
                    conn.execute(
                        "UPDATE chunks SET embedding_model = ? WHERE id = ?",
                        (chunk.embedding_model, chunk.id),
                    )
                else:
                    conn.execute("DELETE FROM chunks WHERE id = ?", (chunk.id,))
                    conn.execute(
                        "INSERT INTO chunks (id, item_id, ordinal, text, start_offset, end_offset, "
                        "text_hash, chunker_version, embedding_model, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            chunk.id,
                            chunk.item_id,
                            chunk.ordinal,
                            chunk.text,
                            chunk.start_offset,
                            chunk.end_offset,
                            chunk.text_hash,
                            chunk.chunker_version,
                            chunk.embedding_model,
                            now,
                        ),
                    )
                entries.append(self._outbox(conn, chunk.id, "upsert", vector_table, now))
        return entries

    def chunk_ids_for_items(self, item_ids: list[str]) -> list[str]:
        ids: list[str] = []
        for start in range(0, len(item_ids), 500):
            batch = item_ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            ids.extend(
                r["id"]
                for r in self.db.conn.execute(
                    f"SELECT id FROM chunks WHERE item_id IN ({marks})",  # noqa: S608
                    batch,
                )
            )
        return ids

    def indexed_chunk_ids(self) -> set[str]:
        rows = self.db.conn.execute(
            "SELECT c.id FROM chunks c JOIN items i ON i.id = c.item_id WHERE i.status = 'indexed'"
        )
        return {r["id"] for r in rows}

    def all_chunk_ids(self) -> set[str]:
        return {r["id"] for r in self.db.conn.execute("SELECT id FROM chunks")}

    def chunk_count(self) -> int:
        return int(self.db.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def iter_chunks(self, batch_size: int = 256) -> Any:
        last = ""
        while True:
            rows = self.db.conn.execute(
                "SELECT id, item_id, ordinal, text, start_offset, end_offset, text_hash, "
                "chunker_version, embedding_model FROM chunks WHERE id > ? ORDER BY id LIMIT ?",
                (last, batch_size),
            ).fetchall()
            if not rows:
                return
            yield [ChunkRow(**dict(r)) for r in rows]
            last = rows[-1]["id"]

    # ---- keyword search ----------------------------------------------------

    def keyword_search(self, fts_query: str, limit: int) -> list[tuple[str, str, float]]:
        """(chunk_id, item_id, bm25) for indexed items, best first."""
        rows = self.db.conn.execute(
            "SELECT c.id AS chunk_id, c.item_id AS item_id, bm25(chunks_fts) AS score "
            "FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
            "JOIN items i ON i.id = c.item_id "
            "WHERE chunks_fts MATCH ? AND i.status = 'indexed' "
            "ORDER BY score LIMIT ?",
            (fts_query, limit),
        )
        return [(r["chunk_id"], r["item_id"], float(r["score"])) for r in rows]

    def optimize_fts(self) -> None:
        with self.db.write() as conn:
            conn.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('optimize')")

    def rebuild_fts(self) -> None:
        with self.db.write() as conn:
            conn.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('rebuild')")

    def fts_integrity_ok(self) -> bool:
        try:
            self.db.conn.execute(
                "INSERT INTO chunks_fts (chunks_fts, rank) VALUES ('integrity-check', 1)"
            )
        except sqlite3.DatabaseError:
            return False
        return True

    # ---- outbox ------------------------------------------------------------

    def _outbox(
        self, conn: sqlite3.Connection, chunk_id: str, operation: str, table: str, now: str
    ) -> OutboxEntry:
        entry = OutboxEntry(uuid7(), chunk_id, operation, table, 0)
        conn.execute(
            "INSERT INTO vector_outbox (id, chunk_id, operation, vector_table, status, "
            "attempt_count, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (entry.id, chunk_id, operation, table, "pending", 0, now, now),
        )
        return entry

    def enqueue_vector_deletes(self, chunk_ids: list[str], table: str) -> list[OutboxEntry]:
        now = utc_now()
        with self.db.write() as conn:
            return [self._outbox(conn, cid, "delete", table, now) for cid in chunk_ids]

    def pending_outbox(self, limit: int = 1000) -> list[OutboxEntry]:
        rows = self.db.conn.execute(
            "SELECT id, chunk_id, operation, vector_table, attempt_count FROM vector_outbox "
            "WHERE status = 'pending' ORDER BY created_at, id LIMIT ?",
            (limit,),
        )
        return [OutboxEntry(**dict(r)) for r in rows]

    def outbox_pending_for_item(self, item_id: str) -> int:
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM vector_outbox o JOIN chunks c ON c.id = o.chunk_id "
            "WHERE c.item_id = ? AND o.status = 'pending'",
            (item_id,),
        ).fetchone()
        return int(row[0])

    def mark_outbox(self, entry_ids: list[str], status: str) -> None:
        if not entry_ids:
            return
        now = utc_now()
        with self.db.write() as conn:
            for start in range(0, len(entry_ids), 500):
                batch = entry_ids[start : start + 500]
                marks = ",".join("?" * len(batch))
                conn.execute(
                    f"UPDATE vector_outbox SET status = ?, attempt_count = attempt_count + 1, "  # noqa: S608
                    f"updated_at = ? WHERE id IN ({marks})",
                    [status, now, *batch],
                )

    def bump_outbox_attempts(self, entry_ids: list[str], max_attempts: int) -> None:
        now = utc_now()
        with self.db.write() as conn:
            for eid in entry_ids:
                conn.execute(
                    "UPDATE vector_outbox SET attempt_count = attempt_count + 1, updated_at = ?, "
                    "status = CASE WHEN attempt_count + 1 >= ? THEN 'failed' ELSE status END "
                    "WHERE id = ?",
                    (now, max_attempts, eid),
                )

    def purge_done_outbox(self) -> None:
        with self.db.write() as conn:
            conn.execute("DELETE FROM vector_outbox WHERE status = 'done'")

    # ---- jobs --------------------------------------------------------------

    def _insert_job(self, conn: sqlite3.Connection, item_id: str, stage: str, now: str) -> str:
        job_id = uuid7()
        conn.execute(
            "INSERT INTO jobs (id, item_id, stage, status, attempt_count, next_attempt_at, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (job_id, item_id, stage, JobStatus.PENDING.value, 0, now, now, now),
        )
        return job_id

    def enqueue_job(self, item_id: str, stage: str = STAGE_PROCESS) -> str:
        with self.db.write() as conn:
            return self._insert_job(conn, item_id, stage, utc_now())

    def active_job_count(self) -> int:
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('pending','running')"
        ).fetchone()
        return int(row[0])

    def job_counts(self) -> dict[str, int]:
        rows = self.db.conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {r["status"]: int(r["n"]) for r in rows}

    def claim_job(self, now: datetime | None = None) -> Job | None:
        """Atomically move the oldest ready pending job to running."""
        moment = format_utc(now or datetime.now(UTC))
        with self.db.write() as conn:
            row = conn.execute(
                "SELECT id, item_id, stage, status, attempt_count, next_attempt_at, "
                "last_error_code FROM jobs WHERE status = 'pending' "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
                "ORDER BY next_attempt_at, id LIMIT 1",
                (moment,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
                (utc_now(), row["id"]),
            )
        job = Job(**dict(row))
        job.status = JobStatus.RUNNING.value
        return job

    def next_job_due(self) -> str | None:
        row = self.db.conn.execute(
            "SELECT MIN(next_attempt_at) FROM jobs WHERE status = 'pending'"
        ).fetchone()
        return row[0] if row else None

    def complete_job(self, job_id: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'done', updated_at = ? WHERE id = ?", (utc_now(), job_id)
            )

    def fail_job(self, job: Job, error_code: str, backoff_s: list[int], max_retries: int) -> bool:
        """Record a failure. Returns True if the job will be retried."""
        attempts = job.attempt_count + 1
        retry = attempts <= max_retries
        now = datetime.now(UTC)
        with self.db.write() as conn:
            if retry:
                delay = backoff_s[min(attempts - 1, len(backoff_s) - 1)] if backoff_s else 0
                conn.execute(
                    "UPDATE jobs SET status = 'pending', attempt_count = ?, next_attempt_at = ?, "
                    "last_error_code = ?, updated_at = ? WHERE id = ?",
                    (
                        attempts,
                        format_utc(now + timedelta(seconds=delay)),
                        error_code,
                        utc_now(),
                        job.id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = 'failed', attempt_count = ?, last_error_code = ?, "
                    "updated_at = ? WHERE id = ?",
                    (attempts, error_code, utc_now(), job.id),
                )
        return retry

    def cancel_jobs(self, item_id: str) -> int:
        with self.db.write() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? "
                "WHERE item_id = ? AND status IN ('pending','running')",
                (utc_now(), item_id),
            )
            return cur.rowcount

    def job_status(self, job_id: str) -> str | None:
        row = self.db.conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row["status"] if row else None

    def reset_running_jobs(self) -> int:
        """Restart recovery: work that was running when the engine stopped is re-queued."""
        with self.db.write() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'pending', next_attempt_at = ?, updated_at = ? "
                "WHERE status = 'running'",
                (utc_now(), utc_now()),
            )
            return cur.rowcount

    def purge_finished_jobs(self) -> None:
        with self.db.write() as conn:
            conn.execute("DELETE FROM jobs WHERE status IN ('done','cancelled')")

    # ---- tombstones --------------------------------------------------------

    def add_tombstone(self, conn: sqlite3.Connection, item_id: str, stores: list[str]) -> None:
        conn.execute(
            "INSERT INTO tombstones (item_id, requested_at, pending_stores, completed_at) "
            "VALUES (?,?,?,NULL) ON CONFLICT(item_id) DO UPDATE SET "
            "pending_stores = excluded.pending_stores, "
            "completed_at = NULL",
            (item_id, utc_now(), json.dumps(stores)),
        )

    def open_tombstones(self) -> list[tuple[str, list[str]]]:
        rows = self.db.conn.execute(
            "SELECT item_id, pending_stores FROM tombstones WHERE completed_at IS NULL "
            "ORDER BY requested_at"
        )
        return [(r["item_id"], json.loads(r["pending_stores"])) for r in rows]

    def update_tombstone(self, item_id: str, pending: list[str]) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE tombstones SET pending_stores = ? WHERE item_id = ?",
                (json.dumps(pending), item_id),
            )

    # ---- sources -----------------------------------------------------------

    def get_source(self, source_type: str) -> tuple[bool, dict[str, Any]] | None:
        row = self.db.conn.execute(
            "SELECT enabled, configuration_json FROM sources WHERE source_type = ?", (source_type,)
        ).fetchone()
        if row is None:
            return None
        return bool(row["enabled"]), json.loads(row["configuration_json"])

    def upsert_source(self, source_type: str, enabled: bool, configuration: dict[str, Any]) -> None:
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO sources (id, source_type, enabled, configuration_json, updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(source_type) DO UPDATE SET "
                "enabled = excluded.enabled, configuration_json = excluded.configuration_json, "
                "updated_at = excluded.updated_at",
                (uuid7(), source_type, int(enabled), json.dumps(configuration), utc_now()),
            )

    # ---- exclusions --------------------------------------------------------

    def list_exclusions(self) -> list[dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT id, rule_type, rule_value, enabled, created_at FROM exclusions "
            "ORDER BY created_at"
        )
        return [dict(r) | {"enabled": bool(r["enabled"])} for r in rows]

    def create_exclusion(self, rule_type: str, rule_value: str, enabled: bool = True) -> str:
        exclusion_id = uuid7()
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO exclusions (id, rule_type, rule_value, enabled, created_at) "
                "VALUES (?,?,?,?,?)",
                (exclusion_id, rule_type, rule_value, int(enabled), utc_now()),
            )
        return exclusion_id

    def update_exclusion(
        self, exclusion_id: str, rule_value: str | None, enabled: bool | None
    ) -> None:
        with self.db.write() as conn:
            row = conn.execute("SELECT id FROM exclusions WHERE id = ?", (exclusion_id,)).fetchone()
            if row is None:
                raise NotFoundError("Exclusion")
            if rule_value is not None:
                conn.execute(
                    "UPDATE exclusions SET rule_value = ? WHERE id = ?", (rule_value, exclusion_id)
                )
            if enabled is not None:
                conn.execute(
                    "UPDATE exclusions SET enabled = ? WHERE id = ?", (int(enabled), exclusion_id)
                )

    def delete_exclusion(self, exclusion_id: str) -> None:
        with self.db.write() as conn:
            cur = conn.execute("DELETE FROM exclusions WHERE id = ?", (exclusion_id,))
            if cur.rowcount == 0:
                raise NotFoundError("Exclusion")
