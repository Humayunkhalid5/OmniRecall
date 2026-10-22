# Evaluation corpus

Deterministic, hand-written fixture data for relevance measurement (OR-011). No real personal data.

- `corpus.jsonl`: 44 documents (38 English, 2 Spanish, 2 French, 2 German) shaped like real captures: copied errors, commands, lecture slides, meeting notes, bookings, recipes.
- `queries.jsonl`: 52 labeled queries. `kind` is `semantic` (paraphrase, little word overlap) or `keyword` (exact token such as an error code or booking reference). `expected` lists every relevant document. 6 queries are non-English (`lang`); the MVP claims English only (PRD §5), so they are reported separately.

Metrics (Phase 2 onward, `scripts/eval_relevance.py`): recall@10 (share of expected documents found in the top 10, averaged per query) and MRR (reciprocal rank of the first relevant document).
