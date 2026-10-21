"""The labeled evaluation corpus stays well-formed (OR-011)."""

import json
from pathlib import Path

EVAL = Path(__file__).parent / "fixtures" / "eval"


def test_corpus_and_queries_are_consistent():
    docs = [
        json.loads(line)
        for line in (EVAL / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    queries = [
        json.loads(line)
        for line in (EVAL / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    ids = {d["id"] for d in docs}
    assert len(ids) == len(docs)
    assert 45 <= len(queries) <= 60
    assert len({q["id"] for q in queries}) == len(queries)
    assert all(q["expected"] and set(q["expected"]) <= ids for q in queries)
    assert sum(q["lang"] != "en" for q in queries) >= 5
    assert {d["lang"] for d in docs} >= {"en", "es", "fr", "de"}
