"""Engine composition root: wires stores, workers, and RPC handlers."""

from __future__ import annotations

import os
import platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omnirecall import __version__
from omnirecall.api import protocol
from omnirecall.api.server import RpcServer
from omnirecall.errors import EngineError

Notify = Callable[[str, dict[str, Any]], None]


class Engine:
    def __init__(self, data_dir: Path, models_dir: Path | None, notify: Notify) -> None:
        self.data_dir = data_dir
        self.models_dir = models_dir or data_dir / "models"
        self.notify = notify
        self.started_at = time.monotonic()
        self._server: RpcServer | None = None

    def register(self, server: RpcServer) -> None:
        self._server = server
        server.register("health", self.health)
        server.register("status", self.status)
        server.register("shutdown", self.shutdown)

    def health(self, params: dict[str, Any]) -> dict[str, Any]:
        client_version = params.get("protocol_version")
        if client_version is not None and client_version != protocol.PROTOCOL_VERSION:
            raise EngineError(
                "protocol_mismatch",
                "The app and engine versions do not match; reinstall OmniRecall",
                {"engine": protocol.PROTOCOL_VERSION, "client": client_version},
            )
        return {
            "ok": True,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "engine_version": __version__,
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - self.started_at, 3),
            "platform": platform.system().lower(),
        }

    def status(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"engine": "running", "uptime_s": round(time.monotonic() - self.started_at, 3)}

    def shutdown(self, _params: dict[str, Any]) -> dict[str, Any]:
        if self._server is not None:
            self._server.request_stop()
        return {"stopping": True}
