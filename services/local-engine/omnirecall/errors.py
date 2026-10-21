"""Sanitized engine errors.

Every error carries a stable machine code and a fixed human message. Messages
never interpolate user content (queries, file text, paths).
"""

from __future__ import annotations

from typing import Any


class EngineError(Exception):
    """An expected, user-presentable failure."""

    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class ValidationError(EngineError):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__("invalid_params", message, {"field": field} if field else None)


class NotFoundError(EngineError):
    def __init__(self, what: str) -> None:
        super().__init__("not_found", f"{what} not found")


class ModelMissingError(EngineError):
    def __init__(self, model_id: str) -> None:
        super().__init__(
            "model_missing",
            "A required local model is not installed. Open Settings → Models to set it up.",
            {"model_id": model_id},
        )


class UnsupportedFormatError(EngineError):
    def __init__(self, kind: str) -> None:
        super().__init__("unsupported_format", "This file type is not supported", {"kind": kind})


class LimitExceededError(EngineError):
    def __init__(self, limit: str, maximum: int | float) -> None:
        super().__init__(
            "limit_exceeded", f"Input exceeds the {limit} limit", {"limit": limit, "max": maximum}
        )


class QueueFullError(EngineError):
    def __init__(self) -> None:
        super().__init__("queue_full", "The indexing queue is full; try again shortly")


class SourceDisabledError(EngineError):
    def __init__(self, source_type: str) -> None:
        super().__init__(
            "source_disabled",
            "This capture source is disabled or paused",
            {"source_type": source_type},
        )
