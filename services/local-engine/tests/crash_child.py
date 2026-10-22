"""Child process for fault-injection tests: runs a real engine and dies at a chosen point.

Usage: crash_child.py <data_dir> <scenario> [<module:Class.method> <before|after>]

The process ends with os._exit(CRASHED), like a power cut or a killed process:
no finally blocks, no atexit handlers, no SQLite or LanceDB cleanup.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from support import HashEmbedder

from omnirecall.app import Engine

CRASHED = 86
FAULT_NOT_HIT = 3


def install_fault(target: str, when: str) -> None:
    module_name, attr = target.split(":")
    owner_name, method_name = attr.split(".")
    owner = getattr(importlib.import_module(module_name), owner_name)
    original = getattr(owner, method_name)

    def crash(*args, **kwargs):
        if when == "before":
            os._exit(CRASHED)
        original(*args, **kwargs)
        os._exit(CRASHED)

    setattr(owner, method_name, crash)


def wait_for(engine: Engine, ids: list[str], statuses: set[str], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(engine.repo.get_item(i).status in statuses for i in ids):
            return
        time.sleep(0.05)
    raise SystemExit(FAULT_NOT_HIT)


def main() -> None:
    data_dir, scenario = Path(sys.argv[1]), sys.argv[2]
    texts = json.loads(os.environ["CRASH_TEXTS"])
    if len(sys.argv) > 3:
        install_fault(sys.argv[3], sys.argv[4])
    engine = Engine(data_dir, None, lambda _m, _p: None, embedder=HashEmbedder())
    if scenario == "index":
        ids = [engine.import_text({"text": t, "label": "note"})["item"]["id"] for t in texts]
        wait_for(engine, ids, {"indexed"})
    elif scenario == "delete":
        victim = os.environ["CRASH_VICTIM"]
        engine.delete_item({"item_id": victim})
        wait_for(engine, [victim], {"deleted"})
    elif scenario == "rebuild":
        engine.index_rebuild({})
        time.sleep(2)
    engine.close()
    # Reaching here means the fault point was never called.
    raise SystemExit(0 if len(sys.argv) == 3 else FAULT_NOT_HIT)


if __name__ == "__main__":
    main()
