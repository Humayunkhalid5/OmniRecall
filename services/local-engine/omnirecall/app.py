"""Engine composition root: wires stores, workers, and RPC handlers."""

from __future__ import annotations

import os
import platform
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omnirecall import __version__, logs
from omnirecall.api import protocol, schemas
from omnirecall.api.server import RpcServer
from omnirecall.embeddings.base import Embedder, vector_table_name
from omnirecall.embeddings.minilm import MODEL_ID as MINILM_ID
from omnirecall.embeddings.minilm import MiniLMEmbedder
from omnirecall.errors import EngineError
from omnirecall.extraction.documents import DOCUMENT_FORMATS
from omnirecall.ingestion.pipeline import Pipeline
from omnirecall.ingestion.service import IngestionService
from omnirecall.jobs.queue import JobRunner
from omnirecall.models import ModelManager
from omnirecall.retrieval.search import SearchFilters, SearchService
from omnirecall.settings import Settings, SettingsStore
from omnirecall.storage.consistency import ConsistencyService
from omnirecall.storage.db import Database
from omnirecall.storage.deletion import DeletionService
from omnirecall.storage.index import IndexWriter
from omnirecall.storage.repository import STAGE_PROCESS, Item, Repository
from omnirecall.storage.states import ItemStatus
from omnirecall.storage.vectors import VectorStore

Notify = Callable[[str, dict[str, Any]], None]
CHUNK_PREVIEW_LIMIT = 50


def _dir_bytes(path: Path) -> int:
    total = 0
    if path.is_dir():
        for entry in path.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
    return total


def item_view(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_type": item.source_type,
        "source_label": item.source_label,
        "source_uri": item.source_uri,
        "captured_at": item.captured_at,
        "media_status": item.media_status,
        "metadata": item.metadata,
        "status": item.status,
        "error_code": item.error_code,
        "skip_reason": item.skip_reason,
        "updated_at": item.updated_at,
    }


