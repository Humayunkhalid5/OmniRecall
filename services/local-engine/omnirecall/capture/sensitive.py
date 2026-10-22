"""Best-effort detection of secrets in captured text (rules.md §1.7, OR-008).

This catches common, well-structured secrets. It cannot recognise every
password or token, and the UI says so. A match means the capture is dropped
before anything is stored.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Each pattern targets a format with a recognisable shape, to keep false
# positives on ordinary prose low.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("api_key", re.compile(r"\bsk-(?:[A-Za-z0-9_\-]{2,}-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(?<![a-z])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
            r"\s*[:=]\s*['\"]?[^\s'\"]{6,}"
        ),
    ),
    ("connection_string", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@[^\s]+")),
)

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_LOWER = re.compile(r"[a-z]")
_UPPER = re.compile(r"[A-Z]")
_DIGIT_OR_SYMBOL = re.compile(r"[\d\W_]")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(c / len(text) * math.log2(c / len(text)) for c in counts.values())


def _looks_like_password(text: str) -> bool:
    """A lone token of 8-128 characters with both letter cases plus a digit or
    symbol, and high entropy.

    Copied passwords and generated tokens look like this; words, numbers,
    paths, and URLs usually do not.
    """
    token = text.strip()
    if not 8 <= len(token) <= 128 or any(c.isspace() for c in token):
        return False
    if token.startswith(("http://", "https://", "/", "~", "./")) or token.count("/") > 1:
        return False
    if not (_LOWER.search(token) and _UPPER.search(token) and _DIGIT_OR_SYMBOL.search(token)):
        return False
    return _entropy(token) >= 3.0


def detect(text: str) -> str | None:
    """Return the kind of secret found, or None. Never returns the matched text."""
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return kind
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "payment_card"
    if _looks_like_password(text):
        return "password_like"
    return None
