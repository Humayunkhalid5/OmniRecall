"""Transcript segments: cleanup and the text and timestamps built from them.

Whisper output carries noise that would pollute search: non-speech tags such
as `[BLANK_AUDIO]` or `(music)`, and on silence or music it can repeat a
phrase over and over. Cleanup removes those and keeps every real word and
its timing. Transcripts are untrusted data (rules.md §4.4) and are never logged.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from omnirecall.extraction.text import normalize_text


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Span:
    """Where a segment sits in the transcript text and in the recording."""

    start: int
    end: int
    start_ms: int
    end_ms: int


# A tag Whisper writes for something that is not speech, e.g. [BLANK_AUDIO], [Music],
# (upbeat music), *laughs*. Only whole bracketed groups are removed.
_TAG = re.compile(r"\[[^\[\]]{0,60}\]|\([^()]{0,60}\)|\*[^*]{0,40}\*|[♪♫♬]+")
# A run of the same 1-8 word phrase repeated four or more times in a row.
_MAX_PHRASE = 8
_MAX_REPEATS = 3


def _strip_tags(text: str) -> str:
    return _TAG.sub(" ", text)


def _collapse_loops(text: str) -> str:
    """Shorten a phrase repeated more than three times in a row to one copy.

    "we will we will we will we will we will" becomes "we will". Normal
    emphasis ("no, no, no") is left alone.
    """
    words = text.split()
    for size in range(1, _MAX_PHRASE + 1):
        keys = [w.lower().strip(",.!?") for w in words]
        out: list[str] = []
        i = 0
        while i < len(words):
            phrase = keys[i : i + size]
            repeats = 1
            while keys[i + repeats * size : i + (repeats + 1) * size] == phrase:
                repeats += 1
            if len(phrase) == size and repeats > _MAX_REPEATS:
                out.extend(words[i : i + size])
                i += repeats * size
            else:
                out.append(words[i])
                i += 1
        words = out
    return " ".join(words)


def _key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def clean_segments(segments: Sequence[Segment]) -> list[Segment]:
    """Drop non-speech segments and loops; merge back-to-back repeats of one segment."""
    cleaned: list[Segment] = []
    for segment in segments:
        text = normalize_text(_collapse_loops(_strip_tags(segment.text))).replace("\n", " ")
        if not _key(text):
            continue
        start = max(0, segment.start_ms)
        end = max(start, segment.end_ms)
        if cleaned and _key(cleaned[-1].text) == _key(text):
            # A hallucination loop across segments: keep one, covering the whole span.
            previous = cleaned[-1]
            cleaned[-1] = Segment(previous.start_ms, max(previous.end_ms, end), previous.text)
            continue
        cleaned.append(Segment(start, end, text))
    return cleaned


def build_text(segments: Sequence[Segment]) -> tuple[str, list[Span]]:
    """One line per segment, with each line's offsets and times."""
    parts: list[str] = []
    spans: list[Span] = []
    offset = 0
    for segment in segments:
        if parts:
            offset += 1  # the newline
        spans.append(Span(offset, offset + len(segment.text), segment.start_ms, segment.end_ms))
        parts.append(segment.text)
        offset += len(segment.text)
    return "\n".join(parts), spans


def chunk_times(spans: Sequence[Span], start: int, end: int) -> tuple[int | None, int | None]:
    """The recording time covered by text offsets [start, end)."""
    covering = [s for s in spans if s.end > start and s.start < end]
    if not covering:
        return None, None
    return covering[0].start_ms, covering[-1].end_ms
