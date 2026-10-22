"""Clipboard capture: filters a copied text before anything is persisted.

The shell watches the clipboard and sends each new text here. Copies that are
too large, excluded, or look like secrets are dropped without a trace in the
store: no item, no hash, no payload (D-022). Only per-session counts are kept,
so the user can see that filtering happened.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from typing import Any

from omnirecall import logs
from omnirecall.capture import sensitive
from omnirecall.capture.exclusions import ExclusionService
from omnirecall.capture.state import CaptureState
from omnirecall.errors import EngineError, LimitExceededError
from omnirecall.ingestion.service import IngestionService
from omnirecall.settings import Settings

SOURCE = "clipboard"


class ClipboardCapture:
    def __init__(
        self,
        state: CaptureState,
        exclusions: ExclusionService,
        ingestion: IngestionService,
        settings: Callable[[], Settings],
    ) -> None:
        self.state = state
        self.exclusions = exclusions
        self.ingestion = ingestion
        self._settings = settings
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def _record(self, outcome: str) -> dict[str, Any]:
        with self._lock:
            self._counts[outcome] += 1
        logs.info("clipboard_capture", status=outcome)
        return {"outcome": outcome}

    def capture(self, text: str, app: str | None, app_known: bool) -> dict[str, Any]:
        """Filter and store one copied text. Returns the outcome, never the text."""
        self.state.require_active(SOURCE)
        settings = self._settings()
        if len(text.encode("utf-8")) > settings.max_clipboard_bytes:
            return self._record("too_large")
        rules = self.exclusions.rules()
        if rules.apps and not app_known:
            # The owning app could not be determined, so an app exclusion
            # cannot be honoured. Fail closed.
            return self._record("app_unknown")
        if rules.app_excluded(app):
            return self._record("excluded_app")
        if rules.pattern_excluded(text):
            return self._record("excluded_pattern")
        if settings.clipboard_detect_secrets and sensitive.detect(text) is not None:
            return self._record("sensitive")
        metadata = {"app": app} if app else {}
        try:
            item, created = self.ingestion.import_text(
                text, SOURCE, None, metadata, settings.max_clipboard_bytes
            )
        except LimitExceededError:
            return self._record("too_large")
        except EngineError as exc:
            if exc.code == "extraction_empty":
                return self._record("empty")
            raise
        outcome = "captured" if created else "duplicate"
        return self._record(outcome) | {"item_id": item.id}
