# OmniRecall — Decisions Log

**Purpose:** record every settled choice so it is not reopened without new evidence. Newest entries go at the bottom. A later entry may replace an earlier one by naming it under **Replaces**.

**Entry format:**

### D-XXX — Short title
- **Date:** YYYY-MM-DD
- **Decision:** what was decided.
- **Reason:** why.
- **Docs updated:** files and sections changed.
- **Replaces:** earlier decision ID, or none.

---

### D-001 — Document precedence
- **Date:** 2026-10-21
- **Decision:** when documents conflict, `rules.md` wins over `prd.md`, which wins over `design.md`, then `implementation_plan.md`, then `decisions.md`. `bugs.md` is status only.
- **Reason:** remove ambiguity for contributors and coding agents.
- **Docs updated:** `rules.md` §0.
- **Replaces:** none.

### D-002 — FTS5 hybrid retrieval is P0
- **Date:** 2026-10-21
- **Decision:** the SQLite FTS5 keyword index and rank fusion with vector search are MVP (P0). Explainable ranking stays P1. The search API accepts optional filters from MVP; the filter UI is P1.
- **Reason:** the PRD listed FTS5 as P1 while the plan built it in Phase 1-2.
- **Docs updated:** `prd.md` §4.
- **Replaces:** none.

### D-003 — Engine IPC is JSON-RPC over stdio
- **Date:** 2026-10-21
- **Decision:** the Python engine runs as a Tauri sidecar speaking versioned JSON-RPC 2.0 over stdin/stdout and opens no network port. Loopback HTTP is a fallback only.
- **Reason:** removes the local network attack surface (OR-009) and token handling.
- **Docs updated:** `design.md` §2, §3, §7; `implementation_plan.md` §1, §6; `rules.md` §2; `bugs.md` OR-009.
- **Replaces:** none.

### D-004 — Single schema and item states
- **Date:** 2026-10-21
- **Decision:** `design.md` §5 is the only schema definition. Item states add `skipped` and `deleting`, with transitions in `design.md` §10. New tables: `vector_outbox`, `tombstones`.
- **Reason:** the schema was duplicated and had drifted; deletion needed a visible pending state.
- **Docs updated:** `design.md` §5, §10; `implementation_plan.md` §5; `prd.md` §7.
- **Replaces:** none.

### D-005 — Default values, IDs, and formats
- **Date:** 2026-10-21
- **Decision:** adopt the starting defaults in `design.md` §11 and the ID, hash, and timestamp formats in `design.md` §12 (UUIDv7, deterministic chunk IDs, SHA-256, ISO 8601 UTC).
- **Reason:** unspecified numbers forced guesswork. Defaults are tuned only with measurements.
- **Docs updated:** `design.md` §6, §11, §12.
- **Replaces:** none.

### D-006 — Retention policy and search history
- **Date:** 2026-10-21
- **Decision:** keep screenshot images 7 days, then text only; cap app media at 5 GB, pruning oldest first; keep text items until deleted; do not store search queries by default. All values are configurable.
- **Reason:** `rules.md` referred to an undefined retention policy and storage had to be bounded.
- **Docs updated:** `prd.md` §4, §6; `design.md` §7, §11, §13.
- **Replaces:** none.

### D-007 — Physical deletion
- **Date:** 2026-10-21
- **Decision:** deletion uses SQLite `secure_delete`, FTS5 optimize, a WAL checkpoint, and LanceDB compaction with old-version cleanup before an item is reported deleted.
- **Reason:** both stores otherwise keep deleted bytes on disk (OR-017).
- **Docs updated:** `design.md` §7; `prd.md` §6; `bugs.md`.
- **Replaces:** none.

### D-008 — Export format
- **Date:** 2026-10-21
- **Decision:** export is a zip with `manifest.json`, `items.jsonl`, `chunks.jsonl`, and `media/`. Vectors are rebuilt on restore, not exported.
- **Reason:** smaller exports that survive embedding model changes.
- **Docs updated:** `design.md` §13; `implementation_plan.md` §6.
- **Replaces:** none.

