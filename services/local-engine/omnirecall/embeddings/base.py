"""Embedding interface shared by ingestion and query paths."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt

Vectors = npt.NDArray[np.float32]


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_tokens(self) -> int: ...

    def available(self) -> bool:
        """True when model files are installed and verified."""
        ...

    def loaded(self) -> bool: ...

    def count_tokens(self, text: str) -> int:
        """Token count including special tokens, without truncation."""
        ...

    def embed(self, texts: list[str]) -> Vectors:
        """L2-normalized float32 vectors, shape (len(texts), dimension)."""
        ...

    def unload_if_idle(self, idle_seconds: float) -> bool: ...


def vector_table_name(model_id: str, dimension: int) -> str:
    """LanceDB table per model and dimension (design.md §3 Storage)."""
    return f"chunks__{model_id}__{dimension}"
