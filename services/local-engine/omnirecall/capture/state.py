"""Capture source switches and pause state (PRD §4, §6).

Every source starts disabled. A source captures only when it is enabled, not
paused on its own, and capture is not paused globally. The shell asks for this
state before it reads anything, and the engine checks it again on every
capture, so either side alone is enough to stop capture.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from omnirecall.errors import SourceDisabledError, ValidationError
from omnirecall.settings import SettingsStore
from omnirecall.storage.repository import Repository

CAPTURE_SOURCES = ("clipboard", "screenshot")


class CaptureState:
    def __init__(
        self,
        repo: Repository,
        settings_store: SettingsStore,
        on_change: Callable[[dict[str, Any]], None],
    ) -> None:
        self.repo = repo
        self.settings_store = settings_store
        self._on_change = on_change
        self._lock = threading.Lock()

    def _source(self, source_type: str) -> tuple[bool, bool]:
        stored = self.repo.get_source(source_type)
        if stored is None:
            return False, False
        enabled, config = stored
        return enabled, bool(config.get("paused", False))

    def snapshot(self) -> dict[str, Any]:
        paused_all = self.settings_store.load().capture_paused
        sources = {}
        for source_type in CAPTURE_SOURCES:
            enabled, paused = self._source(source_type)
            sources[source_type] = {
                "enabled": enabled,
                "paused": paused,
                "active": enabled and not paused and not paused_all,
            }
        return {
            "paused": paused_all,
            "sources": sources,
            "capturing": any(s["active"] for s in sources.values()),
        }

    def is_active(self, source_type: str) -> bool:
        return bool(self.snapshot()["sources"].get(source_type, {}).get("active"))

    def require_active(self, source_type: str) -> None:
        if not self.is_active(source_type):
            raise SourceDisabledError(source_type)

    def set_source(
        self, source_type: str, enabled: bool | None = None, paused: bool | None = None
    ) -> dict[str, Any]:
        if source_type not in CAPTURE_SOURCES:
            raise ValidationError("Unknown capture source", "source_type")
        with self._lock:
            current_enabled, current_paused = self._source(source_type)
            new_enabled = current_enabled if enabled is None else enabled
            new_paused = current_paused if paused is None else paused
            if not new_enabled:
                new_paused = False  # A disabled source has nothing to pause.
            self.repo.upsert_source(source_type, new_enabled, {"paused": new_paused})
            state = self.snapshot()
        self._on_change(state)
        return state

    def set_paused(self, paused: bool) -> dict[str, Any]:
        with self._lock:
            self.settings_store.update({"capture_paused": paused})
            state = self.snapshot()
        self._on_change(state)
        return state