### D-009 — Engine candidates and language scope
- **Date:** 2026-10-21
- **Decision:** Phase 0 compares RapidOCR (ONNX) and Tesseract 5 for OCR and validates `whisper.cpp` with a `base` model. The MVP officially supports English; a multilingual embedding model is a P1 candidate.
- **Reason:** "selected per platform" gave no starting point; all-MiniLM-L6-v2 is mainly English.
- **Docs updated:** `design.md` §3; `implementation_plan.md` §1, Phase 0; `prd.md` §5.
- **Replaces:** none.

### D-010 — Phase order and early measurement
- **Date:** 2026-10-21
- **Decision:** Phase 3 is clipboard plus shared privacy controls, Phase 4 images and screenshots, Phase 5 audio. A labeled evaluation corpus starts in Phase 1, with a relevance and latency baseline at the Phase 2 exit gate.
- **Reason:** clipboard reuses the text pipeline and privacy controls must exist before screen capture; tuning needs numbers.
- **Docs updated:** `implementation_plan.md` §4.
- **Replaces:** none.

### D-011 — Pipeline efficiency and vector tables
- **Date:** 2026-10-21
- **Decision:** batch embeddings, an embedding cache keyed by text hash and model, OCR-text dedup for screenshots, on-demand model loading with idle unload, and one LanceDB table per embedding model and dimension.
- **Reason:** lower CPU and battery use; safe model upgrades and rollback.
- **Docs updated:** `design.md` §3; `implementation_plan.md` Phase 2.
- **Replaces:** none.

### D-012 — OCR engine: Tesseract 5
- **Date:** 2026-10-21
- **Decision:** use Tesseract 5 (`eng`) through `pytesseract` behind the OCR adapter interface. RapidOCR is not shipped.
- **Reason:** Phase 0 spike: mean CER 0.006 vs 0.068 (RapidOCR dropped word spaces, which breaks keyword search), 3–7× faster, about 36 MB vs 458 MB memory, and 245 MB smaller engine bundle. Cost: the Tesseract binary must be packaged per OS (Windows build in Phase 6).
- **Docs updated:** `docs/measurements.md`, `docs/licenses.md`.
- **Replaces:** none (resolves the D-009 comparison).

### D-013 — Embedding model distribution and validation
- **Date:** 2026-10-21
- **Decision:** pin all-MiniLM-L6-v2 at upstream revision `7dbbc903…`; install from the Chroma ONNX mirror archive verified by SHA-256 (archive and per-file), by explicit user action or from a local archive file. Mean pooling + L2 normalization, max 256 tokens.
- **Reason:** validated license (Apache-2.0), output dimension 384, tokenizer compatibility, normalization, and semantic sanity on the reference machine. A checksummed archive keeps the model out of the installer (OR-018).
- **Docs updated:** `docs/licenses.md`, `docs/measurements.md`, `omnirecall/model_manifests/`.
- **Replaces:** none.

### D-014 — Transcription runtime: pywhispercpp
- **Date:** 2026-10-21
- **Decision:** use `pywhispercpp` 1.5.1 (MIT, prebuilt whisper.cpp wheels) with the `ggml-base` model, verified by its published SHA-1. Models are always loaded from a local path, never by name (by-name loading downloads).
- **Reason:** in-process whisper.cpp without a separate build toolchain; wheels exist for Windows, Linux, and Apple Silicon. Accuracy is still to be measured (no model download was possible in the build environment).
- **Docs updated:** `docs/licenses.md`, `docs/measurements.md`.
- **Replaces:** none.

### D-015 — Engine runtime and packaging
- **Date:** 2026-10-21
- **Decision:** Python 3.12, dependencies pinned with `uv` (`uv.lock`); the release sidecar is a PyInstaller one-dir build. Development runs the engine from source with `OMNIRECALL_ENGINE_SOURCE=<path> ` (`uv run --frozen`). Model manifests live inside the engine package (`omnirecall/model_manifests/`) so the frozen build carries them; `models/README.md` points there.
- **Reason:** 3.12 has wheels for every pinned native dependency; PyInstaller cold start measured at about 150 ms.
- **Docs updated:** `docs/measurements.md`, `README.md`.
- **Replaces:** none.

