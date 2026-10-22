"""Query escaping and snippet highlighting (retrieval/search.py)."""

from __future__ import annotations

from omnirecall.retrieval.search import fts_query, make_snippet


def spans(text: str, query: str) -> list[str]:
    shown, highlights = make_snippet(text, query)
    return [shown[a:b] for a, b in highlights]


def test_fts_query_quotes_terms_and_drops_stopwords():
    assert fts_query("how do I undo my last commit") == '"undo" OR "last" OR "commit"'
    assert fts_query('title:x NEAR(a b) "q*"') == '"title" OR "x" OR "near" OR "b" OR "q"'
    assert fts_query("to be or not") == '"not"'
    assert fts_query("the") == '"the"'
    assert fts_query("  !!  ") is None


def test_highlights_skip_stopwords_and_mid_word_matches():
    text = "To undo the last commit, run git reset --soft. This shows uncommitted work."
    assert spans(text, "how do I take back my last commit") == ["last", "commit"]


def test_highlights_match_word_prefixes_for_stemmed_terms():
    assert spans("Committing early, committed often.", "commit") == ["Commit", "commit"]


def test_snippet_windows_long_text_around_first_match():
    text = ("filler " * 200) + "the invoice number is INV-2291 " + ("tail " * 200)
    shown, highlights = make_snippet(text, "invoice")
    assert shown.startswith("…") and shown.endswith("…")
    assert len(shown) <= 282
    assert [shown[a:b] for a, b in highlights] == ["invoice"]


def test_highlights_stay_aligned_when_lowercasing_changes_length():
    # "İ".lower() is two characters; matching on a lowercased copy shifted spans.
    assert spans("İstanbul trip notes: the trip budget", "trip") == ["trip", "trip"]


def test_highlights_are_case_insensitive_on_the_original_text():
    assert spans("ERROR E0382: Borrow of MOVED value", "moved borrow") == ["Borrow", "MOVED"]


def test_snippet_ends_on_a_word_boundary():
    text = ("filler " * 200) + "the invoice number is INV-2291 " + ("wordy tail " * 200)
    shown, _ = make_snippet(text, "invoice")
    assert shown.endswith("…")
    assert shown[:-1].split(" ")[-1] in {"wordy", "tail"}
