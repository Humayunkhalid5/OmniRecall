"""Word error rate for English speech-to-text checks.

Both sides are normalized the way speech benchmarks do it (as in Whisper's
English normalizer, reduced to what the fixtures need): lower case, no
punctuation, and spelled-out numbers turned into digits, so "forty minutes"
and "40 minutes" count as the same words.
"""

from __future__ import annotations

import difflib
import re

_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}


def _numbers_to_digits(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] not in _UNITS and tokens[i] not in _TENS:
            out.append(tokens[i])
            i += 1
            continue
        total = current = 0
        j = i
        while j < len(tokens):
            word = tokens[j]
            if word in _UNITS:
                current += _UNITS[word]
            elif word in _TENS:
                current += _TENS[word]
            elif word in _SCALES and j > i:
                scale = _SCALES[word]
                if scale == 100:
                    current *= 100
                else:
                    total += current * scale
                    current = 0
            elif word == "and" and j + 1 < len(tokens) and j > i:
                # "one hundred and eighty": "and" joins only after a scale word.
                if tokens[j - 1] not in _SCALES or (
                    tokens[j + 1] not in _UNITS and tokens[j + 1] not in _TENS
                ):
                    break
            else:
                break
            j += 1
        out.append(str(total + current))
        i = j
    return out


def normalize(text: str) -> list[str]:
    text = re.sub(r"(\d),(\d)", r"\1\2", text.lower())
    words = re.sub(r"[^\w\s']", " ", text).replace("'", "").split()
    return _numbers_to_digits(re.sub(r"-", " ", " ".join(words)).split())


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    matcher = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    errors = sum(
        max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"
    )
    return errors / max(len(ref), 1)
