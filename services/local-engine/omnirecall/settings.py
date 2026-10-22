"""User-configurable settings with the design.md §11 defaults."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from omnirecall.ids import utc_now
from omnirecall.storage.db import Database

MB = 1024 * 1024


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # Limits
    max_file_bytes: int = Field(default=100 * MB, ge=1, le=2048 * MB)
    max_pdf_pages: int = Field(default=500, ge=1, le=10_000)
    max_audio_seconds: int = Field(default=2 * 3600, ge=1, le=12 * 3600)
    max_clipboard_bytes: int = Field(default=100 * 1024, ge=1, le=10 * MB)
    max_query_chars: int = Field(default=1000, ge=10, le=10_000)
    # Screenshot capture
    screenshot_interval_s: int = Field(default=30, ge=5, le=3600)
    screenshot_phash_threshold: int = Field(default=5, ge=0, le=32)
    pause_on_idle_s: int = Field(default=300, ge=0, le=24 * 3600)
    # Pipeline
    queue_capacity: int = Field(default=1000, ge=10, le=100_000)
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    job_max_retries: int = Field(default=3, ge=0, le=10)
    job_backoff_s: list[int] = Field(default_factory=lambda: [10, 60, 300])
    chunk_size: int = Field(default=500, ge=100, le=4000)
    chunk_overlap: int = Field(default=50, ge=0, le=1000)
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    model_idle_unload_s: int = Field(default=300, ge=10, le=24 * 3600)
    # Retrieval
    vector_top_k: int = Field(default=50, ge=1, le=1000)
    keyword_top_k: int = Field(default=50, ge=1, le=1000)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    results_shown: int = Field(default=20, ge=1, le=200)
    # Retention
    screenshot_retention_days: int = Field(default=7, ge=0, le=3650)
    media_cap_bytes: int = Field(default=5 * 1024 * MB, ge=0)
    text_only_mode: bool = False
    store_recent_searches: bool = False
    # Consent
    first_run_completed: bool = False


SETTINGS_KEY = "app"


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def load(self) -> Settings:
        row = self._db.conn.execute(
            "SELECT value_json FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
        if row is None:
            return Settings()
        stored = json.loads(row["value_json"])
        known = {k: v for k, v in stored.items() if k in Settings.model_fields}
        return Settings.model_validate(known)

    def update(self, changes: dict[str, Any]) -> Settings:
        """Validate and persist a partial update; unknown keys are rejected."""
        merged = self.load().model_dump() | changes
        settings = Settings.model_validate(merged)
        if settings.chunk_overlap >= settings.chunk_size:
            from omnirecall.errors import ValidationError

            raise ValidationError("Chunk overlap must be smaller than chunk size", "chunk_overlap")
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (SETTINGS_KEY, settings.model_dump_json(), utc_now()),
            )
        return settings
