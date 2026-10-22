"""Recovery mode: the engine found its database damaged and serves only repair calls (D-036).

Starting the normal engine on a damaged file would fail, or fail later in the
middle of a write. Instead the engine starts in this mode, answers `status`
with the damage, and offers two actions the user chooses between in the app:

* `database.recover` copies every readable row into a new database, replaces
  the damaged file, and removes media no recovered item refers to. Capture is
  turned off afterwards, because exclusions may not all have been readable.
* `database.reset` permanently deletes the database, the vectors, and all media
  OmniRecall stored, and starts empty. Imported originals are never touched.

After either action the app restarts the engine, which then starts normally.

A database written by a newer OmniRecall (`schema_too_new`) is not damaged:
this mode then only reports it, and both actions are refused, so a downgrade
can never delete data a newer version can still read.
"""

from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from omnirecall import __version__, logs
from omnirecall.api import protocol, schemas
from omnirecall.api.server import RpcServer
from omnirecall.errors import EngineError
from omnirecall.storage.media import owned_media_path, remove_media
from omnirecall.storage.salvage import DatabaseDamagedError, salvage

DB_NAME = "omnirecall.sqlite"
# Folders of media the engine owns; their files exist only for indexed items.
MEDIA_DIRS = ("screenshots", "imports", "audio", "incoming")


def _db_files(db_path: Path) -> list[Path]:
    return [db_path, *(db_path.with_name(db_path.name + s) for s in ("-wal", "-shm", "-journal"))]


class RecoveryEngine:
    def __init__(self, data_dir: Path, reason: str) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "db" / DB_NAME
        self.reason = reason
        self.started_at = time.monotonic()
        self.done: str | None = None

    def register(self, server: RpcServer) -> None:
        server.register("health", self.health)
        server.register("status", self.status)
        server.register("shutdown", lambda _p: self._stop(server))
        server.register("database.recover", self.recover)
        server.register("database.reset", self.reset)

    @staticmethod
    def _stop(server: RpcServer) -> dict[str, Any]:
        server.request_stop()
        return {"stopping": True}

    def health(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.HealthParams.model_validate(params)
        if p.protocol_version is not None and p.protocol_version != protocol.PROTOCOL_VERSION:
            raise EngineError(
                "protocol_mismatch",
                "The app and engine versions do not match; reinstall OmniRecall",
                {"engine": protocol.PROTOCOL_VERSION, "client": p.protocol_version},
            )
        return {
            "ok": True,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "engine_version": __version__,
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - self.started_at, 3),
            "platform": platform.system().lower(),
        }

    def status(self, _params: dict[str, Any]) -> dict[str, Any]:
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "engine": "recovery",
            "database": {
                "state": "restart_needed" if self.done else "damaged",
                "reason": self.reason,
                "bytes": size,
                "path": str(self.db_path),
                "action": self.done,
            },
        }

    def _require_pending(self) -> None:
        if self.reason == "schema_too_new":
            raise EngineError(
                "schema_too_new",
                "This data was created by a newer OmniRecall version; update the app",
            )
        if self.done:
            raise EngineError("restart_needed", "Restart OmniRecall to finish")

    def recover(self, params: dict[str, Any]) -> dict[str, Any]:
        schemas.ClearParams.model_validate(params)
        self._require_pending()
        target = self.db_path.with_name(DB_NAME + ".recovering")
        try:
            report = salvage(self.db_path, target)
        except (sqlite3.DatabaseError, DatabaseDamagedError, OSError) as exc:
            for path in _db_files(target):
                path.unlink(missing_ok=True)
            logs.error("database_salvage_failed", reason=type(exc).__name__)
            raise EngineError(
                "recovery_failed",
                "Nothing could be recovered from the damaged database; start over instead",
            ) from exc
        for path in _db_files(self.db_path):
            path.unlink(missing_ok=True)
        target.replace(self.db_path)
        removed = self._remove_unreferenced_media()
        self._capture_off()
        self.done = "recovered"
        return report.to_dict() | {"media_removed": removed}

    def reset(self, params: dict[str, Any]) -> dict[str, Any]:
        schemas.ClearParams.model_validate(params)
        self._require_pending()
        for path in _db_files(self.db_path):
            path.unlink(missing_ok=True)
        vectors = self.data_dir / "vectors"
        if vectors.is_dir():
            shutil.rmtree(vectors)
        removed = 0
        for sub in MEDIA_DIRS:
            folder = self.data_dir / "media" / sub
            for path in folder.rglob("*") if folder.is_dir() else []:
                if path.is_file():
                    path.unlink()
                    removed += 1
        self.done = "reset"
        logs.info("database_reset", count=removed)
        return {"media_removed": removed}

    def _remove_unreferenced_media(self) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            uris = [
                r[0]
                for r in conn.execute("SELECT media_uri FROM items WHERE media_uri IS NOT NULL")
            ]
        finally:
            conn.close()
        media_root = self.data_dir / "media"
        keep: set[Path] = set()
        for uri in uris:
            path = owned_media_path(media_root, uri)
            if path is not None:
                keep.add(path)
                keep.add(path.with_name(path.stem + ".thumb.webp"))
        removed = 0
        for sub in MEDIA_DIRS:
            folder = media_root / sub
            for path in folder.rglob("*") if folder.is_dir() else []:
                if path.is_file() and path.resolve() not in keep:
                    remove_media(path)
                    removed += 1
        return removed

    def _capture_off(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("UPDATE sources SET enabled = 0")
            conn.commit()
        finally:
            conn.close()
