"""Stdio JSON-RPC server: reads requests from stdin, writes responses to stdout.

The engine opens no network port (design.md §2, D-003).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError as PydanticValidationError

from omnirecall import logs
from omnirecall.api import protocol
from omnirecall.errors import EngineError

Handler = Callable[[dict[str, Any]], Any]


class RpcServer:
    """Dispatches JSON-RPC requests to registered handlers on a thread pool.

    Handlers run concurrently so a long import never blocks `search` or
    `status`. Output writes are serialized by a lock so lines never interleave.
    """

    def __init__(self, stdin: BinaryIO, stdout: BinaryIO, max_workers: int = 4) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._write_lock = threading.Lock()
        self._interrupted = False
        self._handlers: dict[str, Handler] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rpc")
        self._stopping = threading.Event()
        self._shutdown_hooks: list[Callable[[], None]] = []
        # Unblocks the stdin read after a `shutdown` request has been answered.
        self.interrupt: Callable[[], None] | None = None

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        self._shutdown_hooks.append(hook)

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send an engine → shell notification (progress, status changes)."""
        self._write(protocol.notification_message(method, params))

    def request_stop(self) -> None:
        self._stopping.set()

    def _interrupt_once(self) -> None:
        """Wake the blocking read once; later requests finishing must not signal again."""
        with self._write_lock:
            if self._interrupted or self.interrupt is None:
                return
            self._interrupted = True
        self.interrupt()

    def _write(self, message: dict[str, Any]) -> None:
        data = protocol.encode(message)
        with self._write_lock:
            try:
                self._stdout.write(data)
                self._stdout.flush()
            except (BrokenPipeError, ValueError):
                # The shell went away; stop instead of spinning.
                self._stopping.set()

    def _dispatch(self, request: protocol.Request) -> None:
        started = time.monotonic()
        handler = self._handlers.get(request.method)
        if handler is None:
            if request.id is not None:
                self._write(
                    protocol.error_message(
                        request.id, protocol.METHOD_NOT_FOUND, "Method not found"
                    )
                )
            return
        try:
            result = handler(request.params)
            if request.id is not None:
                self._write(protocol.result_message(request.id, result))
            if self._stopping.is_set():
                self._interrupt_once()
        except EngineError as exc:
            code = protocol.INVALID_PARAMS if exc.code == "invalid_params" else protocol.APP_ERROR
            if exc.code == "protocol_mismatch":
                code = protocol.PROTOCOL_MISMATCH
            logs.info("rpc_error", method=request.method, code=exc.code)
            if request.id is not None:
                self._write(
                    protocol.error_message(
                        request.id, code, exc.message, {"code": exc.code, **exc.data}
                    )
                )
        except PydanticValidationError as exc:
            fields = [".".join(str(p) for p in err["loc"]) for err in exc.errors()]
            logs.info("rpc_invalid_params", method=request.method, count=len(fields))
            if request.id is not None:
                self._write(
                    protocol.error_message(
                        request.id,
                        protocol.INVALID_PARAMS,
                        "Invalid parameters",
                        {"code": "invalid_params", "fields": fields},
                    )
                )
        except Exception as exc:  # noqa: BLE001 - last-resort guard keeps the engine alive
            logs.error("rpc_internal_error", method=request.method, reason=type(exc).__name__)
            if request.id is not None:
                self._write(
                    protocol.error_message(
                        request.id, protocol.INTERNAL_ERROR, "Internal error", {"code": "internal"}
                    )
                )
        finally:
            logs.debug(
                "rpc_done",
                method=request.method,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )

    def serve(self) -> None:
        """Read until EOF or a stop request, then run shutdown hooks."""
        try:
            while not self._stopping.is_set():
                line = self._stdin.readline(protocol.MAX_MESSAGE_BYTES + 1)
                if not line:
                    break  # EOF: the shell closed our stdin.
                if len(line) > protocol.MAX_MESSAGE_BYTES and not line.endswith(b"\n"):
                    self._drain_line()
                    self._write(
                        protocol.error_message(None, protocol.INVALID_REQUEST, "Message too large")
                    )
                    continue
                if not line.strip():
                    continue
                try:
                    request = protocol.parse_request(line)
                except protocol.ProtocolError as exc:
                    self._write(protocol.error_message(exc.request_id, exc.code, exc.message))
                    continue
                self._pool.submit(self._dispatch, request)
        finally:
            self.shutdown()

    def _drain_line(self) -> None:
        while True:
            chunk = self._stdin.readline(protocol.MAX_MESSAGE_BYTES)
            if not chunk or chunk.endswith(b"\n"):
                return

    def shutdown(self) -> None:
        self._stopping.set()
        self._pool.shutdown(wait=True, cancel_futures=False)
        for hook in reversed(self._shutdown_hooks):
            try:
                hook()
            except Exception as exc:  # noqa: BLE001 - keep running remaining hooks
                logs.error("shutdown_hook_failed", reason=type(exc).__name__)
        self._shutdown_hooks.clear()


