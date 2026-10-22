"""Known-vector regression for the real MiniLM model (OR-007).

`fixtures/known_vectors.json` holds vectors the pinned model and tokenizer
produced for three sentences. A change to tokenization, truncation, pooling,
normalization, or the ONNX Runtime build that moves them fails here, before
it can silently degrade search. Runs when OMNIRECALL_TEST_MODELS_DIR has the
model (the `Real models` CI job).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from omnirecall.embeddings.minilm import MODEL_ID, MiniLMEmbedder

FIXTURE = Path(__file__).parent / "fixtures" / "known_vectors.json"
MODEL_DIR = Path(os.environ.get("OMNIRECALL_TEST_MODELS_DIR", "/nonexistent")) / MODEL_ID

pytestmark = pytest.mark.skipif(
    not MODEL_DIR.is_dir(), reason="real MiniLM model not installed (OMNIRECALL_TEST_MODELS_DIR)"
)


def test_model_reproduces_known_vectors():
    known = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert known["model_id"] == MODEL_ID
    embedder = MiniLMEmbedder(MODEL_DIR)
    vectors = embedder.embed(known["sentences"])
    expected = np.asarray(known["vectors"], dtype=np.float32)
    assert vectors.shape == expected.shape == (3, 384)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    # Different CPUs round differently in the last bits; anything larger is a change.
    cosines = (vectors * expected).sum(axis=1)
    assert cosines.min() > 0.9999, cosines
    np.testing.assert_allclose(vectors, expected, atol=2e-3)


def test_paraphrase_is_nearer_than_an_unrelated_sentence():
    embedder = MiniLMEmbedder(MODEL_DIR)
    meeting, paraphrase, recipe = embedder.embed(
        [
            "The quarterly review moved to Thursday at 3pm.",
            "When is the quarterly review meeting now?",
            "Preheat the oven to 180 degrees and bake for forty minutes.",
        ]
    )
    assert float(meeting @ paraphrase) > float(meeting @ recipe) + 0.3
