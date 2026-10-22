from __future__ import annotations

import time
from pathlib import Path

from support import HashEmbedder

from omnirecall.app import Engine


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, method: str, params: dict) -> None:
        self.events.append((method, params))


def make_engine(tmp_path: Path, embedder=None) -> tuple[Engine, Recorder]:
    recorder = Recorder()
    engine = Engine(tmp_path / "data", None, recorder, embedder=embedder or HashEmbedder())
    return engine, recorder


def wait_until(predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def wait_status(engine: Engine, item_id: str, statuses: set[str], timeout: float = 20.0) -> str:
    wait_until(lambda: engine.repo.get_item(item_id).status in statuses, timeout)
    return engine.repo.get_item(item_id).status
