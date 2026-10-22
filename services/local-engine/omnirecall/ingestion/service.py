"""Ingestion entry points: validate, deduplicate, persist, and queue (design.md §3)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omnirecall import logs
from omnirecall.errors import (
    EngineError,
    LimitExceededError,
    QueueFullError,
    UnsupportedFormatError,
    ValidationError,
)
from omnirecall.extraction.documents import format_for
from omnirecall.extraction.text import normalize_text
from omnirecall.ids import format_utc, sha256_file, sha256_text, utc_now
from omnirecall.settings import Settings
from omnirecall.storage.repository import Item, NewItem, Repository

MAX_FILES_PER_IMPORT = 10_000
TEXT_SOURCES = frozenset({"text", "clipboard"})


@dataclass
class ImportSummary:
    queued: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queued": len(self.queued),
            "duplicates": len(self.duplicates),
            "rejected": self.rejected,
            "item_ids": self.queued + self.duplicates,
        }


class IngestionService:
    def __init__(self, repo: Repository, media_root: Path, settings: Settings, wake: Any) -> None:
        self.repo = repo
        self.media_root = media_root
        self.settings = settings
        self._wake = wake

    def _check_capacity(self) -> None:
        if self.repo.active_job_count() >= self.settings.queue_capacity:
            raise QueueFullError()

    def import_text(
        self,
        text: str,
        source_type: str = "text",
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
        max_bytes: int | None = None,
    ) -> tuple[Item, bool]:
        if source_type not in TEXT_SOURCES:
            raise ValidationError("Unknown text source", "source_type")
        limit = max_bytes or self.settings.max_file_bytes
        if len(text.encode("utf-8")) > limit:
            raise LimitExceededError("text_size", limit)
        normalized = normalize_text(text)
        if not normalized:
            raise EngineError("extraction_empty", "There is no text to import")
        content_hash = sha256_text(normalized)
        existing = self.repo.find_by_hash(source_type, content_hash)
        if existing is not None and existing.status not in ("deleted",):
            return existing, False
        self._check_capacity()
        # The payload waits in app-owned media until the pipeline has chunked
        # it. It is written before the item exists so a worker never sees an
        # item without its payload.
        incoming = self.media_root / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        relative = f"incoming/{source_type}-{content_hash}.txt"
        payload = self.media_root / relative
        payload.write_text(normalized, encoding="utf-8")
        item, created = self.repo.create_item(
            NewItem(
                source_type=source_type,
                captured_at=utc_now(),
                content_hash=content_hash,
                source_label=(label or _default_label(normalized))[:200],
                media_uri=relative,
                metadata=(metadata or {}) | {"chars": len(normalized)},
            )
        )
        if created:
            self._wake()
        return item, created

    def import_paths(self, paths: list[str]) -> ImportSummary:
        summary = ImportSummary()
        files: list[Path] = []
        for raw in paths:
            path = Path(raw)
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                summary.rejected.append({"name": path.name, "code": "not_found"})
                continue
            if resolved.is_dir():
                files.extend(_walk_supported(resolved, summary))
            elif resolved.is_file():
                files.append(resolved)
            else:
                summary.rejected.append({"name": path.name, "code": "not_a_file"})
            if len(files) > MAX_FILES_PER_IMPORT:
                raise LimitExceededError("files_per_import", MAX_FILES_PER_IMPORT)
        for file_path in files:
            try:
                item, created = self.import_file(file_path)
            except EngineError as exc:
                summary.rejected.append({"name": file_path.name, "code": exc.code})
                continue
            (summary.queued if created else summary.duplicates).append(item.id)
        logs.info(
            "import_paths",
            count=len(summary.queued),
            reason=f"duplicates={len(summary.duplicates)} rejected={len(summary.rejected)}",
        )
        return summary

    def import_file(self, path: Path) -> tuple[Item, bool]:
        fmt = format_for(path)
        stat = path.stat()
        if stat.st_size > self.settings.max_file_bytes:
            raise LimitExceededError("file_size", self.settings.max_file_bytes)
        if stat.st_size == 0:
            raise EngineError("extraction_empty", "The file is empty")
        content_hash = sha256_file(path)
        existing = self.repo.find_by_hash("file", content_hash)
        if existing is not None:
            return existing, False
        self._check_capacity()
        item, created = self.repo.create_item(
            NewItem(
                source_type="file",
                captured_at=utc_now(),
                content_hash=content_hash,
                source_label=path.name[:200],
                source_uri=str(path),
                metadata={
                    "mime": fmt.mime,
                    "format": fmt.kind,
                    "bytes": stat.st_size,
                    "modified_at": format_utc(datetime.fromtimestamp(stat.st_mtime, UTC)),
                },
            )
        )
        if created:
            self._wake()
        return item, created


def _default_label(text: str) -> str:
    first_line = text.split("\n", 1)[0]
    return first_line[:80] + ("…" if len(first_line) > 80 else "")


def _walk_supported(root: Path, summary: ImportSummary) -> list[Path]:
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            candidate = Path(directory) / name
            try:
                format_for(candidate)
            except UnsupportedFormatError:
                continue
            if candidate.is_symlink():
                summary.rejected.append({"name": name, "code": "symlink_skipped"})
                continue
            found.append(candidate)
            if len(found) > MAX_FILES_PER_IMPORT:
                return found
    return found
