# Phase 1 — Local data foundation

## Task brief

- **Phase:** Phase 1. Exit gate: tests prove item/chunk metadata and vector records remain consistent after retries, crashes, deletion, and index rebuild.
- **Acceptance criteria:**
  - SQLite schema and migrations for items, chunks, jobs, sources, exclusions, schema version (`design.md` §5), plus `vector_outbox` and `tombstones`.
  - Stable IDs (§12), content hashes, item states and transitions (§10), job states, retry semantics (3 retries, 10 s / 60 s / 5 min), consistency checks.
  - LanceDB integration: insert, search, delete, rebuild; one table per model and dimension.
  - Physical deletion (§7): `secure_delete`, FTS5 optimize, WAL checkpoint, LanceDB compaction + old-version cleanup; marker-scan regression test.
  - FTS5 index; deterministic fixture corpus with about 50 labeled queries, including a small non-English set.
- **Files:** `omnirecall/storage/{db,migrations/0001_initial.sql,states,repository,vectors,deletion,consistency}.py`, `omnirecall/settings.py`, `omnirecall/jobs/queue.py`, `tests/test_storage_*.py`, `tests/test_deletion.py`, `tests/test_consistency.py`, `tests/test_jobs.py`, `tests/fixtures/eval/{corpus,queries}.jsonl`, `tests/support.py` (test-only deterministic embedder).
- **Tests:** migrations apply once and are idempotent; state transitions accept allowed and reject others; duplicate content hash is not re-ingested; retries produce identical chunk IDs and no duplicates; crash between SQLite commit and LanceDB write is recovered from the outbox; orphan vectors are removed; missing vectors are re-created; rebuild restores identical search results; delete removes rows from every store and a unique marker cannot be found in raw SQLite, WAL, or LanceDB files; job retry backoff and max attempts; restart resets running jobs.
- **Privacy impact:** defines where content is stored. Deleted items keep only ID, source type, status, and timestamps; content hash, label, URI, and media URI are cleared. No content in logs.
- **Defaults used:** job retries 3 with backoff 10 s, 60 s, 5 min; queue capacity 1,000; worker concurrency 2; chunker 500/50 (stored version only); vector/keyword top-K 50.

## Schema additions (logged as D-017)

`design.md` §3 says settings live in SQLite and PRD §5 requires per-source metadata (MIME type, modified time, duration, display), but §5 had no place for them. Added in migration 0001 and to `design.md` §5: `settings` table; `items.metadata_json`, `items.skip_reason`, `items.media_status`.

## End report

- **Done:**
  - Migration runner (contiguous versions, one transaction each, refuses a newer schema) and `0001_initial.sql` with every §5 table, FTS5 external-content index with triggers, CHECK constraints for states.
  - IDs and formats per §12; item state machine per §10 enforced in code and schema; job states.
  - `Repository` (items with content-hash dedup, skipped items with hash + reason only, chunks with idempotent replace, FTS keyword search limited to `indexed` items, outbox, jobs with atomic claim / backoff / cancel / restart recovery, tombstones, sources, exclusions).
  - `VectorStore` (LanceDB, table `chunks__<model>__<dim>`, merge-insert upsert, delete by chunk or item, cosine search, embedding-cache lookup by text hash, compaction + immediate old-version cleanup).
  - `IndexWriter` (embedding cache, outbox apply, crash replay), `DeletionService` (tombstone → vectors → SQLite/FTS → media → FTS optimize + LanceDB cleanup + WAL checkpoint → verify → `deleted`; clear-all with VACUUM), `ConsistencyService` (verify, reconcile, rebuild via side table), `JobRunner` (persistent, bounded workers, 3 retries at 10 s / 60 s / 5 min, permanent-error fast fail, sanitized error codes).
  - Evaluation corpus: 44 documents, 52 labeled queries (6 non-English).
- **Commands run:**
  - `uv run pytest -q` → 47 passed (16 storage, 9 consistency, 5 deletion, 7 jobs, 1 fixtures, 9 RPC).
  - `uv run ruff check .` → all checks passed. `uv run ruff format .` → clean. `uv run mypy` → no issues (29 files).
- **Exit gate evidence:** `test_retry_does_not_duplicate_vectors`, `test_crash_between_sqlite_and_lancedb_is_recovered`, `test_outbox_delete_replayed_after_crash`, `test_orphan_and_missing_vectors_are_repaired`, `test_rebuild_preserves_results`, `test_rebuild_after_vector_table_loss_reembeds`, `test_delete_is_physical`, `test_interrupted_delete_resumes`.
- **Not done or skipped:** these tests use a deterministic test embedder; the real MiniLM model is exercised from Phase 2 (relevance baseline). No desktop changes in this phase.
- **Bugs:** none opened. OR-004 and OR-017 have implementation and tests; they stay OPEN until the Phase 6 fault-injection run and the release checklist.
- **Docs updated:** `design.md` §5 (settings table, item columns, deleted-row contents) and §7 (LanceDB transaction-log note); `decisions.md` D-017, D-018.
