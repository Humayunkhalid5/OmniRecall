"""Network audit (Phase 3): the engine contacts nothing except a user-started model download.

Two checks:
- static: only ``models.py`` may import networking modules;
- runtime (Linux with strace): a full session (clipboard and screenshot capture,
  document and image import, search, export, delete) makes no
  ``connect``/``bind``/``sendto`` to an IP address, Tesseract included.

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
import uuid
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "omnirecall"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "images"
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


def test_onnxruntime_is_imported_only_with_telemetry_off():
    """ONNX Runtime uploads telemetry unless disabled before it loads (OR-023)."""
    importers = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] == "onnxruntime" for n in names):
                importers.append(path.relative_to(PACKAGE).as_posix())
    assert importers == ["embeddings/minilm.py"]
    source = (PACKAGE / "embeddings" / "minilm.py").read_text(encoding="utf-8")
    assert 'os.environ["ORT_DISABLE_TELEMETRY"] = "1"' in source
    assert "disable_telemetry_events()" in source
    server = (PACKAGE / "api" / "server.py").read_text(encoding="utf-8")
    assert 'os.environ["ORT_DISABLE_TELEMETRY"] = "1"' in server


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


def _session(
    proc: subprocess.Popen[bytes], export_path: Path, with_model: bool, data_dir: Path
) -> None:
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
    # OCR runs Tesseract as a child process, which strace -f follows too.
    image = FIXTURES / "chat_message.png"
    imported = call("items.import_paths", {"paths": [str(image)]})["item_ids"][0]
    call("capture.set_source", {"source_type": "screenshot", "enabled": True})
    if call("capture.screenshot_check", {"app_known": False})["allowed"]:
        name = f"shot-{uuid.uuid4().hex}.png"
        shutil.copy(image, data_dir / "media" / "incoming" / name)
        frame = {"file": name, "display_id": "audit", "width": 10, "height": 10}
        call("capture.screenshot", frame)
    if with_model:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            statuses = {
                call("items.get", {"item_id": i})["item"]["status"] for i in (pasted, imported)
            }
            if statuses == {"indexed"}:
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
            "trace=connect,bind,sendto,sendmsg,openat",
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
        _session(proc, tmp_path / "audit.zip", bool(models), tmp_path / "data")
        assert proc.wait(timeout=60) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    calls = trace.read_text().splitlines()
    ip_calls = [c for c in calls if re.search(r"AF_INET6?|sin6?_port", c)]
    assert ip_calls == []
    # Nothing is written outside the data folder and the source tree (bytecode),
    # such as a library's device ID or cache (OR-023).
    allowed = (str(tmp_path), str(PACKAGE.parents[2]), "/dev/", "/proc/")
    created = [
        m.group(1)
        for c in calls
        if "O_CREAT" in c and (m := re.search(r'openat\(AT_FDCWD, "([^"]+)"', c))
    ]
    stray = [p for p in created if p.startswith(str(Path.home())) and not p.startswith(allowed)]
    assert stray == []
    assert (tmp_path / "audit.zip").is_file()
