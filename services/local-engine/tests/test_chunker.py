import itertools

from omnirecall.chunking.chunker import chunk_text
from omnirecall.extraction.text import normalize_text

WORDS = " ".join(f"word{i:04d}" for i in range(400))


def test_offsets_overlap_and_word_boundaries():
    chunks = chunk_text(WORDS, size=100, overlap=20)
    assert len(chunks) > 5
    for chunk in chunks:
        assert WORDS[chunk.start : chunk.end] == chunk.text
        assert len(chunk.text) <= 100
        assert not chunk.text.startswith(" ") and not chunk.text.endswith(" ")
        # Never cut inside a word.
        assert chunk.start == 0 or WORDS[chunk.start - 1] == " "
        assert chunk.end == len(WORDS) or WORDS[chunk.end] == " "
    for a, b in itertools.pairwise(chunks):
        assert b.start < a.end  # overlap
        assert b.start > a.start
    assert chunks[-1].end == len(WORDS)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_deterministic():
    assert chunk_text(WORDS, 120, 30) == chunk_text(WORDS, 120, 30)


def test_short_and_empty():
    assert chunk_text("", 500, 50) == []
    assert [c.text for c in chunk_text("hello", 500, 50)] == ["hello"]


def test_long_token_is_hard_cut():
    blob = "x" * 1200
    chunks = chunk_text(blob, 500, 50)
    assert all(len(c.text) <= 500 for c in chunks)
    assert chunks[-1].end == 1200


def test_token_limit_splits_further():
    counter = lambda s: len(s.split()) + 2  # noqa: E731
    chunks = chunk_text(WORDS, size=500, overlap=50, count_tokens=counter, max_tokens=20)
    assert all(counter(c.text) <= 20 for c in chunks)
    for chunk in chunks:
        assert WORDS[chunk.start : chunk.end] == chunk.text


def test_normalize_text():
    raw = "\ufeffHello\r\nwor\u0000ld  \t  x\n\n\n\n\nnext\u00a0para "
    assert normalize_text(raw) == "Hello\nworld x\n\nnext para"
    assert normalize_text("é") == "é"
