"""Test-only helpers. Nothing here ships in the engine."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

from omnirecall.ids import chunk_id, sha256_text, utc_now
from omnirecall.storage.db import Database
from omnirecall.storage.repository import ChunkRow, NewItem, Repository
from omnirecall.storage.vectors import VectorStore

DIM = 384
_WORD = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    """Deterministic bag-of-words embedder for unit tests (no model files)."""

    model_id = "test-hash"
    dimension = DIM
    max_tokens = 256

    def __init__(self) -> None:
        self.calls = 0
        self.texts_embedded = 0

    def available(self) -> bool:
        return True

    def loaded(self) -> bool:
        return True

    def count_tokens(self, text: str) -> int:
        return len(_WORD.findall(text.lower())) + 2

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        self.texts_embedded += len(texts)
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.lower()):
                digest = hashlib.sha256(word.encode()).digest()
                out[row, int.from_bytes(digest[:4], "big") % DIM] += 1.0
            norm = np.linalg.norm(out[row])
            out[row] = out[row] / norm if norm else out[row]
            if not norm:
                out[row, 0] = 1.0
        return out

    def unload_if_idle(self, idle_seconds: float) -> bool:
        return False


def make_stores(tmp_path: Path) -> tuple[Database, Repository, VectorStore, HashEmbedder]:
    db = Database(tmp_path / "db" / "omnirecall.sqlite")
    db.migrate()
    repo = Repository(db)
    embedder = HashEmbedder()
    vectors = VectorStore(
        tmp_path / "vectors", f"chunks__{embedder.model_id}__{DIM}", DIM, embedder.model_id
    )
    return db, repo, vectors, embedder


def new_text_item(repo: Repository, text: str, label: str = "note") -> str:
    item, _ = repo.create_item(
        NewItem(
            source_type="text",
            captured_at=utc_now(),
            content_hash=sha256_text(text),
            source_label=label,
        )
    )
    return item.id


def simple_chunks(item_id: str, text: str, size: int = 80) -> list[ChunkRow]:
    rows = []
    for ordinal, start in enumerate(range(0, len(text), size)):
        piece = text[start : start + size]
        rows.append(
            ChunkRow(
                id=chunk_id(item_id, ordinal, "test-v1"),
                item_id=item_id,
                ordinal=ordinal,
                text=piece,
                start_offset=start,
                end_offset=start + len(piece),
                text_hash=sha256_text(piece),
                chunker_version="test-v1",
                embedding_model="test-hash",
            )
        )
    return rows
