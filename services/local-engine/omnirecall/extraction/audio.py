"""Audio decoding through the bundled `omnirecall-audio-decode` helper (D-031).

The helper is a small Rust program (services/audio-decoder) that turns one
local file into 16 kHz mono float samples, which is what Whisper expects.
It runs as a child process, like Tesseract, so a crash or a hostile file
cannot take the engine down, and it is stopped as soon as the engine stops
reading (cancellation). It opens only the named file and has no network code.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from omnirecall.errors import EngineError, LimitExceededError

SAMPLE_RATE = 16_000
DECODER_ENV = "OMNIRECALL_AUDIO_DECODER"
DECODER_NAME = "omnirecall-audio-decode"
PROBE_TIMEOUT_S = 30
# Error codes the helper reports, mapped to the engine's own (see errors.py).
_HELPER_CODES = {
    "unsupported_format",
    "unsupported_codec",
    "malformed_file",
    "extraction_empty",
    "source_missing",
    "limit_exceeded",
}


@dataclass(frozen=True)
class AudioInfo:
    duration_s: float | None
    sample_rate: int
    channels: int
    codec: str


class AudioDecoderUnavailableError(EngineError):
    def __init__(self) -> None:
        super().__init__(
            "audio_decoder_unavailable",
            "The audio decoder is missing from this installation; reinstall OmniRecall",
        )


def _helper_error(stderr: bytes, max_seconds: float | None = None) -> EngineError:
    """Turn the helper's one-line JSON error into an engine error with a fixed message."""
    code = "malformed_file"
    for line in reversed(stderr.decode("utf-8", errors="replace").splitlines()):
        try:
            reported = json.loads(line).get("code")
        except (json.JSONDecodeError, AttributeError):
            continue
        if reported in _HELPER_CODES:
            code = reported
        break
    if code == "limit_exceeded":
        return LimitExceededError("audio_duration", max_seconds or 0)
    messages = {
        "unsupported_format": "This audio file type is not supported",
        "unsupported_codec": "This audio encoding is not supported (for example Opus)",
        "malformed_file": "The audio file could not be decoded",
        "extraction_empty": "The audio file contains no sound",
        "source_missing": "The original file was moved or deleted",
    }
    return EngineError(code, messages[code])


class AudioDecoder:
    def __init__(self, command: str | None = None) -> None:
        self._command = command
        self._version: str | None = None
        self._lock = threading.Lock()

    def resolve(self) -> str | None:
        configured = self._command or os.environ.get(DECODER_ENV)
        if configured:
            return configured if Path(configured).is_file() else None
        name = DECODER_NAME + (".exe" if sys.platform == "win32" else "")
        # The packaged app ships the helper next to the engine executable.
        candidates = [Path(sys.executable).with_name(name)]
        if not getattr(sys, "frozen", False):
            # Running from source: the helper built in this checkout.
            services = Path(__file__).resolve().parents[3]
            candidates.append(services / "audio-decoder" / "target" / "release" / name)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return shutil.which(DECODER_NAME)

    def version(self) -> str | None:
        with self._lock:
            if self._version is None:
                command = self.resolve()
                if command is None:
                    return None
                try:
                    done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
                        [command, "--version"],
                        capture_output=True,
                        timeout=PROBE_TIMEOUT_S,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    return None
                if done.returncode != 0:
                    return None
                self._version = done.stdout.decode().strip() or "unknown"
            return self._version

    def available(self) -> bool:
        return self.version() is not None

    def _require(self) -> str:
        command = self.resolve()
        if command is None or not self.available():
            raise AudioDecoderUnavailableError()
        return command

    def probe(self, path: Path) -> AudioInfo:
        command = self._require()
        try:
            done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
                [command, "probe", str(path)],
                capture_output=True,
                timeout=PROBE_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError("malformed_file", "The audio file could not be read") from exc
        if done.returncode != 0:
            raise _helper_error(done.stderr)
        info: dict[str, Any] = json.loads(done.stdout)
        duration = info.get("duration_s")
        return AudioInfo(
            duration_s=float(duration) if duration is not None else None,
            sample_rate=int(info["sample_rate"]),
            channels=int(info["channels"]),
            codec=str(info["codec"]),
        )

    def stream(self, path: Path, max_seconds: float, block_s: float = 30.0) -> Iterator[np.ndarray]:
        """Yield 16 kHz mono float32 blocks; stops the helper when the caller stops."""
        command = self._require()
        block_bytes = int(block_s * SAMPLE_RATE) * 4
        proc = subprocess.Popen(  # noqa: S603 - fixed arguments, no shell
            [command, "decode", str(path), repr(float(max_seconds))],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdout and proc.stderr
        # Drain stderr on a thread so a chatty failure cannot block the pipe.
        errors: list[bytes] = []
        drain = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)  # type: ignore[union-attr]
        drain.start()
        finished = False
        try:
            leftover = b""
            while True:
                data = proc.stdout.read(block_bytes)
                if not data:
                    break
                data = leftover + data
                usable = len(data) - len(data) % 4
                leftover = data[usable:]
                if usable:
                    yield np.frombuffer(data[:usable], dtype="<f4").astype(np.float32)
            code = proc.wait()
            drain.join(timeout=5)
            finished = True
            if code != 0:
                raise _helper_error(b"".join(errors), max_seconds)
        finally:
            if not finished:
                proc.kill()
                proc.wait()
            proc.stdout.close()