### D-016 — Narrow shell command surface
- **Date:** 2026-10-21
- **Decision:** the UI calls the engine only through an allow-list of methods. Methods that take filesystem paths are never exposed to the UI: file pickers, save dialogs, drag-and-drop, and "open original" run in Rust, which obtains the path from the OS and passes it to the engine.
- **Reason:** design.md §3 ("no direct access to … arbitrary filesystem paths") and path-traversal control in §7.
- **Docs updated:** `README.md` (architecture).
- **Replaces:** none.

### D-017 — Schema additions for settings and source metadata
- **Date:** 2026-10-21
- **Decision:** migration 0001 adds a `settings` table and `items.media_status`, `items.metadata_json`, `items.skip_reason`, beyond the original §5 list. Deleted items keep only ID, source type, timestamps, and status.
- **Reason:** `design.md` §3 stores settings in SQLite and PRD §5 requires per-source metadata, but §5 had no place for either; §13 needs a `pruned` media state; `skipped` needs a reason. Clearing content fields on delete also frees the unique content hash for re-import.
- **Docs updated:** `design.md` §5.
- **Replaces:** none.

### D-018 — Outbox ordering and recovery
- **Date:** 2026-10-21
- **Decision:** the pipeline embeds first, then commits chunks, FTS rows, and outbox entries in one SQLite transaction, then writes LanceDB and marks the entries done. An item becomes `indexed` only after that. Pending entries are replayed at startup (re-embedding from SQLite text through the embedding cache). Vector rebuild writes a side table first, then replaces the live table, because LanceDB OSS cannot rename tables.
- **Reason:** keeps SQLite authoritative (rules §2.3) and makes every crash point recoverable (OR-004).
- **Docs updated:** `docs/reports/phase-1.md`.
- **Replaces:** none.

### D-019 — Vector writes in a batching worker
- **Date:** 2026-10-21
- **Decision:** a pipeline job extracts and chunks, then commits chunks, FTS rows, and outbox entries in one SQLite transaction and leaves the item `processing`. A dedicated vector worker drains the outbox in batches across items (up to 256 entries, embedded 32 at a time through the embedding cache), writes LanceDB, and only then marks each fully written item `indexed`. LanceDB is compacted and old versions cleaned every 64 writes.
- **Reason:** one LanceDB write per item produced thousands of versions and about 4.5 items/s; batching gave a 10,000-chunk build in 141 s (`docs/measurements.md`). SQLite stays authoritative and every crash point is still recovered by outbox replay.
- **Docs updated:** `docs/measurements.md`, `docs/reports/phase-2.md`.
- **Replaces:** the "embeds first" ordering in D-018. The rest of D-018 (startup replay, side-table rebuild) stands.

### D-020 — Keyword query construction and relevance labels
- **Date:** 2026-10-21
- **Decision:** the FTS5 query quotes each term and ORs them, after dropping a fixed English stopword list (unless the query is only stopwords). Results are labeled **strong** when cosine similarity is at least 0.45, or at least 0.30 with a keyword hit; **possible** when similarity is at least 0.30 or there is a keyword hit; otherwise **weak**. The response sets `no_strong_match` when no result is strong, and the UI then says no strong match was found.
- **Reason:** quoting neutralizes FTS5 operators in user text; stopwords otherwise dominate rank fusion. The thresholds were calibrated on the Phase 2 evaluation run (strong was correct 44/44). Labels describe evidence, not certainty (rules §5.7).
- **Docs updated:** `docs/measurements.md`.
- **Replaces:** none.

