"""Character chunker with overlap, word boundaries, and a token-limit check."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

CHUNKER_VERSION = "chars-v1"


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    start: int
    end: int


def _boundary_back(text: str, start: int, end: int) -> int:
    """Move `end` back to whitespace so no word is cut, unless that empties the chunk."""
    if end >= len(text) or text[end].isspace() or text[end - 1].isspace():
        return end
    for cut in range(end, start + (end - start) // 2, -1):
        if text[cut - 1].isspace():
            return cut
    return end  # one very long token: hard cut


def _boundary_forward(text: str, position: int, limit: int) -> int:
    """Move an overlap start forward to the beginning of a word."""
    if position <= 0 or text[position - 1].isspace():
        return position
    for cut in range(position, min(limit, len(text))):
        if text[cut].isspace():
            return cut + 1
    return position


def chunk_text(
    text: str,
    size: int = 500,
    overlap: int = 50,
    count_tokens: Callable[[str], int] | None = None,
    max_tokens: int = 256,
) -> list[Chunk]:
    """Split normalized text into overlapping chunks with source offsets.

    If `count_tokens` is given, any chunk above `max_tokens` is split again
    (smaller window) so nothing is silently truncated by the model.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    spans: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        while start < length and text[start].isspace():
            start += 1
        if start >= length:
            break
        end = min(start + size, length)
        end = _boundary_back(text, start, end)
        spans.append((start, end))
        if end >= length:
            break
        next_start = _boundary_forward(text, max(end - overlap, start + 1), end)
        start = next_start if next_start > start else end
    if count_tokens is not None:
        spans = _enforce_token_limit(text, spans, count_tokens, max_tokens)
    chunks = []
    for ordinal, (s, e) in enumerate(spans):
        piece = text[s:e]
        stripped_end = s + len(piece.rstrip())
        chunks.append(Chunk(ordinal, text[s:stripped_end], s, stripped_end))
    return [c for c in chunks if c.text]


def _enforce_token_limit(
    text: str, spans: list[tuple[int, int]], count_tokens: Callable[[str], int], max_tokens: int
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in spans:
        stack = [(start, end)]
        while stack:
            s, e = stack.pop()
            if e - s <= 1 or count_tokens(text[s:e]) <= max_tokens:
                result.append((s, e))
                continue
            mid = _boundary_back(text, s, s + (e - s) // 2)
            if mid <= s or mid >= e:
                mid = s + (e - s) // 2
            stack.append((mid, e))
            stack.append((s, mid))
    return result
