"""JSON-RPC 2.0 framing over newline-delimited stdio.

One JSON object per line. Requests arrive on stdin; responses and engine
notifications leave on stdout. Diagnostics never go to stdout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

# JSON-RPC reserved codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Application codes (-32000..-32099 are server errors per the spec).
APP_ERROR = -32000
PROTOCOL_MISMATCH = -32001


@dataclass(frozen=True)
class Request:
    id: int | str | None  # None means a notification: no response is sent.
    method: str
    params: dict[str, Any]


class ProtocolError(Exception):
    def __init__(self, code: int, message: str, request_id: int | str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


def parse_request(line: bytes) -> Request:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError(INVALID_REQUEST, "Message too large")
    try:
        payload = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProtocolError(PARSE_ERROR, "Parse error") from None
    if not isinstance(payload, dict):
        raise ProtocolError(INVALID_REQUEST, "Request must be an object")
    request_id = payload.get("id")
    if request_id is not None and (
        isinstance(request_id, bool) or not isinstance(request_id, int | str)
    ):
        raise ProtocolError(INVALID_REQUEST, "Invalid id")
    if payload.get("jsonrpc") != "2.0":
        raise ProtocolError(INVALID_REQUEST, "jsonrpc must be '2.0'", request_id)
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError(INVALID_REQUEST, "method must be a string", request_id)
    params = payload.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError(INVALID_PARAMS, "params must be an object", request_id)
    return Request(id=request_id, method=method, params=params)


def encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def result_message(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_message(
    request_id: int | str | None, code: int, message: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def notification_message(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}
