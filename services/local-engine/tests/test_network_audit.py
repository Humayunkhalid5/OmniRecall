"""Network audit (Phase 3): the engine contacts nothing except a user-started model download.

Two checks:
- static: only ``models.py`` may import networking modules;
- runtime (Linux with strace): a full session (capture, import, search, export,
  delete) makes no ``connect``/``bind``/``sendto`` to an IP address.

Set ``OMNIRECALL_TEST_MODELS_DIR`` to a models folder to run the session with
the real embedding model, which also exercises ONNX Runtime and tokenizers.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "omnirecall"
NETWORK_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "websocket",
    "websockets",
    "huggingface_hub",
}
ALLOWED = {"models.py": {"urllib"}}


def test_only_model_setup_imports_network_modules():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in NETWORK_MODULES and root not in ALLOWED.get(path.name, set()):
                    offenders.append(f"{path.relative_to(PACKAGE)}: {name}")
    assert offenders == []


def _session(proc: subprocess.Popen[bytes], export_path: Path, with_model: bool) -> None:
    assert proc.stdin and proc.stdout
    counter = iter(range(1, 10_000))

    def call(method: str, params: dict) -> dict:
        msg_id = next(counter)
        line = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        proc.stdin.write(line.encode() + b"\n")
        proc.stdin.flush()
        while True:
            reply = json.loads(proc.stdout.readline())
            if reply.get("id") == msg_id:
                assert "error" not in reply, reply
                return reply["result"]

    call("health", {"protocol_version": 1})
    call("capture.set_source", {"source_type": "clipboard", "enabled": True})
    copied = call("capture.clipboard", {"text": "audit note about the harbor", "app_known": True})
    pasted = call("items.import_text", {"text": "audit text about otters"})["item"]["id"]
    if with_model:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if call("items.get", {"item_id": pasted})["item"]["status"] == "indexed":
                break
            time.sleep(0.2)
    call("search", {"query": "harbor otters"})
    call("status", {})
    call("export.create", {"path": str(export_path)})
    call("items.delete", {"item_id": copied["item_id"]})
    call("index.verify", {})
    call("shutdown", {})


@pytest.mark.timeout(180)
@pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("strace") is None,
    reason="syscall audit needs Linux and strace",
)
def test_engine_session_makes_no_network_calls(tmp_path):
    models = os.environ.get("OMNIRECALL_TEST_MODELS_DIR")
    trace = tmp_path / "net.trace"
    engine = [sys.executable, "-m", "omnirecall.api.server", "--data-dir", str(tmp_path / "data")]
    if models:
        engine += ["--models-dir", models]
    proc = subprocess.Popen(
        [
            "strace",
            "-f",
            "-qq",
            "-e",
            "trace=connect,bind,sendto,sendmsg",
            "-o",
            str(trace),
            *engine,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=PACKAGE.parent,
    )
    try:
        assert proc.stdout
        assert json.loads(proc.stdout.readline())["method"] == "engine.ready"
        _session(proc, tmp_path / "audit.zip", with_model=bool(models))
        assert proc.wait(timeout=60) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    calls = trace.read_text().splitlines()
    ip_calls = [c for c in calls if re.search(r"AF_INET6?|sin6?_port", c)]
    assert ip_calls == []
    assert (tmp_path / "audit.zip").is_file()
