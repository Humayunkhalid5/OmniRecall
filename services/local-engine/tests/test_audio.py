"""Audio import and transcription (Phase 5).

The decoder tests run the real `omnirecall-audio-decode` helper (built from
services/audio-decoder). Transcription is faked in the engine tests so they
are fast and exact; the whisper.cpp binding is exercised with a tiny random
model, and with the real ggml-base model when OMNIRECALL_TEST_MODELS_DIR has it.
"""

from __future__ import annotations

import io
import os
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from engine_support import Recorder, wait_status, wait_until
from support import HashEmbedder

from omnirecall import logs
from omnirecall.app import Engine
from omnirecall.errors import EngineError
from omnirecall.extraction.audio import SAMPLE_RATE, AudioDecoder
from omnirecall.extraction.transcribe import (
    TranscriptionAbortedError,
    WindowResult,
    transcribe_stream,
)
from omnirecall.extraction.transcript import (
    Segment,
    build_text,
    chunk_times,
    clean_segments,
)

FIXTURES = Path(__file__).parent / "fixtures" / "audio"
SPOKEN = ("voice_memo.m4a", "meeting_note.mp3", "recipe.ogg", "lecture.flac", "voice_memo.wav")
needs_decoder = pytest.mark.skipif(
    not AudioDecoder().available(), reason="the audio decoder is not built"
)


# ---- fakes -------------------------------------------------------------------


class FakeTranscriber:
    """Speaks a fixed script: one segment per two seconds of window, in order."""

    name = "fake-whisper"
    model_id = "whisper-base"

    def __init__(self, script: str = "") -> None:
        self.script = script.split()
        self.installed = True
        self.calls = 0
        self.windows: list[tuple[int, int]] = []
        self.delay_s = 0.0
        self.started = threading.Event()
        self._next = 0

    def available(self) -> bool:
        return self.installed

    def loaded(self) -> bool:
        return self.calls > 0

    def unload_if_idle(self, idle_s: float) -> None:
        pass

    def close(self) -> None:
        pass

    def transcribe(self, samples, offset_ms, on_segment, should_abort) -> WindowResult:
        self.calls += 1
        self.started.set()
        length_ms = len(samples) * 1000 // SAMPLE_RATE
        self.windows.append((offset_ms, length_ms))
        deadline = time.monotonic() + self.delay_s
        while time.monotonic() < deadline:
            if should_abort():
                return WindowResult([])
            time.sleep(0.02)
        segments = []
        for start in range(0, max(length_ms, 1), 2000):
            words = self.script[self._next : self._next + 4]
            if not words:
                break
            self._next += len(words)
            segment = Segment(
                offset_ms + start, offset_ms + min(start + 2000, length_ms), " ".join(words)
            )
            segments.append(segment)
            on_segment(segment)
        return WindowResult(segments, language="en")


def make_engine(tmp_path: Path, transcriber: FakeTranscriber) -> tuple[Engine, Recorder]:
    recorder = Recorder()
    engine = Engine(
        tmp_path / "data", None, recorder, embedder=HashEmbedder(), transcriber=transcriber
    )
    return engine, recorder