class Engine:
    def __init__(
        self,
        data_dir: Path,
        models_dir: Path | None,
        notify: Notify,
        embedder: Embedder | None = None,
        start_workers: bool = True,
    ) -> None:
        self.data_dir = data_dir
        self.models_dir = models_dir or data_dir / "models"
        self.media_root = data_dir / "media"
        self.notify = notify
        self.started_at = time.monotonic()
        self._server: RpcServer | None = None
        self._stop = threading.Event()
        self._vector_wake = threading.Event()

        for sub in ("db", "vectors", "logs", "exports", "media/incoming", "media/imports"):
            (data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.db = Database(data_dir / "db" / "omnirecall.sqlite")
        self.db.migrate()
        self.repo = Repository(self.db)
        self.settings_store = SettingsStore(self.db)
        self._settings = self.settings_store.load()

        self.models = ModelManager(self.models_dir)
        self.embedder: Embedder = embedder or MiniLMEmbedder(self.models.model_dir(MINILM_ID))
        self.vectors = VectorStore(
            data_dir / "vectors",
            vector_table_name(self.embedder.model_id, self.embedder.dimension),
            self.embedder.dimension,
            self.embedder.model_id,
        )
        self.writer = IndexWriter(self.repo, self.vectors, self.embedder)
        self.consistency = ConsistencyService(
            self.repo, self.writer, self._settings.embedding_batch_size
        )
        self.deletion = DeletionService(
            self.db, self.repo, self.vectors, self.media_root, lock=self.writer.lock
        )
        self.search_service = SearchService(self.repo, self.vectors, self.embedder)
        self.runner = JobRunner(
            self.repo,
            concurrency=self._settings.worker_concurrency,
            max_retries=self._settings.job_max_retries,
            backoff_s=self._settings.job_backoff_s,
            on_exhausted=self._on_exhausted,
        )
        self.ingestion = IngestionService(
            self.repo, self.media_root, self._settings, self.runner.wake
        )
        self.pipeline = Pipeline(
            self.repo,
            self.writer,
            self.embedder,
            self.media_root,
            lambda: self._settings,
            notify,
            vectors_ready=self._vector_wake.set,
        )
        self.runner.register(STAGE_PROCESS, self.pipeline.process)
        self._maintenance: threading.Thread | None = None
        self._vector_thread: threading.Thread | None = None
        self._maintenance_wake = threading.Event()
        if start_workers:
            self.start()

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.runner.start()
        self._maintenance = threading.Thread(
            target=self._maintenance_loop, name="maintenance", daemon=True
        )
        self._maintenance.start()
        self._vector_thread = threading.Thread(
            target=self._vector_loop, name="vectors", daemon=True
        )
        self._vector_thread.start()

    def close(self) -> None:
        self._stop.set()
        self._maintenance_wake.set()
        self._vector_wake.set()
        self.runner.stop()
        for thread in (self._maintenance, self._vector_thread):
            if thread:
                thread.join(timeout=30)
        self.db.close()

    def _on_exhausted(self, job: Any, code: str) -> None:
        self.pipeline.on_exhausted(job, code)

    def _vector_loop(self) -> None:
        """Embed and write vectors across items in batches, then finalize items."""
        while not self._stop.is_set():
            self._vector_wake.wait(timeout=1.0)
            self._vector_wake.clear()
            while not self._stop.is_set():
                if not self.embedder.available():
                    break
                try:
                    count, item_ids = self.writer.apply_pending_batch(
                        self._settings.embedding_batch_size, limit=256
                    )
                except Exception:  # noqa: BLE001 - logged inside; retry after a pause
                    self._stop.wait(2.0)
                    break
                if not count:
                    break
                for item_id in sorted(item_ids):
                    try:
                        self.pipeline.finalize(item_id)
                    except EngineError as exc:
                        logs.warning("finalize_failed", item_id=item_id, error_code=exc.code)

    def _maintenance_loop(self) -> None:
        try:
            if self.embedder.available():
                self._requeue_model_missing()
            self.consistency.reconcile()
        except Exception as exc:  # noqa: BLE001 - reported in status, retried next start
            logs.error("startup_reconcile_failed", reason=type(exc).__name__)
        last_unload_check = time.monotonic()
        while not self._stop.is_set():
            self._maintenance_wake.wait(timeout=2.0)
            self._maintenance_wake.clear()
            if self._stop.is_set():
                break
            try:
                if self.repo.open_tombstones():
                    completed = self.deletion.process()
                    if completed:
                        self.notify("items.deleted", {"count": completed})
                if self.repo.pending_outbox(limit=1):
                    self._vector_wake.set()
                if time.monotonic() - last_unload_check > 30:
                    last_unload_check = time.monotonic()
                    self.embedder.unload_if_idle(self._settings.model_idle_unload_s)
            except Exception as exc:  # noqa: BLE001 - retried on the next tick
                logs.error("maintenance_failed", reason=type(exc).__name__)

    # ---- registration ------------------------------------------------------

    def register(self, server: RpcServer) -> None:
        self._server = server
        server.on_shutdown(self.close)
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "health": self.health,
            "status": self.status,
            "shutdown": self.shutdown,
            "items.import_text": self.import_text,
            "items.import_paths": self.import_paths,
            "items.list": self.list_items,
            "items.get": self.get_item,
            "items.delete": self.delete_item,
            "items.retry": self.retry_item,
            "jobs.cancel": self.cancel_job,
            "search": self.search,
            "index.verify": self.index_verify,
            "index.rebuild": self.index_rebuild,
            "index.clear": self.index_clear,
            "settings.get": self.settings_get,
            "settings.update": self.settings_update,
            "models.list": self.models_list,
            "models.download": self.models_download,
            "models.install_file": self.models_install_file,
            "models.cancel": self.models_cancel,
            "formats.list": self.formats_list,
        }
        for method, handler in handlers.items():
            server.register(method, handler)

    # ---- handlers ----------------------------------------------------------

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
        model_installed = self.embedder.available()
        return {
            "engine": "running",
            "uptime_s": round(time.monotonic() - self.started_at, 3),
            "items": self.repo.status_counts(),
            "jobs": self.repo.job_counts(),
            "queue": {
                "capacity": self._settings.queue_capacity,
                "active": self.repo.active_job_count(),
                "workers_busy": self.runner.active,
                "workers": self._settings.worker_concurrency,
            },
            "model": {
                "id": self.embedder.model_id,
                "installed": model_installed,
                "loaded": self.embedder.loaded() if model_installed else False,
            },
            "index": {
                "chunks": self.repo.chunk_count(),
                "vectors": self.vectors.count(),
                "table": self.vectors.table_name,
                "pending_vector_writes": len(self.repo.pending_outbox(limit=10_000)),
            },
            "storage": {
                "data_dir": str(self.data_dir),
                "db_bytes": _dir_bytes(self.data_dir / "db"),
                "vector_bytes": _dir_bytes(self.data_dir / "vectors"),
                "media_bytes": _dir_bytes(self.media_root),
                "model_bytes": _dir_bytes(self.models_dir),
            },
            "encryption_at_rest": False,
        }

    def shutdown(self, _params: dict[str, Any]) -> dict[str, Any]:
        if self._server is not None:
            self._server.request_stop()
        return {"stopping": True}

    def import_text(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ImportTextParams.model_validate(params)
        item, created = self.ingestion.import_text(p.text, "text", p.label)
        return {"item": item_view(item), "created": created}

    def import_paths(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ImportPathsParams.model_validate(params)
        return self.ingestion.import_paths(p.paths).to_dict()

    def list_items(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ListItemsParams.model_validate(params)
        statuses: list[str] = (
            list(p.status) if p.status else [s.value for s in ItemStatus if s != ItemStatus.DELETED]
        )
        items = self.repo.list_items(statuses, p.limit, p.offset)
        return {"items": [item_view(i) for i in items], "counts": self.repo.status_counts()}

    def get_item(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ItemRef.model_validate(params)
        item = self.repo.get_item(p.item_id)
        chunks = self.repo.chunks_for_item(item.id)
        source_exists = bool(item.source_uri) and Path(item.source_uri or "").is_file()
        return {
            "item": item_view(item),
            "source_exists": source_exists,
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "id": c.id,
                    "ordinal": c.ordinal,
                    "text": c.text,
                    "start": c.start_offset,
                    "end": c.end_offset,
                }
                for c in chunks[:CHUNK_PREVIEW_LIMIT]
            ],
        }

    def delete_item(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ItemRef.model_validate(params)
        status = self.deletion.request(p.item_id)
        self._maintenance_wake.set()
        return {"item_id": p.item_id, "status": status}

    def retry_item(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ItemRef.model_validate(params)
        item = self.repo.get_item(p.item_id)
        if item.status != ItemStatus.FAILED:
            raise EngineError("invalid_state", "Only failed items can be retried")
        self.repo.transition(item.id, ItemStatus.QUEUED)
        self.repo.enqueue_job(item.id)
        self.runner.wake()
        return {"item_id": item.id, "status": ItemStatus.QUEUED.value}

    def cancel_job(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ItemRef.model_validate(params)
        item = self.repo.get_item(p.item_id)
        if item.status not in (ItemStatus.QUEUED, ItemStatus.PROCESSING):
            raise EngineError("invalid_state", "This item is not being processed")
        self.repo.cancel_jobs(item.id)
        if item.status == ItemStatus.QUEUED:
            self.repo.transition(item.id, ItemStatus.PROCESSING)
        self.repo.transition(item.id, ItemStatus.FAILED, error_code="cancelled")
        return {"item_id": item.id, "status": ItemStatus.FAILED.value}

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.SearchParams.model_validate(params)
        filters = SearchFilters(**p.filters.model_dump())
        return self.search_service.search(p.query, self._settings, filters, p.limit)

    def index_verify(self, _params: dict[str, Any]) -> dict[str, Any]:
        return self.consistency.verify().to_dict()

    def index_rebuild(self, _params: dict[str, Any]) -> dict[str, Any]:
        self._require_model()
        return self.consistency.rebuild().to_dict()

    def index_clear(self, params: dict[str, Any]) -> dict[str, Any]:
        schemas.ClearParams.model_validate(params)
        # Stop workers so nothing writes while every store is wiped.
        self.runner.stop()
        try:
            count = self.deletion.clear_all()
        finally:
            self.runner = JobRunner(
                self.repo,
                self._settings.worker_concurrency,
                self._settings.job_max_retries,
                self._settings.job_backoff_s,
                self._on_exhausted,
            )
            self.runner.register(STAGE_PROCESS, self.pipeline.process)
            self.ingestion._wake = self.runner.wake
            self.runner.start()
        return {"cleared": count}

    def settings_get(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"settings": self._settings.model_dump(), "defaults": Settings().model_dump()}

    def settings_update(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.SettingsUpdateParams.model_validate(params)
        self._settings = self.settings_store.update(p.changes)
        self.ingestion.settings = self._settings
        return {"settings": self._settings.model_dump()}

    def _require_model(self) -> None:
        if not self.embedder.available():
            from omnirecall.errors import ModelMissingError

            raise ModelMissingError(self.embedder.model_id)

    def models_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"models": self.models.describe(), "models_dir": str(self.models_dir)}

    def models_download(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ModelRef.model_validate(params)
        self.models.manifest(p.model_id)

        def run() -> None:
            last = [0.0]

            def progress(received: int, total: int) -> None:
                now = time.monotonic()
                if now - last[0] > 0.5:
                    last[0] = now
                    self.notify(
                        "models.progress",
                        {"model_id": p.model_id, "received": received, "total": total},
                    )

            try:
                self.models.download(p.model_id, progress)
                self.notify("models.installed", {"model_id": p.model_id})
                self._requeue_model_missing()
            except EngineError as exc:
                self.notify("models.failed", {"model_id": p.model_id, "code": exc.code})

        threading.Thread(target=run, name=f"download-{p.model_id}", daemon=True).start()
        return {"model_id": p.model_id, "state": "downloading"}

    def models_install_file(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ModelFileParams.model_validate(params)
        self.models.install_from_file(p.model_id, Path(p.path))
        self._requeue_model_missing()
        return {"model_id": p.model_id, "installed": True}

    def models_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ModelRef.model_validate(params)
        self.models.cancel(p.model_id)
        return {"model_id": p.model_id}

    def _requeue_model_missing(self) -> None:
        """Items that failed only because the model was missing are retried."""
        rows = self.db.conn.execute(
            "SELECT id FROM items WHERE status = 'failed' AND error_code = 'model_missing'"
        ).fetchall()
        for row in rows:
            self.repo.transition(row["id"], ItemStatus.QUEUED)
            self.repo.enqueue_job(row["id"])
        if rows:
            self.runner.wake()

    def formats_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "documents": [
                {"kind": f.kind, "label": f.label, "extensions": list(f.extensions)}
                for f in DOCUMENT_FORMATS
            ]
        }
