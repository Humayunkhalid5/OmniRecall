"""Local speech-to-text behind a replaceable adapter (design.md §3, D-014).

The Whisper model is loaded only from its verified local file, never by name
(pywhispercpp downloads models given by name). whisper.cpp's own log output
is switched off, so no transcript text reaches a log or the console.

Long recordings are transcribed in windows of a few minutes, split at the
quietest moment near each boundary, so memory stays flat for a two-hour file
and cancellation takes effect within a window.
"""

from __future__ import annotations

import atexit
import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from omnirecall import logs
from omnirecall.extraction.audio import SAMPLE_RATE
from omnirecall.extraction.transcript import Segment

WINDOW_S = 300
# Where in the last seconds of a window to look for a pause to split at.
SPLIT_SEARCH_S = 10
SPLIT_FRAME_S = 0.1
MIN_AUDIO_S = 0.1
# 1 is greedy decoding; above 1, whisper.cpp keeps that many beams per step.
BEAM_SIZE = 1

OnSegment = Callable[[Segment], None]
ShouldAbort = Callable[[], bool]


def _discard_log(*_args: Any) -> None:
    """whisper.cpp log sink. Module level, so it outlives every model."""


class TranscriptionAbortedError(Exception):
    """The caller asked to stop (cancel, delete, or shutdown)."""


@dataclass
class WindowResult:
    segments: list[Segment]
    language: str | None = None


class Transcriber(Protocol):
    name: str
    model_id: str

    def available(self) -> bool: ...

    def loaded(self) -> bool: ...

    def transcribe(
        self,
        samples: np.ndarray,
        offset_ms: int,
        on_segment: OnSegment,
        should_abort: ShouldAbort,
    ) -> WindowResult: ...

    def unload_if_idle(self, idle_s: float) -> None: ...

    def close(self) -> None: ...


@dataclass
class TranscriptResult:
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None
    audio_seconds: float = 0.0
    windows: int = 0


def _quiet_split(samples: np.ndarray, search_s: float) -> int:
    """Index of the quietest short frame within the last `search_s` seconds."""
    frame = int(SPLIT_FRAME_S * SAMPLE_RATE)
    region_start = max(0, len(samples) - int(search_s * SAMPLE_RATE))
    region = samples[region_start:]
    count = len(region) // frame
    if count < 2:
        return len(samples)
    energy = np.square(region[: count * frame].reshape(count, frame)).mean(axis=1)
    quietest = int(np.argmin(energy))
    return region_start + quietest * frame + frame // 2


def transcribe_stream(
    transcriber: Transcriber,
    blocks: Iterable[np.ndarray],
    should_abort: ShouldAbort,
    progress: Callable[[float], None],
    window_s: float = WINDOW_S,
) -> TranscriptResult:
    """Transcribe 16 kHz mono blocks window by window; timestamps are absolute."""
    result = TranscriptResult()
    window = int(window_s * SAMPLE_RATE)
    pending = np.zeros(0, dtype=np.float32)
    offset = 0  # samples already transcribed

    def run(samples: np.ndarray) -> None:
        nonlocal offset
        if len(samples) >= MIN_AUDIO_S * SAMPLE_RATE:
            out = transcriber.transcribe(
                samples,
                offset_ms=offset * 1000 // SAMPLE_RATE,
                on_segment=lambda s: progress(s.end_ms / 1000),
                should_abort=should_abort,
            )
            if should_abort():
                raise TranscriptionAbortedError
            result.segments.extend(out.segments)
            result.language = result.language or out.language
            result.windows += 1
        offset += len(samples)
        progress(offset / SAMPLE_RATE)

    for block in blocks:
        if should_abort():
            raise TranscriptionAbortedError
        pending = np.concatenate((pending, block))
        result.audio_seconds += len(block) / SAMPLE_RATE
        while len(pending) >= window + SPLIT_SEARCH_S * SAMPLE_RATE:
            cut = _quiet_split(
                pending[: window + int(SPLIT_SEARCH_S * SAMPLE_RATE)], 2 * SPLIT_SEARCH_S
            )
            run(pending[:cut])
            pending = pending[cut:]
    run(pending)
    return result


