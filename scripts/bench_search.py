"""Search latency at N chunks with the real embedding model.

Usage: python scripts/bench_search.py <data_dir_with_models> --chunks 10000
Builds a deterministic synthetic corpus (sentences recombined from the
evaluation corpus with a fixed seed), indexes it, then times the labeled
queries end to end through Engine.search.
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import shutil
import statistics
import sys
import time
from pathlib import Path

from omnirecall.app import Engine
from omnirecall.storage.salvage import check

EVAL = Path(__file__).resolve().parents[1] / "services/local-engine/tests/fixtures/eval"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--chunks", type=int, default=10_000)
    parser.add_argument("--keep", action="store_true", help="reuse an existing index of this size")
    args = parser.parse_args()
    data = args.data_dir
    if not args.keep:
        for sub in ("db", "vectors", "media"):
            shutil.rmtree(data / sub, ignore_errors=True)
    docs = [
        json.loads(line)
        for line in (EVAL / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    queries = [
        json.loads(line)["query"]
        for line in (EVAL / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    sentences = [s.strip() + "." for d in docs for s in d["text"].split(".") if len(s.strip()) > 20]
    rng = random.Random(1234)  # noqa: S311 - synthetic benchmark text
    engine = Engine(data, None, lambda m, p: None)
    if not engine.embedder.available():
        sys.exit("embedding model not installed")
    started = time.perf_counter()
    if engine.repo.chunk_count() < args.chunks:
        # ~430 chars per document → one chunk each with the 500-char baseline.
        # Counted once: counting the whole library on every import made the
        # benchmark itself the bottleneck at 100,000 chunks.
        have = engine.repo.status_counts().get("queued", 0) + engine.repo.chunk_count()
        for index in range(args.chunks - have):
            body = " ".join(rng.sample(sentences, 3)) + f" Reference {index:06d}."
            engine.import_text({"text": body[:480], "label": f"synthetic {index}"})
            if engine.repo.backlog_count() > 900:
                time.sleep(0.5)
        while engine.repo.active_job_count() > 0 or engine.repo.pending_outbox(limit=1):
            time.sleep(0.5)
        while set(engine.repo.status_counts()) - {"indexed"}:
            time.sleep(0.5)
    index_s = time.perf_counter() - started
    chunks = engine.repo.chunk_count()
    for q in queries[:5]:  # warm-up
        engine.search({"query": q})
    latencies = []
    for _ in range(3):
        for q in queries:
            t = time.perf_counter()
            engine.search({"query": q})
            latencies.append((time.perf_counter() - t) * 1000)
    lat = sorted(latencies)
    p95 = lat[int(0.95 * (len(lat) - 1))]
    status = engine.status({})
    engine.close()
    print(f"chunks={chunks} vectors={status['index']['vectors']} indexing_s={index_s:.0f}")
    print(
        f"queries={len(lat)} median_ms={statistics.median(lat):.1f} p95_ms={p95:.1f} max_ms={lat[-1]:.1f}"
    )
    print(
        f"db_bytes={status['storage']['db_bytes']} vector_bytes={status['storage']['vector_bytes']}"
    )
    print(f"peak_rss_mb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}")

    # Startup cost at this size: the integrity check (D-036), then a full start.
    t = time.perf_counter()
    damage = check(data / "db" / "omnirecall.sqlite")
    check_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    engine = Engine(data, None, lambda m, p: None)
    start_ms = (time.perf_counter() - t) * 1000
    engine.startup_reconciled.wait(600)
    reconcile_s = time.perf_counter() - t
    engine.close()
    print(
        f"startup_check_ms={check_ms:.0f} damage={damage} engine_init_ms={start_ms:.0f} "
        f"startup_reconcile_s={reconcile_s:.1f}"
    )


if __name__ == "__main__":
    main()
