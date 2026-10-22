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
from omnirecall.capture.clipboard import ClipboardCapture
from omnirecall.capture.exclusions import ExclusionService
from omnirecall.capture.screenshot import Frame, ScreenshotCapture
from omnirecall.capture.state import CaptureState
from omnirecall.embeddings.base import Embedder, vector_table_name
from omnirecall.embeddings.minilm import MODEL_ID as MINILM_ID
from omnirecall.embeddings.minilm import MiniLMEmbedder
from omnirecall.errors import EngineError
from omnirecall.export import Exporter
from omnirecall.extraction.audio import AudioDecoder
from omnirecall.extraction.documents import AUDIO_FORMATS, DOCUMENT_FORMATS, IMAGE_FORMATS
from omnirecall.extraction.ocr import OcrEngine, TesseractOcr
from omnirecall.extraction.transcribe import Transcriber, WhisperCppTranscriber
from omnirecall.ingestion.pipeline import TRANSCRIPTION_MODEL_MISSING, Pipeline
from omnirecall.ingestion.service import IngestionService
from omnirecall.jobs.queue import JobRunner
from omnirecall.models import ModelManager
from omnirecall.retrieval.search import SearchFilters, SearchService
from omnirecall.settings import Settings, SettingsStore
from omnirecall.storage.consistency import ConsistencyReport, ConsistencyService
from omnirecall.storage.db import Database
from omnirecall.storage.deletion import DeletionService
from omnirecall.storage.index import IndexWriter
from omnirecall.storage.repository import STAGE_PROCESS, Item, Repository
from omnirecall.storage.retention import RetentionService
from omnirecall.storage.states import ItemStatus
from omnirecall.storage.vectors import VectorStore