class WhisperCppTranscriber:
    """whisper.cpp through pywhispercpp, loaded on first use and unloaded when idle."""

    name = "whisper.cpp"

    def __init__(
        self,
        model_path: Path,
        model_id: str,
        threads: int | None = None,
        beam_size: int = BEAM_SIZE,
    ) -> None:
        self.model_path = model_path
        self.model_id = model_id
        self.threads = threads or max(1, min(4, os.cpu_count() or 1))
        self.beam_size = beam_size
        self._model: Any = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._exit_hook = False

    def available(self) -> bool:
        return self.model_path.is_file()

    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> Any:
        if self._model is None:
            if not self.model_path.is_file():
                from omnirecall.errors import ModelMissingError

                raise ModelMissingError(self.model_id)
            import _pywhispercpp as pw
            from pywhispercpp.model import Model

            # Silence whisper.cpp: its log lines go to stderr and may echo text.
            pw.whisper_log_set(_discard_log)
            if not self._exit_hook:
                # Runs before module teardown, so the model never outlives the log sink.
                atexit.register(self._at_exit)
                self._exit_hook = True
            started = time.monotonic()
            decoding: dict[str, Any] = {}
            if self.beam_size > 1:
                decoding = {
                    "params_sampling_strategy": 1,
                    "beam_search": {"beam_size": self.beam_size, "patience": -1.0},
                }
            self._model = Model(
                str(self.model_path),
                redirect_whispercpp_logs_to=False,
                **decoding,
                n_threads=self.threads,
                language="auto",
                print_progress=False,
                print_realtime=False,
                print_timestamps=False,
                print_special=False,
                suppress_nst=True,
            )
            logs.info(
                "model_loaded",
                model=self.model_id,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        return self._model

    def transcribe(
        self,
        samples: np.ndarray,
        offset_ms: int,
        on_segment: OnSegment,
        should_abort: ShouldAbort,
    ) -> WindowResult:
        # One whisper context serves one transcription at a time.
        while not self._lock.acquire(timeout=0.5):
            if should_abort():
                raise TranscriptionAbortedError
        try:
            model = self._load()
            self._last_used = time.monotonic()
            segments: list[Segment] = []

            def collect(raw: Any) -> None:
                segment = Segment(
                    offset_ms + int(raw.t0) * 10, offset_ms + int(raw.t1) * 10, raw.text
                )
                segments.append(segment)
                on_segment(segment)

            model.transcribe(
                np.ascontiguousarray(samples, dtype=np.float32),
                new_segment_callback=collect,
                abort_callback=should_abort,
            )
            language = self._language(model)
            self._last_used = time.monotonic()
            return WindowResult(segments=segments, language=language)
        finally:
            self._lock.release()

    @staticmethod
    def _language(model: Any) -> str | None:
        import _pywhispercpp as pw

        try:
            code = pw.whisper_lang_str(pw.whisper_full_lang_id(model._ctx))
        except (AttributeError, RuntimeError, TypeError):
            return None
        return str(code) if code else None

    def _free(self) -> None:
        """Free the model while Python is fully running, then restore whisper.cpp's
        default logger, so nothing calls back into Python during interpreter exit
        (OR-027). Called with the lock held."""
        self._model = None
        import gc

        import _pywhispercpp as pw

        gc.collect()
        pw.whisper_log_set(None)

    def close(self) -> None:
        with self._lock:
            if self._model is not None:
                self._free()

    def _at_exit(self) -> None:
        # A worker thread may still hold the lock; then only detach the logger.
        if self._lock.acquire(timeout=1):
            try:
                if self._model is not None:
                    self._free()
            finally:
                self._lock.release()
        else:
            import _pywhispercpp as pw

            pw.whisper_log_set(None)

    def unload_if_idle(self, idle_s: float) -> None:
        if self._model is None or not self._lock.acquire(blocking=False):
            return
        try:
            # >= so that 0 means "now" even where the clock ticks every ~15 ms (Windows).
            if self._model is not None and time.monotonic() - self._last_used >= idle_s:
                self._free()
                logs.info("model_unloaded", model=self.model_id)
        finally:
            self._lock.release()
