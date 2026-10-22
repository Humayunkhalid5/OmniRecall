"""Physical deletion across SQLite, FTS5, LanceDB, and app-owned media (design.md §7)."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from omnirecall import logs
from omnirecall.ids import utc_now
from omnirecall.storage.db import Database
from omnirecall.storage.media import owned_media_path, remove_media
from omnirecall.storage.repository import Repository
from omnirecall.storage.states import ItemStatus
from omnirecall.storage.vectors import VectorStore

STORES = ["vectors", "sqlite", "fts", "media"]


class DeletionService:
    def __init__(
        self,
        db: Database,
        repo: Repository,
        vectors: VectorStore,
        media_root: Path,
        lock: threading.RLock | None = None,
    ) -> None:
        self.lock = lock or threading.RLock()
        self.db = db
        self.repo = repo
        self.vectors = vectors
        self.media_root = media_root.resolve()

    def request(self, item_id: str) -> str:
        """Tombstone the item: hidden from search at once, cleanup runs async."""
        item = self.repo.get_item(item_id)
        if item.status in (ItemStatus.DELETING, ItemStatus.DELETED):
            return item.status
        with self.db.write() as conn:
            self.repo.transition(item_id, ItemStatus.DELETING, conn=conn)
            self.repo.add_tombstone(conn, item_id, list(STORES))
            conn.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? "
                "WHERE item_id = ? AND status IN ('pending','running')",
                (utc_now(), item_id),
            )
        logs.info("delete_requested", item_id=item_id)
        return ItemStatus.DELETING.value

    def _media_path(self, media_uri: str | None) -> Path | None:
        return owned_media_path(self.media_root, media_uri)

    def process(self) -> int:
        """Run cleanup for all open tombstones. Returns how many completed."""
        with self.lock:
            return self._process()

    def _process(self) -> int:
        tombstones = self.repo.open_tombstones()
        if not tombstones:
            return 0
        item_ids = [item_id for item_id, _ in tombstones]
        # 1. Vectors, by item so chunk rows are not needed.
        self.vectors.delete_items(item_ids)
        for item_id in item_ids:
            self.repo.update_tombstone(item_id, ["sqlite", "fts", "media"])
        # 2. SQLite rows (FTS rows go with them via triggers) and content fields.
        media_paths: dict[str, Path | None] = {}
        with self.db.write() as conn:
            for item_id in item_ids:
                row = conn.execute(
                    "SELECT media_uri FROM items WHERE id = ?", (item_id,)
                ).fetchone()
                media_paths[item_id] = self._media_path(row["media_uri"] if row else None)
                chunk_ids = [
                    r["id"]
                    for r in conn.execute("SELECT id FROM chunks WHERE item_id = ?", (item_id,))
                ]
                for cid in chunk_ids:
                    conn.execute("DELETE FROM vector_outbox WHERE chunk_id = ?", (cid,))
                conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
                conn.execute("DELETE FROM jobs WHERE item_id = ?", (item_id,))
                conn.execute(
                    "UPDATE items SET content_hash = NULL, source_label = NULL, source_uri = NULL, "
                    "media_uri = NULL, metadata_json = '{}', error_code = NULL, "
                    "skip_reason = NULL, "
                    "media_status = CASE media_status WHEN 'none' THEN 'none' ELSE 'deleted' END, "
                    "updated_at = ? WHERE id = ?",
                    (utc_now(), item_id),
                )
        # 3. Owned media.
        for path in media_paths.values():
            if path is None:
                continue
            remove_media(path)
        for item_id in item_ids:
            self.repo.update_tombstone(item_id, ["physical"])
        # 4. Physical removal of freed bytes.
        self.repo.optimize_fts()
        self.vectors.compact_and_cleanup()
        self.db.checkpoint()
        # 5. Verify each store, then finish.
        completed = 0
        remaining_vector_items = self.vectors.all_item_ids()
        for item_id in item_ids:
            chunk_left = self.db.conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE item_id = ?", (item_id,)
            ).fetchone()[0]
            media = media_paths.get(item_id)
            if chunk_left or item_id in remaining_vector_items or (media and media.exists()):
                logs.error("delete_verify_failed", item_id=item_id)
                continue
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE tombstones SET pending_stores = '[]', completed_at = ? "
                    "WHERE item_id = ?",
                    (utc_now(), item_id),
                )
                self.repo.transition(item_id, ItemStatus.DELETED, conn=conn)
            completed += 1
        self.db.checkpoint()
        logs.info("delete_completed", count=completed)
        return completed

    def clear_all(self) -> int:
        """Delete every item and its derived data. Settings, sources, and exclusions stay."""
        with self.lock:
            return self._clear_all()

    def _clear_all(self) -> int:
        count = int(self.db.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
        self.vectors.drop()
        with self.db.write() as conn:
            for table in ("vector_outbox", "jobs", "tombstones", "chunks", "items"):
                conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
            conn.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('rebuild')")
        self.repo.optimize_fts()
        for sub in ("screenshots", "imports", "audio", "incoming"):
            directory = self.media_root / sub
            if directory.is_dir():
                shutil.rmtree(directory)
            directory.mkdir(parents=True, exist_ok=True)
        self.db.checkpoint()
        self.db.vacuum()
        self.db.checkpoint()
        logs.info("index_cleared", count=count)
        return count
