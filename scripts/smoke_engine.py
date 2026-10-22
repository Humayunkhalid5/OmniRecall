"""Smoke test of a packaged engine: it starts, finds its helpers, indexes, and exits.

Usage: python scripts/smoke_engine.py <omnirecall-engine[.exe]> [--require-ocr]
       [--models-dir DIR | --download-model]

Runs the frozen executable on an empty data folder, the way the app does, over
JSON-RPC on stdio. Without a model an item stops at `model_missing`, which
still shows extraction and chunking ran. With the model (an existing folder, or
downloaded through the engine's own verified download), the item must be found.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROTOCOL_VERSION = 1


class Engine:
    def __init__(self, exe: Path, data: Path, models: Path | None) -> None:
        extra = ["--models-dir", str(models)] if models else []
        self.proc = subprocess.Popen(
            [str(exe), "--data-dir", str(data), *extra],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.next_id = 0
        ready = self._read()
        if ready.get("method") != "engine.ready":
            raise SystemExit(f"unexpected first message: {ready}")

    def _read(self) -> dict:
        assert self.proc.stdout
        line = self.proc.stdout.readline()
        if not line:
            assert self.proc.stderr
            raise SystemExit(
                "engine exited:\n" + self.proc.stderr.read().decode()[-4000:]
            )
        return json.loads(line)

    def call(self, method: str, params: dict | None = None) -> dict:
        assert self.proc.stdin
        self.next_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": method,
            "params": params or {},
        }
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
        self.proc.stdin.flush()
        while True:
            reply = self._read()
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise SystemExit(f"{method} failed: {reply['error']}")
                return reply["result"]

    def stop(self) -> int:
        assert self.proc.stdin
        self.proc.stdin.close()
        return self.proc.wait(timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("--require-ocr", action="store_true")
    model = parser.add_mutually_exclusive_group()
    model.add_argument("--models-dir", type=Path)
    model.add_argument("--download-model", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        started = time.perf_counter()
        models = args.models_dir.resolve() if args.models_dir else None
        engine = Engine(args.exe.resolve(), Path(tmp) / "data", models)
        health = engine.call("health", {"protocol_version": PROTOCOL_VERSION})
        start_ms = (time.perf_counter() - started) * 1000
        status = engine.call("status")
        capture = engine.call("capture.state")
        formats = engine.call("formats.list")
        if args.download_model:
            engine.call("models.download", {"model_id": "all-minilm-l6-v2"})
            deadline = time.monotonic() + 600
            while (
                time.monotonic() < deadline
                and not engine.call("status")["model"]["installed"]
            ):
                time.sleep(1)
        with_model = engine.call("status")["model"]["installed"]
        item = engine.call(
            "items.import_text", {"text": "Smoke test: the lighthouse keeper logs"}
        )
        item_id = item["item"]["id"]
        deadline = time.monotonic() + 120
        found: list[dict] = []
        detail: dict = {}
        while time.monotonic() < deadline and not found:
            detail = engine.call("items.get", {"item_id": item_id})["item"]
            if not with_model and detail["status"] == "failed":
                break
            found = [
                r
                for r in engine.call("search", {"query": "lighthouse keeper"})[
                    "results"
                ]
                if r["item_id"] == item_id
            ]
            time.sleep(0.25)
        code = engine.stop()

    checks = {
        "health ok": health["ok"],
        "normal engine": status["engine"] != "recovery",
        "audio decoder bundled": status["transcription"]["decoder_available"],
        "OCR available": capture["ocr"]["available"] or not args.require_ocr,
        "formats listed": bool(formats["documents"]),
        "search finds the item" if with_model else "item waits for the model": bool(
            found
        )
        if with_model
        else detail.get("error_code") == "model_missing",
        "clean exit": code == 0,
    }
    print(
        f"engine {health['engine_version']} on {health['platform']}: ready in {start_ms:.0f} ms"
    )
    print(f"OCR: {capture['ocr']}; model installed: {with_model}")
    for name, ok in checks.items():
        print(f"{'ok ' if ok else 'FAIL'} {name}")
    if not all(checks.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
