"""Time adding new items to an existing library.

Usage: python scripts/bench_add.py <data_dir> [--items 500]

Run it on a copy of a data folder built by bench_search.py: it imports that
many new, unique text items and waits until every one is indexed and the
vector outbox is empty, then prints the rate and the peak resident memory
of the process. The texts are synthetic.
"""

from __future__ import annotations

import argparse
import random
import resource
import time
from pathlib import Path

from omnirecall.app import Engine

WORDS = [
    "tide",
    "harbor",
    "lantern",
    "keeper",
    "storm",
    "beacon",
    "granite",
    "gull",
    "ferry",
    "rope",
    "ledger",
    "signal",
    "island",
    "fog",
    "bell",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--items", type=int, default=500)
    args = parser.parse_args()
    engine = Engine(args.data_dir, None, lambda _method, _params: None)
    engine.startup_reconciled.wait(600)
    rng = random.Random(99)
    started = time.perf_counter()
    ids = [
        engine.import_text(
            {
                "text": " ".join(rng.choice(WORDS) for _ in range(70))
                + f" unique-{i}-{rng.random()}",
                "label": "bench",
            }
        )["item"]["id"]
        for i in range(args.items)
    ]
    while any(engine.repo.get_item(i).status != "indexed" for i in ids) or (
        engine.repo.pending_outbox(limit=1)
    ):
        time.sleep(0.2)
    elapsed = time.perf_counter() - started
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(
        f"{args.items} items in {elapsed:.1f} s = {args.items / elapsed:.1f} items/s; "
        f"peak_rss_mb={peak_mb:.0f}"
    )
    engine.close()


if __name__ == "__main__":
    main()
