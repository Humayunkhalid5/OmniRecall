"""Relevance baseline on the labeled corpus with the real embedding model.

Usage: python scripts/eval_relevance.py <data_dir_with_models> [--mode hybrid|vector|keyword]
Reports recall@10 and MRR overall, for English, and for non-English queries.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path

from omnirecall.app import Engine

EVAL = Path(__file__).resolve().parents[1] / "services/local-engine/tests/fixtures/eval"


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (EVAL / name).read_text(encoding="utf-8").splitlines()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--mode", default="hybrid", choices=["hybrid", "vector", "keyword"])
    args = parser.parse_args()
    data = args.data_dir
    for sub in ("db", "vectors", "media"):
        shutil.rmtree(data / sub, ignore_errors=True)
    engine = Engine(data, None, lambda m, p: None)
    if not engine.embedder.available():
        sys.exit("embedding model not installed in <data_dir>/models")
    docs = load("corpus.jsonl")
    queries = load("queries.jsonl")
    item_to_doc = {}
    for doc in docs:
        out = engine.import_text({"text": doc["text"], "label": doc["title"]})
        item_to_doc[out["item"]["id"]] = doc["id"]
    deadline = time.time() + 300
    while engine.repo.status_counts().get("indexed", 0) < len(docs):
        if time.time() > deadline:
            sys.exit("indexing timed out")
        time.sleep(0.1)
    if args.mode == "vector":
        engine.search_service.repo.keyword_search = lambda q, k: []  # type: ignore[method-assign]
    if args.mode == "keyword":
        engine.search_service.embedder.available = lambda: False  # type: ignore[method-assign]
    rows = []
    latencies = []
    for q in queries:
        started = time.perf_counter()
        result = engine.search({"query": q["query"], "limit": 10})
        latencies.append((time.perf_counter() - started) * 1000)
        ranked = [item_to_doc[r["item_id"]] for r in result["results"]]
        expected = set(q["expected"])
        recall = len(expected & set(ranked[:10])) / len(expected)
        rr = next((1 / (i + 1) for i, d in enumerate(ranked) if d in expected), 0.0)
        top = result["results"][0] if result["results"] else None
        rows.append(
            {
                "id": q["id"],
                "lang": q["lang"],
                "kind": q["kind"],
                "recall10": recall,
                "rr": rr,
                "top_relevance": top["relevance"] if top else None,
                "top_correct": bool(top and item_to_doc[top["item_id"]] in expected),
                "top_similarity": top["similarity"] if top else None,
            }
        )
    engine.close()

    def summary(subset: list[dict]) -> str:
        if not subset:
            return "n=0"
        return (
            f"n={len(subset)} recall@10={statistics.mean(r['recall10'] for r in subset):.3f} "
            f"MRR={statistics.mean(r['rr'] for r in subset):.3f}"
        )

    print(f"mode={args.mode}")
    print("all      ", summary(rows))
    print("english  ", summary([r for r in rows if r["lang"] == "en"]))
    print("non-en   ", summary([r for r in rows if r["lang"] != "en"]))
    print("keyword  ", summary([r for r in rows if r["kind"] == "keyword"]))
    print("semantic ", summary([r for r in rows if r["kind"] == "semantic"]))
    lat = sorted(latencies)
    print(
        f"latency ms: median={statistics.median(lat):.1f} p95={lat[int(0.95 * (len(lat) - 1))]:.1f}"
    )
    for label in ("strong", "moderate", "weak"):
        group = [r for r in rows if r["top_relevance"] == label]
        if group:
            precision = sum(r["top_correct"] for r in group) / len(group)
            print(f"top result labeled {label:8s}: n={len(group)} correct={precision:.2f}")
    misses = [r["id"] for r in rows if r["rr"] == 0]
    print("queries with no relevant result:", misses)
    sims_ok = sorted(r["top_similarity"] for r in rows if r["top_correct"] and r["top_similarity"])
    sims_bad = sorted(
        r["top_similarity"] for r in rows if not r["top_correct"] and r["top_similarity"]
    )
    print("top similarity when correct:", [round(s, 2) for s in sims_ok][:8], "…")
    print("top similarity when wrong:  ", [round(s, 2) for s in sims_bad])


if __name__ == "__main__":
    main()
