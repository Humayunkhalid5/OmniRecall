"""Identifier, hash, and timestamp formats (design.md §12)."""

from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from datetime import UTC, datetime

# Namespace for deterministic chunk IDs. Never change: chunk IDs derive from it.
CHUNK_NAMESPACE = uuid.UUID("6f6d6e69-7265-6361-6c6c-2d6368756e6b")

_uuid7_lock = threading.Lock()
_last_uuid7_ms = 0
_uuid7_seq = 0


def uuid7() -> str:
    """Return a time-sortable UUIDv7 string (RFC 9562).

    A 12-bit counter in rand_a keeps IDs monotonic within one millisecond.
    """
    global _last_uuid7_ms, _uuid7_seq
    with _uuid7_lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_uuid7_ms:
            _uuid7_seq += 1
            if _uuid7_seq > 0xFFF:
                _last_uuid7_ms += 1
                _uuid7_seq = 0
            ms = _last_uuid7_ms
        else:
            _last_uuid7_ms = ms
            _uuid7_seq = int.from_bytes(os.urandom(2), "big") & 0x3FF
        seq = _uuid7_seq
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= seq << 64
    value |= 0b10 << 62
    value |= rand_b
    return str(uuid.UUID(int=value))


def chunk_id(item_id: str, ordinal: int, chunker_version: str) -> str:
    """Deterministic chunk ID so retries never create duplicates."""
    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{item_id}:{ordinal}:{chunker_version}"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str], block_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def format_utc(moment: datetime) -> str:
    """ISO 8601 UTC with milliseconds, e.g. 2026-10-21T22:14:24.123Z."""
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def utc_now() -> str:
    return format_utc(datetime.now(UTC))


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
