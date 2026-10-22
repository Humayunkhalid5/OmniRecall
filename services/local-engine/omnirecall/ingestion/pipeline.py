"""Processing pipeline: extract → chunk → embed → store (implementation_plan.md §2)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from omnirecall import logs
from omnirecall.chunking.chunker import CHUNKER_VERSION, chunk_text
from omnirecall.embeddings.base import Embedder
from omnirecall.errors import EngineError, ModelMissingError
from omnirecall.extraction.documents import extract_document, format_for
from omnirecall.extraction.ocr import OcrEngine, ocr_file, open_image
from omnirecall.extraction.text import normalize_text
from omnirecall.ids import chunk_id, sha256_text
from omnirecall.settings import Settings
from omnirecall.storage.index import IndexWriter
from omnirecall.storage.media import owned_media_path, remove_media
from omnirecall.storage.repository import ChunkRow, Item, Job, Repository
from omnirecall.storage.states import ItemStatus

Notify = Callable[[str, dict[str, Any]], None]
Extractor = Callable[[Item, Settings], tuple[str, dict[str, Any]]]
# Returns why an extracted item should be dropped instead of indexed, or None.
Reviewer = Callable[[Item, str], str | None]
Discarded = Callable[[Item, str], None]
THUMBNAIL_WIDTH = 640


class Cancelled(Exception):
    """The item was deleted or the engine is stopping; abandon quietly."""


class Pipeline:
    def __init__(
        self,
        repo: Repository,
        writer: IndexWriter,
        embedder: Embedder,
        media_root: Path,
        settings_provider: Callable[[], Settings],
        notify: Notify,
        ocr: OcrEngine,
        vectors_ready: Callable[[], None] = lambda: None,
    ) -> None:
        self.vectors_ready = vectors_ready
        self.ocr = ocr
        self.reviewers: dict[str, Reviewer] = {}
        self.on_discard: Discarded = lambda _item, _reason: None
        self.repo = repo
        self.writer = writer
        self.embedder = embedder
        self.media_root = media_root.resolve()
        self.settings_provider = settings_provider
        self.notify = notify
        self.extractors: dict[str, Extractor] = {
            "text": self._extract_payload,
            "clipboard": self._extract_payload,
            "file": self._extract_file,
            "screenshot": self._extract_screenshot,
        }

    def register_extractor(self, source_type: str, extractor: Extractor) -> None:
        self.extractors[source_type] = extractor

    def _media_path(self, relative: str | None) -> Path:
        if not relative:
            raise EngineError("payload_missing", "The captured content is no longer available")
        path = (self.media_root / relative).resolve()
        if not path.is_relative_to(self.media_root):
            raise EngineError("payload_missing", "The captured content is no longer available")
        return path

    def _extract_payload(self, item: Item, _settings: Settings) -> tuple[str, dict[str, Any]]:
        path = self._media_path(item.media_uri)
        if not path.is_file():
            raise EngineError("payload_missing", "The captured content is no longer available")
        return path.read_text(encoding="utf-8"), {}

    def _extract_file(self, item: Item, settings: Settings) -> tuple[str, dict[str, Any]]:
        if not item.source_uri:
            raise EngineError("source_missing", "The original file is missing")
        path = Path(item.source_uri)
        if not path.is_file():
            raise EngineError("source_missing", "The original file was moved or deleted")
        if format_for(path).kind == "image":
            if path.stat().st_size > settings.max_file_bytes:
                from omnirecall.errors import LimitExceededError

                raise LimitExceededError("file_size", settings.max_file_bytes)
            result = ocr_file(self.ocr, path)
            text = normalize_text(result.text)
            if not text:
                raise EngineError("extraction_empty", "No text was found in this image")
            return text, result.metadata
        extracted = extract_document(path, settings.max_file_bytes, settings.max_pdf_pages)
        return extracted.text, extracted.metadata

    def _extract_screenshot(self, item: Item, settings: Settings) -> tuple[str, dict[str, Any]]:
        path = self._media_path(item.media_uri)
        if not path.is_file():
            raise EngineError("payload_missing", "The screenshot image is no longer available")
        if not self.ocr.available():
            from omnirecall.extraction.ocr import OcrUnavailableError

            raise OcrUnavailableError()
        image = open_image(path)
        result = self.ocr.recognize(image)
        if not settings.text_only_mode:
            thumb = path.with_name(path.stem + ".thumb.webp")
            preview = image.convert("RGB")
            preview.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_WIDTH * 4))
            preview.save(thumb, "WEBP", quality=70)
        # An empty result is a review decision ("no_text"), not a failure.
        return normalize_text(result.text), result.metadata

    def _discard(self, item: Item, reason: str) -> None:
        media_uri = self.repo.discard_item(item.id)
        path = owned_media_path(self.media_root, media_uri)
        if path is not None:
            remove_media(path)
        self.on_discard(item, reason)
        self.notify("items.discarded", {"item_id": item.id, "reason": reason})

    def _progress(self, item_id: str, stage: str) -> None:
        self.notify("items.progress", {"item_id": item_id, "stage": stage})

    def _check_live(self, item_id: str, stopping: Callable[[], bool]) -> Item:
        item = self.repo.get_item(item_id)
        if item.status in (ItemStatus.DELETING, ItemStatus.DELETED) or stopping():
            raise Cancelled
        return item

    def process(self, job: Job, stopping: Callable[[], bool]) -> None:
        try:
            self._process(job, stopping)
        except Cancelled:
            logs.info("job_abandoned", job_id=job.id, item_id=job.item_id)
            if stopping():
                # Leave it running; restart recovery re-queues it.
                raise EngineError("engine_stopping", "The engine is shutting down") from None

    def _process(self, job: Job, stopping: Callable[[], bool]) -> None:
        settings = self.settings_provider()
        item = self._check_live(job.item_id, stopping)
        if not self.embedder.available():
            raise ModelMissingError(self.embedder.model_id)
        if item.status == ItemStatus.FAILED:
            self.repo.transition(item.id, ItemStatus.QUEUED)
        self.repo.transition(item.id, ItemStatus.PROCESSING)
        self._progress(item.id, "extracting")

        extractor = self.extractors.get(item.source_type)
        if extractor is None:
            raise EngineError("unsupported_source", "This source type cannot be processed yet")
        text, extra_meta = extractor(item, settings)
        reviewer = self.reviewers.get(item.source_type)
        if reviewer is not None:
            self._check_live(item.id, stopping)
            reason = reviewer(item, text)
            if reason is not None:
                self._discard(item, reason)
                return
        if not text.strip():
            raise EngineError("extraction_empty", "No text could be extracted")

        self._progress(item.id, "chunking")
        count_tokens = self.embedder.count_tokens if self.embedder.available() else None
        pieces = chunk_text(
            text,
            settings.chunk_size,
            settings.chunk_overlap,
            count_tokens=count_tokens,
            max_tokens=self.embedder.max_tokens,
        )
        if not pieces:
            raise EngineError("extraction_empty", "No text could be extracted")
        rows = [
            ChunkRow(
                id=chunk_id(item.id, piece.ordinal, CHUNKER_VERSION),
                item_id=item.id,
                ordinal=piece.ordinal,
                text=piece.text,
                start_offset=piece.start,
                end_offset=piece.end,
                text_hash=sha256_text(piece.text),
                chunker_version=CHUNKER_VERSION,
                embedding_model=self.embedder.model_id,
            )
            for piece in pieces
        ]

        self._check_live(item.id, stopping)
        self.repo.set_metadata(item.id, extra_meta | {"chunks": len(rows), "chars": len(text)})
        # Chunks, FTS rows, and outbox entries commit together. The vector
        # worker embeds across items in batches and then calls finalize().
        self._progress(item.id, "embedding")
        self.repo.replace_chunks(item.id, rows, self.writer.vectors.table_name)
        self.vectors_ready()

    def finalize(self, item_id: str) -> bool:
        """Mark an item indexed once every vector write for it is applied."""
        item = self.repo.get_item(item_id)
        if item.status != ItemStatus.PROCESSING or self.repo.outbox_pending_for_item(item_id):
            return False
        if self.repo.db.conn.execute(
            "SELECT 1 FROM jobs WHERE item_id = ? AND status = 'pending'", (item_id,)
        ).fetchone():
            return False  # a retry is scheduled; it will finish the item
        self.repo.transition(item_id, ItemStatus.INDEXED)
        # Text payloads are fully represented by their chunks now.
        if item.source_type in ("text", "clipboard") and item.media_uri:
            self._media_path(item.media_uri).unlink(missing_ok=True)
            self.repo.set_media_status(item_id, "none", clear_uri=True)
        # Text-only mode keeps a screenshot's text and drops the image once indexed.
        if (
            item.source_type == "screenshot"
            and item.media_uri
            and self.settings_provider().text_only_mode
        ):
            path = owned_media_path(self.media_root, item.media_uri)
            if path is not None:
                remove_media(path)
            self.repo.set_media_status(item_id, "pruned", clear_uri=True)
        chunks = int(item.metadata.get("chunks", 0))
        self.notify("items.indexed", {"item_id": item_id, "chunks": chunks})
        logs.info("item_indexed", item_id=item_id, count=chunks, source_type=item.source_type)
        return True

    def on_exhausted(self, job: Job, code: str) -> None:
        try:
            item = self.repo.get_item(job.item_id)
        except EngineError:
            return
        if item.status in (ItemStatus.PROCESSING, ItemStatus.QUEUED):
            if item.status == ItemStatus.QUEUED:
                self.repo.transition(item.id, ItemStatus.PROCESSING)
            self.repo.transition(item.id, ItemStatus.FAILED, error_code=code)
            self.notify("items.failed", {"item_id": item.id, "code": code})
