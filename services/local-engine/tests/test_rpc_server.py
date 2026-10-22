"""JSON-RPC stdio framing and dispatch."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from omnirecall.api import protocol
from omnirecall.api.server import RpcServer
from omnirecall.errors import EngineError


def run_server(lines: list[bytes], register=None) -> list[dict]:
    stdin = io.BytesIO(b"".join(lines))
    stdout = io.BytesIO()
    server = RpcServer(stdin, stdout, max_workers=2)
    if register:
        register(server)
    server.serve()
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def req(id_, method, params=None) -> bytes:
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return json.dumps(body).encode() + b"\n"


def test_round_trip_and_unknown_method():
    def register(server):
        server.register("echo", lambda p: p)

    out = run_server([req(1, "echo", {"a": 1}), req(2, "missing")], register)
    by_id = {m["id"]: m for m in out}
    assert by_id[1]["result"] == {"a": 1}
    assert by_id[2]["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_parse_errors_do_not_stop_the_server():
    def register(server):
        server.register("ping", lambda p: "pong")

    out = run_server(
        [b"{not json\n", b"[1,2]\n", b'{"jsonrpc":"1.0","id":5,"method":"x"}\n', req(9, "ping")],
        register,
    )
    codes = [m.get("error", {}).get("code") for m in out]
    assert protocol.PARSE_ERROR in codes
    assert protocol.INVALID_REQUEST in codes
    assert any(m.get("result") == "pong" for m in out)


def test_params_must_be_object():
    out = run_server([b'{"jsonrpc":"2.0","id":1,"method":"x","params":[1]}\n'])
    assert out[0]["error"]["code"] == protocol.INVALID_PARAMS


def test_engine_error_is_sanitized_and_internal_errors_hidden():
    def boom(_p):
        raise RuntimeError("secret content /home/user/private.txt")

    def expected(_p):
        raise EngineError("not_found", "Item not found")

    def register(server):
        server.register("boom", boom)
        server.register("expected", expected)

    out = {m["id"]: m for m in run_server([req(1, "boom"), req(2, "expected")], register)}
    assert out[1]["error"] == {
        "code": protocol.INTERNAL_ERROR,
        "message": "Internal error",
        "data": {"code": "internal"},
    }
    assert "secret" not in json.dumps(out[1])
    assert out[2]["error"]["data"]["code"] == "not_found"


def test_notifications_get_no_response():
    calls = []

    def register(server):
        server.register("note", lambda p: calls.append(p))

    out = run_server([b'{"jsonrpc":"2.0","method":"note","params":{"x":1}}\n'], register)
    assert out == []
    assert calls == [{"x": 1}]


def test_oversized_message_rejected(monkeypatch):
    monkeypatch.setattr(protocol, "MAX_MESSAGE_BYTES", 64)

    def register(server):
        server.register("ping", lambda p: "pong")

    big = req(1, "ping", {"pad": "x" * 500})
    out = run_server([big, req(2, "ping")], register)
    assert out[0]["error"]["code"] == protocol.INVALID_REQUEST
    assert out[1]["result"] == "pong"


ENGINE_CMD = [sys.executable, "-m", "omnirecall.api.server"]


def spawn_engine(tmp_path: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [*ENGINE_CMD, "--data-dir", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[1],
    )


@pytest.mark.timeout(60)
def test_real_engine_handshake_and_graceful_shutdown(tmp_path):
    proc = spawn_engine(tmp_path)
    assert proc.stdin and proc.stdout
    ready = json.loads(proc.stdout.readline())
    assert ready["method"] == "engine.ready"
    proc.stdin.write(req(1, "health", {"protocol_version": protocol.PROTOCOL_VERSION}))
    proc.stdin.flush()
    health = json.loads(proc.stdout.readline())
    assert health["result"]["ok"] is True
    proc.stdin.write(req(2, "health", {"protocol_version": 999}))
    proc.stdin.flush()
    mismatch = json.loads(proc.stdout.readline())
    assert mismatch["error"]["code"] == protocol.PROTOCOL_MISMATCH
    proc.stdin.close()  # EOF → graceful stop
    assert proc.wait(timeout=30) == 0


@pytest.mark.timeout(60)
@pytest.mark.skipif(os.name == "nt", reason="SIGTERM semantics differ on Windows")
def test_real_engine_stops_on_sigterm(tmp_path):
    proc = spawn_engine(tmp_path)
    assert proc.stdout
    proc.stdout.readline()
    time.sleep(0.2)
    proc.terminate()
    assert proc.wait(timeout=30) == 0


@pytest.mark.timeout(60)
@pytest.mark.skipif(os.name == "nt", reason="the shell closes stdin after shutdown on Windows")
def test_real_engine_exits_on_shutdown_request_with_stdin_open(tmp_path):
    proc = spawn_engine(tmp_path)
    assert proc.stdin and proc.stdout
    proc.stdout.readline()
    proc.stdin.write(req(1, "shutdown", {}))
    proc.stdin.flush()
    assert json.loads(proc.stdout.readline())["result"] == {"stopping": True}
    assert proc.wait(timeout=30) == 0  # stdin deliberately left open


def test_engine_opens_no_network_port(tmp_path):
    """The engine must not listen on any socket (D-003)."""
    psutil = pytest.importorskip("psutil")
    proc = spawn_engine(tmp_path)
    try:
        assert proc.stdout
        proc.stdout.readline()
        connections = psutil.Process(proc.pid).net_connections(kind="inet")
        assert connections == []
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.timeout(60)
@pytest.mark.skipif(os.name == "nt", reason="the shell closes stdin after shutdown on Windows")
def test_requests_in_flight_at_shutdown_are_answered(tmp_path):
    """OR-022: a request finishing after `shutdown` must not signal the engine again."""
    proc = spawn_engine(tmp_path)
    assert proc.stdin and proc.stdout
    proc.stdout.readline()
    enable = {"source_type": "clipboard", "enabled": True}
    batch = b"".join(req(i, "capture.set_source", enable) for i in range(1, 7))
    proc.stdin.write(batch + req(7, "shutdown", {}))
    proc.stdin.flush()
    # stdin stays open; the little output fits in the pipe buffers.
    assert proc.wait(timeout=30) == 0
    assert proc.stderr
    replies = [json.loads(line) for line in proc.stdout.read().splitlines()]
    assert {r.get("id") for r in replies} >= set(range(1, 8))
    assert b"Traceback" not in proc.stderr.read()