def copy_fixture(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "inbox" / name
    target.parent.mkdir(exist_ok=True)
    shutil.copy(FIXTURES / name, target)
    return target


def import_one(engine: Engine, path: Path) -> str:
    return engine.import_paths({"paths": [str(path)]})["item_ids"][0]


def script(name: str) -> str:
    return (FIXTURES / (Path(name).stem + ".txt")).read_text().strip()


# ---- transcript cleanup ------------------------------------------------------


def test_cleanup_drops_non_speech_tags_and_keeps_words():
    cleaned = clean_segments(
        [
            Segment(0, 900, " [BLANK_AUDIO]"),
            Segment(900, 2000, "Call the landlord (upbeat music) today."),
            Segment(2000, 2500, "♪ ♪"),
            Segment(2500, 3000, "*laughs*"),
            Segment(3000, 4000, "  Bring   the  keys. "),
        ]
    )
    assert [s.text for s in cleaned] == ["Call the landlord today.", "Bring the keys."]
    assert (cleaned[0].start_ms, cleaned[0].end_ms) == (900, 2000)


def test_cleanup_collapses_hallucination_loops():
    looped = "we will rebuild we will rebuild we will rebuild we will rebuild we will rebuild"
    cleaned = clean_segments(
        [
            Segment(0, 1000, looped),
            Segment(1000, 2000, "Thank you."),
            Segment(2000, 3000, "thank you"),
            Segment(3000, 4000, "Thank you!"),
            Segment(4000, 5000, "No, no, no, that is wrong."),
        ]
    )
    assert [s.text for s in cleaned] == [
        "we will rebuild",
        "Thank you.",
        "No, no, no, that is wrong.",
    ]
    # The merged repeat covers the time of all three copies.
    assert (cleaned[1].start_ms, cleaned[1].end_ms) == (1000, 4000)


def test_cleanup_of_silence_leaves_nothing():
    assert clean_segments([Segment(0, 30000, "[BLANK_AUDIO]"), Segment(0, 1, "  ")]) == []


def test_text_offsets_map_chunks_to_recording_times():
    segments = [
        Segment(0, 2000, "alpha beta"),
        Segment(2000, 5000, "gamma"),
        Segment(5000, 9000, "delta"),
    ]
    text, spans = build_text(segments)
    assert text == "alpha beta\ngamma\ndelta"
    assert [text[s.start : s.end] for s in spans] == ["alpha beta", "gamma", "delta"]
    assert chunk_times(spans, 0, 5) == (0, 2000)
    assert chunk_times(spans, 6, 16) == (0, 5000)  # "beta\ngamma"
    assert chunk_times(spans, 17, 22) == (5000, 9000)
    assert chunk_times(spans, 100, 120) == (None, None)


# ---- windowing ---------------------------------------------------------------


def tone(seconds: float, quiet_at: float | None = None) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    samples = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    if quiet_at is not None:
        start = int(quiet_at * SAMPLE_RATE)
        samples[start : start + SAMPLE_RATE // 2] = 0.0
    return samples


def blocks_of(samples: np.ndarray, block_s: float = 7.0):
    step = int(block_s * SAMPLE_RATE)
    for start in range(0, len(samples), step):
        yield samples[start : start + step]


def test_long_audio_is_split_at_a_pause_with_absolute_times():
    fake = FakeTranscriber(" ".join(f"w{i}" for i in range(400)))
    # 25 s of audio, 10 s windows, a pause just after 11 s.
    audio = tone(25, quiet_at=11.2)
    progress: list[float] = []
    result = transcribe_stream(fake, blocks_of(audio), lambda: False, progress.append, window_s=10)
    first_offset, first_len = fake.windows[0]
    assert first_offset == 0 and 11_000 <= first_len <= 11_800  # cut inside the pause
    assert fake.windows[1][0] == first_len  # the next window starts where the last ended
    assert sum(length for _, length in fake.windows) == pytest.approx(25_000, abs=5)
    assert result.audio_seconds == pytest.approx(25.0)
    starts = [s.start_ms for s in result.segments]
    assert starts == sorted(starts) and starts[-1] > 20_000
    assert progress[-1] == pytest.approx(25.0)


def test_abort_stops_between_windows():
    fake = FakeTranscriber("a b c d e f g h")
    calls = {"n": 0}

    def should_abort() -> bool:
        calls["n"] += 1
        return fake.calls >= 1

    with pytest.raises(TranscriptionAbortedError):
        transcribe_stream(fake, blocks_of(tone(40)), should_abort, lambda _s: None, window_s=10)
    assert fake.calls == 1


# ---- the decoder helper ------------------------------------------------------


@needs_decoder
@pytest.mark.parametrize("name", SPOKEN)
def test_decoder_reads_common_formats_at_16k_mono(name):
    decoder = AudioDecoder()
    info = decoder.probe(FIXTURES / name)
    samples = np.concatenate(list(decoder.stream(FIXTURES / name, 7200, block_s=1.0)))
    assert samples.dtype == np.float32
    assert len(samples) / SAMPLE_RATE == pytest.approx(info.duration_s, abs=0.1)
    assert 0.01 < float(np.abs(samples).max()) <= 1.0


@needs_decoder
@pytest.mark.parametrize(
    ("name", "code"),
    [("unsupported_opus.ogg", "unsupported_codec"), ("truncated.m4a", "malformed_file")],
)
def test_decoder_reports_unreadable_files_with_clear_codes(name, code):
    with pytest.raises(EngineError) as info:
        AudioDecoder().probe(FIXTURES / name)
    assert info.value.code == code


@needs_decoder
def test_decoder_enforces_the_duration_limit_while_decoding(tmp_path):
    with pytest.raises(EngineError) as info:
        list(AudioDecoder().stream(FIXTURES / "lecture.flac", 3))
    assert info.value.code == "limit_exceeded"


@needs_decoder
def test_stopping_early_kills_the_decoder(monkeypatch):
    import subprocess

    started: list[subprocess.Popen] = []
    real = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real(*args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", spy)
    stream = AudioDecoder().stream(FIXTURES / "meeting_note.mp3", 7200, block_s=0.5)
    next(stream)
    stream.close()
    assert started and started[0].poll() is not None


def test_missing_decoder_is_reported(tmp_path):
    decoder = AudioDecoder(command=str(tmp_path / "missing"))
    assert not decoder.available()
    with pytest.raises(EngineError) as info:
        decoder.probe(FIXTURES / "voice_memo.wav")
    assert info.value.code == "audio_decoder_unavailable"


# ---- engine flow (fake transcriber, real decoder) ------------------------------


@pytest.fixture
def fake():
    return FakeTranscriber()


@pytest.fixture
def engine(tmp_path, fake):
    engine, _ = make_engine(tmp_path, fake)
    yield engine
    engine.close()


@needs_decoder
def test_audio_import_is_searchable_with_timestamps(tmp_path, engine, fake):
    fake.script = script("meeting_note.mp3").split()
    item_id = import_one(engine, copy_fixture(tmp_path, "meeting_note.mp3"))
    assert wait_status(engine, item_id, {"indexed", "failed"}) == "indexed"
    item = engine.repo.get_item(item_id)
    meta = item.metadata
    assert meta["format"] == "audio" and meta["codec"] == "mp3"
    assert meta["duration_s"] == pytest.approx(10.0, abs=0.1)
    assert meta["transcription_model"] == "whisper-base" and meta["language"] == "en"
    detail = engine.get_item({"item_id": item_id})
    assert all(c["start_ms"] is not None and c["end_ms"] >= c["start_ms"] for c in detail["chunks"])
    hits = engine.search({"query": "product launch second week of March"})["results"]
    assert hits and hits[0]["item_id"] == item_id
    assert hits[0]["start_ms"] is not None and hits[0]["end_ms"] <= 10_100


@needs_decoder
def test_progress_is_reported_while_transcribing(tmp_path, fake):
    fake.script = script("lecture.flac").split()
    fake.delay_s = 1.2
    engine, recorder = make_engine(tmp_path, fake)
    try:
        item_id = import_one(engine, copy_fixture(tmp_path, "lecture.flac"))
        wait_status(engine, item_id, {"indexed"})
        stages = [
            p for m, p in recorder.events if m == "items.progress" and p["item_id"] == item_id
        ]
        transcribing = [p for p in stages if p["stage"] == "transcribing"]
        assert transcribing and transcribing[-1]["total_s"] == pytest.approx(10.3, abs=0.2)
        assert all(0 <= p.get("percent", 0) <= 100 for p in transcribing)
    finally:
        engine.close()


@needs_decoder
def test_missing_model_fails_clearly_and_retries_after_install(tmp_path, engine, fake):
    fake.installed = False
    item_id = import_one(engine, copy_fixture(tmp_path, "voice_memo.wav"))
    assert wait_status(engine, item_id, {"failed", "indexed"}) == "failed"
    item = engine.repo.get_item(item_id)
    assert item.error_code == "transcription_model_missing"
    assert (
        engine.repo.db.conn.execute(
            "SELECT attempt_count FROM jobs WHERE item_id = ?", (item_id,)
        ).fetchone()[0]
        == 1
    )  # permanent: no pointless retries
    fake.installed = True
    fake.script = script("voice_memo.wav").split()
    engine._requeue_model_missing()
    assert wait_status(engine, item_id, {"indexed", "failed"}) == "indexed"


@needs_decoder
def test_recordings_over_the_duration_limit_are_refused(tmp_path, engine):
    engine.settings_update({"changes": {"max_audio_seconds": 5}})
    item_id = import_one(engine, copy_fixture(tmp_path, "lecture.flac"))
    assert wait_status(engine, item_id, {"failed", "indexed"}) == "failed"
    assert engine.repo.get_item(item_id).error_code == "limit_exceeded"


@needs_decoder
@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("unsupported_opus.ogg", "unsupported_codec"),
        ("truncated.m4a", "malformed_file"),
        ("silence.wav", "extraction_empty"),
    ],
)
def test_unusable_audio_fails_with_a_clear_code(tmp_path, engine, name, code):
    item_id = import_one(engine, copy_fixture(tmp_path, name))
    assert wait_status(engine, item_id, {"failed", "indexed"}) == "failed"
    assert engine.repo.get_item(item_id).error_code == code


@needs_decoder
def test_cancel_stops_a_running_transcription(tmp_path, engine, fake):
    fake.script = script("recipe.ogg").split()
    fake.delay_s = 30
    item_id = import_one(engine, copy_fixture(tmp_path, "recipe.ogg"))
    assert fake.started.wait(10)
    began = time.monotonic()
    engine.cancel_job({"item_id": item_id})
    wait_until(lambda: engine.runner.active == 0, timeout=5)
    assert time.monotonic() - began < 3
    item = engine.repo.get_item(item_id)
    assert item.status == "failed" and item.error_code == "cancelled"
    assert engine.repo.chunks_for_item(item_id) == []
    # A cancelled item can be retried.
    fake.delay_s = 0
    fake.started.clear()
    engine.retry_item({"item_id": item_id})
    assert wait_status(engine, item_id, {"indexed", "failed"}) == "indexed"


@needs_decoder
def test_deleting_during_transcription_aborts_it(tmp_path, engine, fake):
    fake.delay_s = 30
    item_id = import_one(engine, copy_fixture(tmp_path, "recipe.ogg"))
    assert fake.started.wait(10)
    engine.delete_item({"item_id": item_id})
    wait_until(lambda: engine.repo.get_item(item_id).status == "deleted", timeout=10)
    wait_until(lambda: engine.runner.active == 0, timeout=5)
    assert engine.repo.chunks_for_item(item_id) == []


@needs_decoder
def test_logs_never_contain_transcript_words(tmp_path, engine, fake, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(logs, "_stream", stream)
    monkeypatch.setattr(logs, "_min_level", 0)
    fake.script = script("voice_memo.m4a").split()
    item_id = import_one(engine, copy_fixture(tmp_path, "voice_memo.m4a"))
    wait_status(engine, item_id, {"indexed"})
    engine.search({"query": "landlord heating plumber"})
    log = stream.getvalue()
    assert "item_indexed" in log
    for needle in ("landlord", "heating", "plumber", "voice_memo"):
        assert needle not in log, needle


def test_formats_list_includes_audio(tmp_path, engine):
    formats = engine.formats_list({})
    extensions = {ext for f in formats["audio"] for ext in f["extensions"]}
    assert {".mp3", ".m4a", ".wav", ".flac", ".ogg"} <= extensions
    assert ".opus" not in extensions
    assert isinstance(formats["transcription_available"], bool)


# ---- the real whisper.cpp binding ---------------------------------------------


def test_whisper_binding_loads_from_a_local_path_only(tmp_path, capfd):
    from whisper_synth import write_random_model

    from omnirecall.extraction.transcribe import WhisperCppTranscriber

    missing = WhisperCppTranscriber(tmp_path / "absent.bin", "whisper-base")
    assert not missing.available()
    with pytest.raises(EngineError) as info:
        missing.transcribe(tone(1), 0, lambda _s: None, lambda: False)
    assert info.value.code == "model_missing"

    model = write_random_model(tmp_path / "tiny.bin")
    transcriber = WhisperCppTranscriber(model, "whisper-base", threads=1)
    seen: list[Segment] = []
    result = transcriber.transcribe(tone(3), 5_000, seen.append, lambda: False)
    assert transcriber.loaded()
    # A random model says nothing meaningful; the timings are what is checked.
    assert all(s.start_ms >= 5_000 for s in result.segments)
    assert seen == result.segments
    # Aborting returns at once.
    began = time.monotonic()
    transcriber.transcribe(tone(20), 0, lambda _s: None, lambda: True)
    assert time.monotonic() - began < 2
    transcriber.unload_if_idle(0)
    assert not transcriber.loaded()
    out, err = capfd.readouterr()
    assert out == "" and err == ""  # whisper.cpp's console output is off


REAL_MODELS = Path(os.environ.get("OMNIRECALL_TEST_MODELS_DIR", "/nonexistent"))
REAL_MODEL = REAL_MODELS / "whisper-base"
needs_real_models = pytest.mark.skipif(
    not (REAL_MODEL / "ggml-base.bin").is_file() or not (REAL_MODELS / "all-minilm-l6-v2").is_dir(),
    reason="the real ggml-base and MiniLM models are not available",
)
# A question someone would ask later, in other words than the recording (D-038).
SPOKEN_QUERIES = {
    "voice_memo.m4a": "when is the plumber coming to fix the heating",
    "meeting_note.mp3": "when was the product launch moved to",
    "recipe.ogg": "how long to bake the lemon cake",
    "lecture.flac": "how do plants make glucose from sunlight",
}


@needs_decoder
@needs_real_models
@pytest.mark.timeout(600)
@pytest.mark.parametrize("name", SPOKEN)
def test_real_model_transcribes_fixtures_offline(tmp_path, name):
    """Sanity bound per fixture; accuracy itself is measured by eval_transcription.py."""
    from wer import word_error_rate

    from omnirecall.extraction.transcribe import WhisperCppTranscriber

    transcriber = WhisperCppTranscriber(REAL_MODEL / "ggml-base.bin", "whisper-base")
    try:
        result = transcribe_stream(
            transcriber,
            AudioDecoder().stream(FIXTURES / name, 7200),
            lambda: False,
            lambda _s: None,
        )
    finally:
        transcriber.close()
    text, _spans = build_text(clean_segments(result.segments))
    assert word_error_rate(script(name), text) < 0.35, text
    assert result.language == "en"


@needs_decoder
@needs_real_models
@pytest.mark.timeout(900)
def test_real_models_make_every_recording_findable(tmp_path):
    """The Phase 5 exit gate with the real models: each recording, transcribed on
    this machine, is the top result for a paraphrased question about it."""
    engine = Engine(tmp_path / "data", REAL_MODELS, lambda m, p: None)
    try:
        ids = {}
        for name in SPOKEN_QUERIES:
            ids[name] = import_one(engine, copy_fixture(tmp_path, name))
        for item_id in ids.values():
            wait_status(engine, item_id, {"indexed"}, timeout=600)
        for name, query in SPOKEN_QUERIES.items():
            results = engine.search({"query": query, "limit": 5})["results"]
            assert results and results[0]["item_id"] == ids[name], (name, results[:2])
            assert results[0]["start_ms"] is not None
    finally:
        engine.close()


@pytest.mark.parametrize("ending", ["close", "exit", "unload_then_close"])
def test_process_exits_cleanly_after_a_transcription(tmp_path, ending):
    """whisper.cpp logged into a freed Python callback during interpreter exit (OR-027),
    including after the idle timer had already unloaded the model."""
    import subprocess
    import sys

    from whisper_synth import write_random_model

    model = write_random_model(tmp_path / "tiny.bin")
    endings = {
        "close": "t.close()\n",
        "exit": "",
        "unload_then_close": "t.unload_if_idle(0)\nassert not t.loaded()\nt.close()\n",
    }
    program = (
        "import numpy as np\n"
        "from pathlib import Path\n"
        # Holding the module keeps the teardown order that exposed the idle-unload case.
        "from omnirecall.extraction import transcribe\n"
        f"t = transcribe.WhisperCppTranscriber(Path({str(model)!r}), 'whisper-base', threads=1)\n"
        "t.transcribe(np.zeros(16000, dtype=np.float32), 0, lambda s: None, lambda: False)\n"
        + endings[ending]
    )
    done = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=120)
    assert done.returncode == 0, done.stderr[-500:]


@needs_decoder
def test_search_can_be_limited_to_audio_notes(tmp_path, engine, fake):
    fake.script = script("recipe.ogg").split()
    heard = import_one(engine, copy_fixture(tmp_path, "recipe.ogg"))
    typed = engine.import_text({"text": "lemon cake with flour and sugar, baked for forty minutes"})
    wait_status(engine, heard, {"indexed"})
    wait_status(engine, typed["item"]["id"], {"indexed"})
    both = {r["item_id"] for r in engine.search({"query": "lemon cake flour"})["results"]}
    assert both == {heard, typed["item"]["id"]}
    only = engine.search({"query": "lemon cake flour", "filters": {"formats": ["audio"]}})
    assert [r["item_id"] for r in only["results"]] == [heard]
