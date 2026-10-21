# Phase 2 — Text import to search vertical slice

## Task brief

- **Phase:** Phase 2. Exit gate: user imports a fixture corpus, queries it semantically, opens source details, deletes an item, and confirms it no longer appears. Baseline recall@10, MRR, and p95 search latency at 10,000 chunks recorded on the reference machine.
- **Acceptance criteria:**
  - Paste/import of plain text and supported documents; supported formats declared in the UI and tested (PRD §5).
  - Normalize and chunk text (500/50, word boundaries, offsets, token-length check); embed locally in batches with the embedding cache; store metadata and vectors.
  - Hybrid retrieval: FTS5 + vector, reciprocal rank fusion (k = 60), joined to SQLite, `indexed` only; snippet, source, timestamp, relevance indication without implying certainty; "no strong match" state; empty / malformed / too-long queries fail gracefully; search usable during ingestion.
  - Model setup: missing model produces a useful message; install requires user action and shows size and license; checksum verified.
  - UI: search, results, item detail, import (dialog, drop, paste), queue progress, delete, empty / loading / error / engine-unavailable / model-missing states; keyboard navigation and labels.
- **Files:** engine `extraction/{text,documents}.py`, `chunking/chunker.py`, `ingestion/{service,pipeline}.py`, `retrieval/search.py`, `models.py`, `api/schemas.py`, `app.py`; desktop `src-tauri/src/{lib,commands}.rs`, `src/**` (React UI); `scripts/eval_relevance.py`, `scripts/bench_search.py`; tests for each.
- **Tests:** chunker offsets/overlap/word boundaries/token split; extractors for each format plus malformed and oversized files; pipeline success, retry idempotency, failure states; search fusion, filters, deleted items hidden, invalid queries, FTS query escaping; model checksum mismatch; RPC end-to-end import → search → get → delete; UI component tests (search states, detail, delete confirmation, accessibility via axe).
- **Privacy impact:** imported text and paths are stored locally (SQLite); file paths are shown only in the item detail. Queries are not stored. Logs carry IDs, counts, and codes only. Network: only the user-started model download.
- **Defaults used:** max file 100 MB, max PDF pages 500, max query 1,000 chars, chunk 500/50, batch 32, vector and keyword top-K 50, RRF k = 60, results 20, model idle unload 5 min, worker concurrency 2, queue capacity 1,000.

## End report

- **Done:**
  - Extractors for plain text, Markdown, CSV/TSV, JSON, HTML, PDF (text layer), and DOCX, with binary, encrypted, malformed, empty, and oversized files failing with clear codes (D-021). Text normalization (Unicode NFC, control characters, whitespace).
  - Chunker: 500/50 characters on word boundaries with source offsets; any chunk over 256 model tokens is split again.
  - Import of pasted text, files, and folders (hidden files and symlinks skipped, 10,000-file cap), content-hash dedup, persistent jobs. Pasted text is staged to a payload file and deleted once indexed.
  - Pipeline plus a batching vector worker; items reach `indexed` only after their vectors are written (D-019).
  - Hybrid search: quoted FTS5 terms without stopwords, cosine vector search, RRF k = 60, results grouped per item, `indexed` items only, filters (source type, time range, app, path prefix), highlighted snippets, relevance labels, `no_strong_match` (D-020). Search works while indexing and with keyword-only fallback when the model is missing.
  - Model setup: download over HTTPS or install from a local file, archive and per-file checksums, staged install, progress and cancel. Nothing downloads without a user action.
  - Engine API: import, list, get, delete, retry, cancel, search, index verify / rebuild / clear (with confirmation), settings get / update, models, formats.
  - Shell: allow-listed `engine_call`, file and folder dialogs, OS drag-and-drop import, model install from file, open original (path taken from the engine record and checked), reveal data folder (D-016).
  - UI: search with source filter, model-missing notice, labelled results with the reason they matched, weak matches collapsed behind a button when stronger evidence exists, no-strong-match notice, no-results hint; item detail with open original and confirmed permanent delete; library with import, paste dialog, drop results, status counts, filters, retry, cancel, supported-format list; settings with models (size, license, source), limits, storage use, data folder, not-encrypted notice, index check / rebuild / delete-everything with confirmation; engine starting / restarting / failed screens with restart and a sanitized code. Light and dark themes, visible focus, labelled controls.
- **Commands run:**
  - Engine: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` → clean (37 files). `uv run pytest -q` → 84 passed, 1 skipped (the real-model archive test, which needs `OMNIRECALL_TEST_MINILM_ARCHIVE`).
  - Shell: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` → clean. `cargo test` → 8 passed.
  - UI: `npm run format:check`, `npm run lint`, `npm run typecheck` → clean. `npm test` → 13 passed, including axe checks (colour contrast excluded in jsdom) on the engine-failed, search, detail, library, and settings screens. `npm run build` → 251 KB JS (78 KB gzip).
  - `scripts/eval_relevance.py` in hybrid, vector, and keyword modes; `scripts/bench_search.py --chunks 10000`. Results in `docs/measurements.md`.
- **Exit gate evidence:**
  - Automated: `test_engine_flow.py::test_text_import_search_detail_delete` (import → semantic search → detail → delete → gone from search and from the stores) and the UI delete-confirmation test.
  - Live run of the debug desktop build under Xvfb with the real engine and model: 20 fixture documents imported, the query "how do I take back my last commit" returned "git undo commit" as a strong match, the detail panel opened, the item was deleted through the confirmation dialog, and the same search then showed only weak matches with the no-strong-match notice. Killing the engine process mid-session led the supervisor to restart it. The engine log held IDs, counts, and event names only; none of the imported text or queries.
  - Baseline: hybrid recall@10 0.982, MRR 0.958; 10,000 chunks search p95 23.3 ms (REF-CI-LINUX).
- **Found and fixed during the live run:** OR-021 (engine kept running after a `shutdown` request while stdin was open); stopwords and mid-word fragments were highlighted ("do" inside "undo"); the primary button lost its contrast on hover; the result count included collapsed weak matches; the library actions column broke the table layout; the audio model was offered for download although audio import is a Phase 5 feature (now hidden until then).
- **Not done or skipped:**
  - File and folder import through the native dialogs, drag-and-drop, and "open original" were not driven in the live run (no way to operate the GTK dialog here). Their engine side is covered by `test_engine_flow.py`; the shell side by type checks and the allow-list test.
  - The 10,000-chunk numbers come from a cloud VM, not a laptop; Phase 6 repeats them on real hardware alongside the 100,000-chunk target.
  - Peak engine memory during bulk indexing was 743 MB. There is no PRD memory target to compare against, and no memory claim is made.
  - Relevance thresholds were tuned on the same corpus they were measured on; Phase 6 re-runs the baseline.
- **Bugs:** OR-021 opened and closed with a regression test.
- **Docs updated:** `decisions.md` D-019, D-020, D-021; `measurements.md` Phase 2; `bugs.md` OR-021.
