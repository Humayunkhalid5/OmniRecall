"""all-MiniLM-L6-v2 via ONNX Runtime: mean pooling + L2 normalization.

Matches the sentence-transformers pipeline for this model (BertTokenizer,
lower-casing, max sequence 256, mean pooling over the attention mask,
normalize). Loaded on first use and unloaded after the idle timeout.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from omnirecall import logs
from omnirecall.embeddings.base import Vectors
from omnirecall.errors import ModelMissingError

MODEL_ID = "all-minilm-l6-v2"
DIMENSION = 384
MAX_TOKENS = 256


class MiniLMEmbedder:
    def __init__(self, model_dir: Path, threads: int = 2) -> None:
        self._model_dir = model_dir
        self._threads = threads
        self._lock = threading.Lock()
        self._session: Any = None
        self._tokenizer: Any = None
        self._counter: Any = None
        self._last_used = 0.0

    @property
    def model_id(self) -> str:
        return MODEL_ID

    @property
    def dimension(self) -> int:
        return DIMENSION

    @property
    def max_tokens(self) -> int:
        return MAX_TOKENS

    def available(self) -> bool:
        return (self._model_dir / "model.onnx").is_file() and (
            self._model_dir / "tokenizer.json"
        ).is_file()

    def loaded(self) -> bool:
        return self._session is not None

    def _ensure_tokenizers(self) -> None:
        if self._tokenizer is not None:
            return
        if not self.available():
            raise ModelMissingError(MODEL_ID)
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(self._model_dir / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=MAX_TOKENS)
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")  # noqa: S106 - token name, not a secret
        counter = Tokenizer.from_file(str(self._model_dir / "tokenizer.json"))
        counter.no_truncation()
        counter.no_padding()
        self._tokenizer = tokenizer
        self._counter = counter

    def _ensure_loaded(self) -> None:
        self._ensure_tokenizers()
        if self._session is not None:
            return
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = self._threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        started = time.monotonic()
        self._session = ort.InferenceSession(
            str(self._model_dir / "model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        logs.info(
            "model_loaded", model=MODEL_ID, duration_ms=round((time.monotonic() - started) * 1000)
        )

    def count_tokens(self, text: str) -> int:
        with self._lock:
            self._ensure_tokenizers()
            return len(self._counter.encode(text).ids)

    def embed(self, texts: list[str]) -> Vectors:
        if not texts:
            return np.zeros((0, DIMENSION), dtype=np.float32)
        with self._lock:
            self._ensure_loaded()
            self._last_used = time.monotonic()
            encodings = self._tokenizer.encode_batch(texts)
            input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
            attention = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            token_types = np.zeros_like(input_ids)
            (hidden,) = self._session.run(
                ["last_hidden_state"],
                {
                    "input_ids": input_ids,
                    "attention_mask": attention,
                    "token_type_ids": token_types,
                },
            )
        mask = attention[..., None].astype(np.float32)
        summed = (hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        pooled = summed / counts
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized: Vectors = (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)
        return normalized

    def unload_if_idle(self, idle_seconds: float) -> bool:
        with self._lock:
            if self._session is None or time.monotonic() - self._last_used < idle_seconds:
                return False
            self._session = None
        logs.info("model_unloaded", model=MODEL_ID)
        return True
