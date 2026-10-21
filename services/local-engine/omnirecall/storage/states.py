"""Item lifecycle states and allowed transitions (design.md §10)."""

from __future__ import annotations

from enum import StrEnum

from omnirecall.errors import EngineError


class ItemStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DELETING = "deleting"
    DELETED = "deleted"


TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.QUEUED: frozenset({ItemStatus.PROCESSING, ItemStatus.SKIPPED, ItemStatus.DELETING}),
    ItemStatus.PROCESSING: frozenset(
        {ItemStatus.INDEXED, ItemStatus.FAILED, ItemStatus.SKIPPED, ItemStatus.DELETING}
    ),
    ItemStatus.INDEXED: frozenset({ItemStatus.PROCESSING, ItemStatus.DELETING}),
    ItemStatus.FAILED: frozenset({ItemStatus.QUEUED, ItemStatus.DELETING}),
    ItemStatus.SKIPPED: frozenset({ItemStatus.DELETING}),
    ItemStatus.DELETING: frozenset({ItemStatus.DELETED}),
    ItemStatus.DELETED: frozenset(),
}


class InvalidTransitionError(EngineError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            "invalid_state",
            "This action is not possible in the item's current state",
            {"from": current, "to": target},
        )


def check_transition(current: str, target: str) -> None:
    if ItemStatus(target) not in TRANSITIONS[ItemStatus(current)]:
        raise InvalidTransitionError(current, target)


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