class _StopSignal(BaseException):
    """Raised from a signal handler to unwind the blocking read loop."""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omnirecall-engine")
    parser.add_argument(
        "--data-dir", required=True, help="App data directory (resolved by the shell)"
    )
    parser.add_argument(
        "--models-dir", default=None, help="Model directory (default: <data-dir>/models)"
    )
    parser.add_argument(
        "--log-level", default="info", choices=["debug", "info", "warning", "error"]
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Defense in depth: transitive libraries (huggingface-hub via tokenizers)
    # can download files. The engine never asks them to; this forbids it.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"  # ONNX Runtime uploads telemetry otherwise (OR-023)
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data_dir).expanduser().resolve()
    logs.configure(data_dir / "logs", args.log_level)

    from omnirecall.app import Engine  # local import keeps `--help` fast
    from omnirecall.recovery import DB_NAME, RecoveryEngine
    from omnirecall.storage.salvage import check

    server = RpcServer(sys.stdin.buffer, sys.stdout.buffer)
    engine: Engine | RecoveryEngine
    damage = check(data_dir / "db" / DB_NAME)
    if damage is None:
        try:
            engine = Engine(
                data_dir=data_dir,
                models_dir=Path(args.models_dir).resolve() if args.models_dir else None,
                notify=server.notify,
            )
        except sqlite3.DatabaseError:
            # Only damage found by the check leads to recovery. A locked or full
            # disk is not damage, and offering to reset would be wrong.
            damage = check(data_dir / "db" / DB_NAME)
            if damage is None:
                raise
        except EngineError as exc:
            if exc.code != "schema_too_new":
                raise
            damage = "schema_too_new"  # made by a newer version: no action offered
    if damage is not None:
        # Serve only the repair calls; the app shows the choice (D-036).
        logs.error("database_damaged", reason=damage)
        engine = RecoveryEngine(data_dir, damage)
    engine.register(server)

    signalled = threading.Event()

    def _on_signal(signum: int, _frame: object) -> None:
        if signalled.is_set():
            return  # already unwinding; a second exception would break shutdown
        signalled.set()
        logs.info("signal", code=str(signum))
        server.request_stop()
        # Interrupt the blocking stdin read; serve() runs shutdown in finally.
        raise _StopSignal

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    main_ident = threading.main_thread().ident
    if hasattr(signal, "pthread_kill") and main_ident is not None:
        # Deliver to the main thread so its blocking read is interrupted. On
        # Windows the shell closes stdin after `shutdown`, which ends the read.
        server.interrupt = lambda: signal.pthread_kill(main_ident, signal.SIGTERM)

    logs.info("engine_start", pid=os.getpid(), version=str(protocol.PROTOCOL_VERSION))
    server.notify(
        "engine.ready", {"protocol_version": protocol.PROTOCOL_VERSION, "pid": os.getpid()}
    )
    with contextlib.suppress(_StopSignal):
        server.serve()
    logs.info("engine_stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
