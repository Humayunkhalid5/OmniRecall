"""Speech-to-text accuracy and speed with the real whisper.cpp `base` model.

Usage: python scripts/eval_transcription.py <models_dir> [--librispeech FILE.parquet]
<models_dir> holds `whisper-base/ggml-base.bin`, installed by the engine's
ModelManager.

For each spoken fixture (synthetic espeak-ng voices), and optionally for each
utterance of a LibriSpeech parquet file (real read speech, CC BY 4.0), prints
the word error rate against the reference, the detected language, and the
real-time factor (transcription time divided by recording length). WER uses
the normalization in tests/wer.py. This script measures; the pass/fail gates
are the real-model tests in tests/test_audio.py (D-038).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from omnirecall.extraction.audio import SAMPLE_RATE, AudioDecoder
from omnirecall.extraction.transcribe import WhisperCppTranscriber, transcribe_stream
from omnirecall.extraction.transcript import build_text, clean_segments

TESTS = Path(__file__).resolve().parents[1] / "services/local-engine/tests"
sys.path.insert(0, str(TESTS))
from wer import word_error_rate  # noqa: E402

FIXTURES = TESTS / "fixtures/audio"
SPOKEN = ("voice_memo.m4a", "meeting_note.mp3", "recipe.ogg", "lecture.flac", "voice_memo.wav")


def librispeech(parquet: Path, folder: Path) -> list[tuple[str, Path, str]]:
    import pyarrow.parquet as pq

    table = pq.read_table(parquet, columns=["id", "audio", "text"]).to_pylist()
    cases = []
    for row in table:
        path = folder / f"{row['id']}.flac"
        path.write_bytes(row["audio"]["bytes"])
        cases.append((row["id"], path, row["text"]))
    return cases


def run(
    transcriber: WhisperCppTranscriber, decoder: AudioDecoder, cases: list[tuple[str, Path, str]]
) -> list[dict]:
    rows = []
    for name, path, reference in cases:
        blocks = list(decoder.stream(path, 7200))
        seconds = sum(len(b) for b in blocks) / SAMPLE_RATE
        started = time.perf_counter()
        result = transcribe_stream(transcriber, iter(blocks), lambda: False, lambda _p: None)
        elapsed = time.perf_counter() - started
        text, _spans = build_text(clean_segments(result.segments))
        row = {
            "case": name,
            "seconds": round(seconds, 1),
            "words": len(reference.split()),
            "wer": round(word_error_rate(reference, text), 3),
            "language": result.language,
            "transcribe_s": round(elapsed, 2),
            "real_time_factor": round(elapsed / seconds, 3),
        }
        rows.append(row)
        # Fixture scripts and LibriSpeech are public test text, so printing them is safe.
        print(json.dumps({**row, "text": text}), flush=True)
    return rows


def summary(label: str, rows: list[dict]) -> dict:
    words = sum(r["words"] for r in rows)
    return {
        "summary": label,
        "cases": len(rows),
        # Corpus WER weights each case by its length, as speech benchmarks report it.
        "corpus_wer": round(sum(r["wer"] * r["words"] for r in rows) / max(words, 1), 3),
        "mean_wer": round(float(np.mean([r["wer"] for r in rows])), 3),
        "max_wer": max(r["wer"] for r in rows),
        "english_detected": sum(r["language"] == "en" for r in rows),
        "mean_real_time_factor": round(float(np.mean([r["real_time_factor"] for r in rows])), 3),
        "audio_seconds": round(sum(r["seconds"] for r in rows), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models_dir", type=Path)
    parser.add_argument("--librispeech", type=Path)
    args = parser.parse_args()
    model = args.models_dir / "whisper-base" / "ggml-base.bin"
    if not model.is_file():
        sys.exit(f"model not found: {model}")
    decoder = AudioDecoder()
    if not decoder.available():
        sys.exit("audio decoder not built")
    transcriber = WhisperCppTranscriber(model, "whisper-base")
    try:
        fixtures = [
            (n, FIXTURES / n, (FIXTURES / (Path(n).stem + ".txt")).read_text().strip())
            for n in SPOKEN
        ]
        results = [summary("fixtures (espeak-ng)", run(transcriber, decoder, fixtures))]
        if args.librispeech:
            with tempfile.TemporaryDirectory() as tmp:
                cases = librispeech(args.librispeech, Path(tmp))
                results.append(summary("librispeech", run(transcriber, decoder, cases)))
    finally:
        transcriber.close()
    for result in results:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
