"""Media retention (design.md §11, §13).

Screenshot images older than the retention period are removed; their OCR text
and chunks stay searchable and the item shows the media as ``pruned``. When
app-owned media exceeds the cap, the oldest media of any source is pruned
first. Text items are never pruned.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from omnirecall import logs
from omnirecall.ids import format_utc, parse_utc, utc_now
from omnirecall.settings import Settings
from omnirecall.storage.media import media_bytes, owned_media_path, remove_media
from omnirecall.storage.repository import Item, Repository

AGED_SOURCES = ["screenshot"]


@dataclass
class RetentionReport:
    pruned_by_age: int
    pruned_by_cap: int
    media_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "pruned_by_age": self.pruned_by_age,
            "pruned_by_cap": self.pruned_by_cap,
            "media_bytes": self.media_bytes,
        }


class RetentionService:
    def __init__(self, repo: Repository, media_root: Path, lock: threading.RLock) -> None:
        self.repo = repo
        self.media_root = media_root
        self.lock = lock

    def _prune(self, item: Item) -> None:
        path = owned_media_path(self.media_root, item.media_uri)
        if path is not None:
            remove_media(path)
        self.repo.set_media_status(item.id, "pruned", clear_uri=True)

    def _size(self, item: Item) -> int:
        path = owned_media_path(self.media_root, item.media_uri)
        return media_bytes(path) if path is not None else 0

    def usage(self) -> int:
        return sum(self._size(item) for item in self.repo.items_with_media())

    def run(self, settings: Settings, now: str | None = None) -> RetentionReport:
        with self.lock:
            current = parse_utc(now or utc_now())
            cutoff = format_utc(current - timedelta(days=settings.screenshot_retention_days))
            aged = self.repo.items_with_media(AGED_SOURCES, captured_before=cutoff)
            if settings.screenshot_retention_days == 0:
                aged = self.repo.items_with_media(AGED_SOURCES)
            for item in aged:
                self._prune(item)

            remaining = [(item, self._size(item)) for item in self.repo.items_with_media()]
            total = sum(size for _, size in remaining)
            by_cap = 0
            for item, size in remaining:
                if total <= settings.media_cap_bytes:
                    break
                self._prune(item)
                total -= size
                by_cap += 1
        if aged or by_cap:
            logs.info("retention_pruned", count=len(aged) + by_cap)
        return RetentionReport(len(aged), by_cap, total)
