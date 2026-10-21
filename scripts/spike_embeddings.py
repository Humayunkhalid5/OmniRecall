"""Phase 0 embedding spike: correctness sanity checks, latency, memory.

Usage: python scripts/spike_embeddings.py <model_dir>
"""

from __future__ import annotations

import resource
import sys
import time
from pathlib import Path

import numpy as np

from omnirecall.embeddings.minilm import MiniLMEmbedder


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    embedder = MiniLMEmbedder(Path(sys.argv[1]))
    base = rss_mb()
    start = time.perf_counter()
    vectors = embedder.embed(["warm up"])
    print(f"cold load+first embed: {(time.perf_counter() - start) * 1000:.0f} ms, rss {base:.0f}->{rss_mb():.0f} MB")
    assert vectors.shape == (1, 384), vectors.shape
    pairs = [
        ("A cat is sleeping on the mat", "A kitten naps on a rug", "high"),
        ("How do I fix a borrow of moved value error in Rust?", "error[E0382]: borrow of moved value", "high"),
        ("The quarterly review moved to Thursday", "Recipe for chocolate chip cookies", "low"),
        ("Photosynthesis happens in chloroplasts", "Stock market closed lower today", "low"),
    ]
    for a, b, expect in pairs:
        va, vb = embedder.embed([a, b])
        print(f"cos={float(va @ vb):.3f} expect={expect}: {a[:40]!r} vs {b[:40]!r}")
    norms = np.linalg.norm(embedder.embed(["x", "longer text here"]), axis=1)
    print("norms", norms)
    again = embedder.embed(["determinism check"])
    assert np.allclose(again, embedder.embed(["determinism check"]), atol=1e-6)
    chunk = ("Local-first search keeps personal context on device. " * 10)[:500]
    print("tokens in 500-char chunk:", embedder.count_tokens(chunk))
    batch = [chunk + str(i) for i in range(32)]
    for _ in range(2):
        start = time.perf_counter()
        embedder.embed(batch)
        print(f"batch of 32 x 500 chars: {(time.perf_counter() - start) * 1000:.0f} ms")
    start = time.perf_counter()
    embedder.embed(["what did I copy about the quarterly review"])
    print(f"single query embed: {(time.perf_counter() - start) * 1000:.1f} ms; peak rss {rss_mb():.0f} MB")


if __name__ == "__main__":
    main()