### D-021 — Phase 2 document formats
- **Date:** 2026-10-21
- **Decision:** supported formats are plain text (`.txt`, `.text`, `.log`), Markdown, CSV/TSV, JSON (flattened to `path: value` lines), HTML (visible text only; scripts, styles, and head skipped), PDF (text layer only, encrypted PDFs refused, 500-page limit), and Word `.docx` (paragraphs and tables). Files with NUL bytes in the first 4 KB (other than UTF-16 with a BOM) are refused as binary. The UI shows this list from `formats.list`; images and audio join in Phases 4 and 5.
- **Reason:** PRD §5 requires a declared, tested format list. Pure-Python extractors (`pypdf`, `python-docx`, stdlib) execute no embedded content (rules §4.4).
- **Docs updated:** `docs/reports/phase-2.md`.
- **Replaces:** none.

### D-022 — Dropped clipboard copies leave no trace
- **Date:** 2026-10-22
- **Decision:** a clipboard copy that is too large, comes from an excluded app, contains excluded text, comes from an unknown app while app exclusions exist, or looks like a secret is not stored at all: no `skipped` item, no content hash, no payload. The engine keeps per-session counts in memory, shown in Settings, and logs only the outcome. Duplicates return the existing item.
- **Reason:** a `skipped` row with a hash would reveal when a secret was copied, and a SHA-256 of a short password can be reversed by guessing. PRD §6 asks for exclusion before persistence.
- **Docs updated:** `design.md` §3 (source adapters), `docs/privacy-audit.md`.
- **Replaces:** none. The `skipped` state still covers imports that are deliberately not indexed.

### D-023 — Clipboard watching runs in the shell
- **Date:** 2026-10-22
- **Decision:** the Rust shell watches the clipboard (`arboard`), using the OS change counter on Windows and macOS and in-memory text comparison on Linux, and sends new text to the shell-only `capture.clipboard` method with the frontmost app (`active-win-pos-rs`). It reads nothing while the engine reports clipboard capture inactive, and the text present when capture becomes active is a baseline, never captured. The engine re-checks enabled and paused state on every capture. App exclusions fail closed when the app is unknown.
- **Reason:** design §3 gives OS permissions to the shell. Checking state on both sides means either one alone stops capture.
- **Docs updated:** `design.md` §3, `docs/support-matrix.md`.
- **Replaces:** none.

### D-024 — Capture indicator, pause, and closing the window
- **Date:** 2026-10-22
- **Decision:** a tray icon shows capture on, paused, or off, with Pause/Resume, Open, and Quit. The window header shows the same state with a one-click Pause or Resume. Ctrl/Cmd+Alt+Shift+P toggles global pause where the OS allows global shortcuts. Pause is stored, so it survives restarts. While any capture source is enabled and a tray exists, closing the window hides it to the tray; otherwise closing quits. Pausing is changed only through `capture.pause`, never `settings.update`, so the shell is always notified.
- **Reason:** PRD §6 requires visible status and one-action pause; background capture needs the app to outlive its window, and the tray keeps that visible.
- **Docs updated:** `docs/support-matrix.md`.
- **Replaces:** none.

### D-025 — Exclusion rules
- **Date:** 2026-10-22
- **Decision:** three rule types. `app` matches the app name case-insensitively, ignoring `.exe` and `.app`. `pattern` is literal text matched case-insensitively, never a regular expression. `path` is a folder whose files are never imported, added only through the shell's folder dialog (`exclusions.add_path` is not UI-callable, per D-016). The app's own data folder is always excluded from imports.
- **Reason:** literal matching cannot hang the engine on a pathological pattern; folder paths stay out of UI-supplied parameters.
- **Docs updated:** `design.md` §5 (`exclusions`).
- **Replaces:** none.

### D-026 — Export details
- **Date:** 2026-10-22
- **Decision:** the export zip follows §13 and adds `format`, `format_version` (1), `chunk_count`, `media_count`, and `vectors_included: false` to the manifest. Items in `deleting` or `deleted` are left out; transient payloads in `media/incoming/` are never exported. The zip is written to `<name>.partial` and renamed when complete. It is read from one SQLite snapshot, so concurrent indexing cannot produce a mixed export. The target must be outside the app data folder and is chosen in a save dialog.
- **Reason:** a deleted item must not reappear through an export, and an interrupted export must not look complete.
- **Docs updated:** `design.md` §13.
- **Replaces:** none.
