"""Speech-to-text accuracy and speed with the real whisper.cpp `base` model.

Usage: python scripts/eval_transcription.py <models_dir>
<models_dir> holds `whisper-base/ggml-base.bin`, installed by the engine's
ModelManager. For each spoken fixture, prints the word error rate against its
script, the detected language, and the real-time factor (transcription time
divided by recording length). Exits non-zero if any fixture has WER >= 0.25
or is not detected as English (the Phase 5 exit gate).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from omnirecall.extraction.audio import SAMPLE_RATE, AudioDecoder
from omnirecall.extraction.transcribe import WhisperCppTranscriber, transcribe_stream
from omnirecall.extraction.transcript import build_text, clean_segments

FIXTURES = Path(__file__).resolve().parents[1] / "services/local-engine/tests/fixtures/audio"
SPOKEN = (
    "voice_memo.m4a",
    "meeting_note.mp3",
    "recipe.ogg",
    "lecture.flac",
    "voice_memo.wav",
)


def words(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", "", text.lower()).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    matcher = difflib.SequenceMatcher(None, ref, hyp)
    errors = sum(
        max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"
    )
    return errors / max(len(ref), 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models_dir", type=Path)
    args = parser.parse_args()
    model = args.models_dir / "whisper-base" / "ggml-base.bin"
    if not model.is_file():
        sys.exit(f"model not found: {model}")
    decoder = AudioDecoder()
    if not decoder.available():
        sys.exit("audio decoder not built")
    transcriber = WhisperCppTranscriber(model, "whisper-base")
    failed = False
    rows = []
    try:
        for name in SPOKEN:
            blocks = list(decoder.stream(FIXTURES / name, 7200))
            seconds = sum(len(b) for b in blocks) / SAMPLE_RATE
            started = time.perf_counter()
            result = transcribe_stream(transcriber, iter(blocks), lambda: False, lambda _p: None)
            elapsed = time.perf_counter() - started
            text, _spans = build_text(clean_segments(result.segments))
            reference = (FIXTURES / (Path(name).stem + ".txt")).read_text().strip()
            wer = word_error_rate(reference, text)
            ok = wer < 0.25 and result.language == "en"
            failed |= not ok
            rows.append(
                {
                    "fixture": name,
                    "seconds": round(seconds, 1),
                    "wer": round(wer, 3),
                    "language": result.language,
                    "transcribe_s": round(elapsed, 2),
                    "real_time_factor": round(elapsed / seconds, 3),
                    "ok": ok,
                }
            )
            # Fixture scripts are synthetic test text, so printing them is safe here.
            print(json.dumps({**rows[-1], "text": text}), flush=True)
    finally:
        transcriber.close()
    print(
        json.dumps(
            {
                "summary": True,
                "mean_wer": round(float(np.mean([r["wer"] for r in rows])), 3),
                "max_wer": max(r["wer"] for r in rows),
                "mean_real_time_factor": round(
                    float(np.mean([r["real_time_factor"] for r in rows])), 3
                ),
            }
        )
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