Notify = Callable[[str, dict[str, Any]], None]
CHUNK_PREVIEW_LIMIT = 50
RETENTION_INTERVAL_S = 3600
# Changed only through capture.pause, which notifies the shell.
SHELL_MANAGED_SETTINGS = frozenset({"capture_paused"})
# Settings the shell's screenshot watcher follows; a change re-sends capture.state.
WATCHER_SETTINGS = ("screenshot_interval_s", "pause_on_idle_s", "screenshot_phash_threshold")
WHISPER_ID = "whisper-base"
# Failures that a model install can fix; those items are retried after it.
MODEL_MISSING_CODES = ("model_missing", TRANSCRIPTION_MODEL_MISSING)


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
        "media_uri": item.media_uri,
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
        ocr: OcrEngine | None = None,
        transcriber: Transcriber | None = None,
        audio: AudioDecoder | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.models_dir = models_dir or data_dir / "models"
        self.media_root = data_dir / "media"
        self.notify = notify
        self.started_at = time.monotonic()
        self._server: RpcServer | None = None
        self._stop = threading.Event()
        self._vector_wake = threading.Event()

        self.ocr: OcrEngine = ocr or TesseractOcr()
        subdirs = (
            "db",
            "vectors",
            "logs",
            "exports",
            "media/incoming",
            "media/imports",
            "media/screenshots",
        )
        for sub in subdirs:
            (data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.db = Database(data_dir / "db" / "omnirecall.sqlite")
        self.db.migrate()
        self.repo = Repository(self.db)
        self.settings_store = SettingsStore(self.db)
        self._settings = self.settings_store.load()

        self.models = ModelManager(self.models_dir)
        self.embedder: Embedder = embedder or MiniLMEmbedder(self.models.model_dir(MINILM_ID))
        self.audio = audio or AudioDecoder()
        self.transcriber: Transcriber = transcriber or WhisperCppTranscriber(
            self.models.model_file(WHISPER_ID), WHISPER_ID
        )
        self.vectors = VectorStore(
            data_dir / "vectors",
            vector_table_name(self.embedder.model_id, self.embedder.dimension),
            self.embedder.dimension,
            self.embedder.model_id,
        )
        self.writer = IndexWriter(self.repo, self.vectors, self.embedder)
        self.consistency = ConsistencyService(
            self.repo,
            self.writer,
            self._settings.embedding_batch_size,
            on_repaired=self._on_repaired,
        )
        self.deletion = DeletionService(
            self.db, self.repo, self.vectors, self.media_root, lock=self.writer.lock
        )
        self._vector_repair = threading.Event()
        self._repairing = False
        # Set once the startup reconciliation has run (tests wait on it).
        self.startup_reconciled = threading.Event()
        self.search_service = SearchService(
            self.repo, self.vectors, self.embedder, on_vector_failure=self._request_vector_repair
        )
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
            ocr=self.ocr,
            audio=self.audio,
            transcriber=self.transcriber,
            vectors_ready=self._vector_wake.set,
        )
        self.runner.register(STAGE_PROCESS, self.pipeline.process)
        self.exclusions = ExclusionService(self.repo)
        self.ingestion.is_excluded = self._path_excluded
        self.capture_state = CaptureState(self.repo, self.settings_store, self._capture_changed)
        self.clipboard = ClipboardCapture(
            self.capture_state, self.exclusions, self.ingestion, lambda: self._settings
        )
        self.screenshots = ScreenshotCapture(
            self.capture_state,
            self.exclusions,
            self.repo,
            self.media_root,
            lambda: self._settings,
            lambda: self.runner.wake(),
            self.ocr.available,
        )
        self.pipeline.reviewers["screenshot"] = self.screenshots.review
        self.pipeline.on_discard = self._screenshot_discarded
        self._clear_incoming()
        self.retention = RetentionService(self.repo, self.media_root, self.writer.lock)
        self.exporter = Exporter(self.db, self.media_root, self.data_dir)
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
        self.transcriber.close()
        self.db.close()

    def _screenshot_discarded(self, _item: Item, reason: str) -> None:
        self.screenshots.record(reason)

    def _clear_incoming(self) -> None:
        """Frames left in media/incoming by a crash were never accepted; remove them."""
        for leftover in (self.media_root / "incoming").glob("shot-*.png"):
            leftover.unlink(missing_ok=True)

    def _path_excluded(self, path: Path) -> bool:
        resolved = path.resolve()
        # The app's own data is never imported back into itself.
        if resolved.is_relative_to(self.data_dir.resolve()):
            return True
        return self.exclusions.rules().path_excluded(resolved)

    def _capture_changed(self, state: dict[str, Any]) -> None:
        self._settings = self.settings_store.load()
        self.ingestion.settings = self._settings
        logs.info("capture_state", status="capturing" if state["capturing"] else "idle")
        # The full state, so the shell's watchers keep the screenshot timing.
        self.notify("capture.state", self.capture_get({}))

    def _run_retention(self) -> None:
        report = self.retention.run(self._settings)
        if report.pruned_by_age or report.pruned_by_cap:
            self.notify("media.pruned", report.to_dict())

    def _on_exhausted(self, job: Any, code: str) -> None:
        self.pipeline.on_exhausted(job, code)

    def _request_vector_repair(self) -> None:
        self._vector_repair.set()
        self._maintenance_wake.set()

    def _repair_vectors(self) -> None:
        """Rebuild a damaged vector table from SQLite (D-035); searches stay keyword-only."""
        if not self.embedder.available():
            return
        self._repairing = True
        try:
            self.consistency.repair_damaged()
        finally:
            self._repairing = False

    def _on_repaired(self, report: ConsistencyReport) -> None:
        self.notify("index.repaired", {"vectors": report.vector_rows})
        self._vector_wake.set()

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
                    if not self.vectors.check():
                        self._request_vector_repair()
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
            self.consistency.reconcile()  # also repairs a damaged vector table
            self._vector_repair.clear()
        except Exception as exc:  # noqa: BLE001 - reported in status, retried next start
            logs.error("startup_reconcile_failed", reason=type(exc).__name__)
        finally:
            self.startup_reconciled.set()
        last_unload_check = time.monotonic()
        last_retention = 0.0
        while not self._stop.is_set():
            self._maintenance_wake.wait(timeout=2.0)
            self._maintenance_wake.clear()
            if self._stop.is_set():
                break
            try:
                if self._vector_repair.is_set():
                    self._vector_repair.clear()
                    self._repair_vectors()
                if self.repo.open_tombstones():
                    completed = self.deletion.process()
                    if completed:
                        self.notify("items.deleted", {"count": completed})
                if self.repo.pending_outbox(limit=1):
                    self._vector_wake.set()
                if time.monotonic() - last_retention > RETENTION_INTERVAL_S:
                    last_retention = time.monotonic()
                    self._run_retention()
                if time.monotonic() - last_unload_check > 30:
                    last_unload_check = time.monotonic()
                    self.embedder.unload_if_idle(self._settings.model_idle_unload_s)
                    self.transcriber.unload_if_idle(self._settings.model_idle_unload_s)
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
            "capture.state": self.capture_get,
            "capture.set_source": self.capture_set_source,
            "capture.pause": self.capture_pause,
            "capture.clipboard": self.capture_clipboard,
            "capture.screenshot_check": self.capture_screenshot_check,
            "capture.screenshot": self.capture_screenshot,
            "capture.screenshot_skip": self.capture_screenshot_skip,
            "exclusions.list": self.exclusions_list,
            "exclusions.add": self.exclusions_add,
            "exclusions.add_path": self.exclusions_add_path,
            "exclusions.update": self.exclusions_update,
            "exclusions.remove": self.exclusions_remove,
            "export.create": self.export_create,
            "storage.usage": self.storage_usage,
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
            "transcription": {
                "id": self.transcriber.model_id,
                "installed": self.transcriber.available(),
                "loaded": self.transcriber.loaded(),
                "decoder_available": self.audio.available(),
            },
            "index": {
                "chunks": self.repo.chunk_count(),
                "vectors": self._vector_count(),
                "repairing": self._repairing or self._vector_repair.is_set(),
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
                    "start_ms": c.start_ms,
                    "end_ms": c.end_ms,
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

    def _vector_count(self) -> int | None:
        try:
            return self.vectors.count()
        except Exception:  # noqa: BLE001 - damaged table; status must still answer
            self._request_vector_repair()
            return None

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
        managed = SHELL_MANAGED_SETTINGS & p.changes.keys()
        if managed:
            from omnirecall.errors import ValidationError

            raise ValidationError("Use the capture controls to pause capture", sorted(managed)[0])
        before = self._settings
        self._settings = self.settings_store.update(p.changes)
        self.ingestion.settings = self._settings
        retention_keys = ("screenshot_retention_days", "media_cap_bytes")
        if any(getattr(before, k) != getattr(self._settings, k) for k in retention_keys):
            self._run_retention()
        if any(getattr(before, k) != getattr(self._settings, k) for k in WATCHER_SETTINGS):
            self.notify("capture.state", self.capture_get({}))
        return {"settings": self._settings.model_dump()}

    # ---- capture and privacy -----------------------------------------------

    def capture_get(self, _params: dict[str, Any]) -> dict[str, Any]:
        version = self.ocr.version()
        return self.capture_state.snapshot() | {
            "session": {
                "clipboard": self.clipboard.counts(),
                "screenshot": self.screenshots.counts(),
            },
            "screenshot": {
                "interval_s": self._settings.screenshot_interval_s,
                "pause_on_idle_s": self._settings.pause_on_idle_s,
                "phash_threshold": self._settings.screenshot_phash_threshold,
            },
            "ocr": {"available": version is not None, "engine": self.ocr.name, "version": version},
        }

    def capture_set_source(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.CaptureSourceParams.model_validate(params)
        self.capture_state.set_source(p.source_type, p.enabled, p.paused)
        return self.capture_get({})

    def capture_pause(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.CapturePauseParams.model_validate(params)
        self.capture_state.set_paused(p.paused)
        return self.capture_get({})

    def capture_clipboard(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ClipboardCaptureParams.model_validate(params)
        return self.clipboard.capture(p.text, p.app, p.app_known)

    def capture_screenshot_check(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ScreenshotCheckParams.model_validate(params)
        return self.screenshots.check(p.app, p.app_known)

    def capture_screenshot(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ScreenshotParams.model_validate(params)
        return self.screenshots.submit(Frame(**p.model_dump()))

    def capture_screenshot_skip(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ScreenshotSkipParams.model_validate(params)
        return self.screenshots.skip(p.reason)

    def exclusions_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"exclusions": self.repo.list_exclusions()}

    def exclusions_add(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ExclusionAddParams.model_validate(params)
        exclusion_id = self.exclusions.add(p.rule_type, p.rule_value)
        return {"id": exclusion_id, "exclusions": self.repo.list_exclusions()}

    def exclusions_add_path(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ExclusionPathParams.model_validate(params)
        exclusion_id = self.exclusions.add("path", p.rule_value)
        return {"id": exclusion_id, "exclusions": self.repo.list_exclusions()}

    def exclusions_update(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ExclusionUpdateParams.model_validate(params)
        self.repo.update_exclusion(p.id, None, p.enabled)
        return {"exclusions": self.repo.list_exclusions()}

    def exclusions_remove(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ExclusionRef.model_validate(params)
        self.repo.delete_exclusion(p.id)
        return {"exclusions": self.repo.list_exclusions()}

    def export_create(self, params: dict[str, Any]) -> dict[str, Any]:
        p = schemas.ExportParams.model_validate(params)
        return self.exporter.export(
            p.path, progress=lambda n: self.notify("export.progress", {"items": n})
        )

    def storage_usage(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "media_bytes": self.retention.usage(),
            "media_cap_bytes": self._settings.media_cap_bytes,
            "screenshot_retention_days": self._settings.screenshot_retention_days,
            "text_only_mode": self._settings.text_only_mode,
        }

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
        """Items that failed only because the model was missing are retried, and a
        vector table found damaged while the model was missing is rebuilt."""
        self._request_vector_repair()
        marks = ",".join("?" * len(MODEL_MISSING_CODES))
        rows = self.db.conn.execute(
            f"SELECT id FROM items WHERE status = 'failed' AND error_code IN ({marks})",  # noqa: S608
            MODEL_MISSING_CODES,
        ).fetchall()
        for row in rows:
            self.repo.transition(row["id"], ItemStatus.QUEUED)
            self.repo.enqueue_job(row["id"])
        if rows:
            self.runner.wake()

    def formats_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        def view(formats: Any) -> list[dict[str, Any]]:
            return [
                {"kind": f.kind, "label": f.label, "extensions": list(f.extensions)}
                for f in formats
            ]

        return {
            "documents": view(DOCUMENT_FORMATS),
            "images": view(IMAGE_FORMATS),
            "audio": view(AUDIO_FORMATS),
            "ocr_available": self.ocr.available(),
            "transcription_available": self.transcriber.available() and self.audio.available(),
            "audio_decoder_available": self.audio.available(),
        }
