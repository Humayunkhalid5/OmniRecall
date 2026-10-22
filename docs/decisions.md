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

### D-027 — Screenshots are taken by the shell and handed over as files
- **Date:** 2026-10-22
- **Decision:** the Rust shell takes screenshots, because it owns OS permissions, the frontmost app, idle time, and lock state (rules.md §2.2).
  - **Platforms:** `xcap` on Windows (GDI) and macOS (CoreGraphics). Linux X11 uses `x11rb` (RandR monitors, `GetImage`, and the ScreenSaver extension for idle time).
  - **Before each capture:** the shell skips the frame when the screen is locked, the user is idle past the setting, macOS Screen Recording is off, or OmniRecall's own window is in front. Otherwise it asks the engine's `capture.screenshot_check`, which checks capture state, Tesseract availability, app exclusions (fail closed when the app is unknown), and queue room.
  - **After each capture:** per display, the shell computes a 64-bit DCT perceptual hash. A frame within Hamming distance 5 of the last accepted frame for that display is dropped without being written.
  - **Hand-off:** a new frame is written as a PNG into `media/incoming/` (user-only permissions, written under a temporary name and renamed). The shell then calls `capture.screenshot`, which re-checks everything, moves the file into `media/screenshots/YYYY/MM/`, and queues the item. The engine removes the incoming file in every case and clears leftovers at start.
  - **Wayland:** reported as unsupported. The portal asks the user on every capture, which periodic capture cannot honour (OR-015).
- **Reason:**
  - The engine never reads an excluded app's screen, and an unchanged screen costs no disk write or OCR.
  - The file hand-off keeps multi-megabyte images out of the JSON-RPC channel.
  - The engine's re-check means either side alone can stop capture.
- **Docs updated:** `design.md` §3, §6, §11; `support-matrix.md`.
- **Replaces:** none.

### D-028 — Frames dropped after OCR leave no trace
- **Date:** 2026-10-22
- **Decision:** after OCR, a screenshot is dropped when:
  - it has no text;
  - its text matches a text exclusion;
  - its text looks like a secret (`screenshot_detect_secrets`, on by default, best effort);
  - its text is the same as the last accepted frame on that display. In this case the earlier item gets `last_seen_at` instead.

  A dropped frame's row, job, image, and thumbnail are deleted. It does not become a `skipped` item. Every skip, before or after OCR, is counted per session in memory and logged as an outcome code only.
- **Reason:**
  - A `skipped` row per unchanged frame would add thousands of rows a day while a video plays.
  - A sensitive frame must not keep even a hash (consistent with D-022).
  - Counts and outcome logs are enough to show the user that filtering happened (implementation plan: "record why a frame was skipped without storing the image").
- **Docs updated:** `design.md` §6.
- **Replaces:** none.

### D-029 — OCR details and image import
- **Date:** 2026-10-22
- **Decision:**
  - **Engine:** Tesseract 5 (`eng`), found through `OMNIRECALL_TESSERACT_CMD` (set by the packaged app in Phase 6) or `PATH`.
  - **Image preparation:** only the first frame is read, after EXIF rotation. Transparency is flattened onto white, the image is converted to grayscale, and images narrower than 1,600 px are upscaled (at most 3x).
  - **Limits:** 100 MP, enforced before decoding. OCR times out after 120 s.
  - **Image import:** PNG, JPEG, WebP, BMP, TIFF, and GIF import as `file` items with OCR text. An image with no text fails with `extraction_empty`.
  - **Tesseract missing:** the item fails with `ocr_unavailable`, and screenshot capture is refused.
  - **Recorded per item:** the OCR engine and version.
- **Reason:** Tesseract does best near a 30 px x-height. UI text in 1x screenshots is smaller, so it is upscaled. On the fixtures and real 1280x800 screens, the median OCR time is 0.45 s on REF-CI-LINUX.
- **Docs updated:** `design.md` §3.
- **Replaces:** none.

### D-030 — Text-only mode, thumbnails, and inactivity pause
- **Date:** 2026-10-22
- **Decision:**
  - **Text-only mode:** removes each new screenshot's image (and thumbnail) as soon as the item is indexed, and marks its media `pruned`.
  - **Thumbnails:** otherwise a 640 px WebP preview (`<hash>.thumb.webp`) is kept next to the PNG. It counts toward the media cap and is removed with the image.
  - **Inactivity pause:** defaults to 5 minutes without keyboard or mouse input (`pause_on_idle_s` = 300; 0 turns it off).
  - **Lock detection:** Windows uses `OpenInputDesktop`, macOS uses `CGSSessionScreenIsLocked`, and X11 uses the screen saver state.
- **Reason:**
  - The PRD requires a pause on lock or inactivity "where supported", and `design.md` §11 had no inactivity value.
  - 5 minutes matches common screen-lock defaults.
- **Docs updated:** `design.md` §11, §13.
- **Replaces:** none.

### D-031 — Audio is decoded by a bundled Rust helper, not PyAV or ffmpeg
- **Date:** 2026-10-22
- **Decision:**
  - **Helper:** `omnirecall-audio-decode` (`services/audio-decoder`), a small Rust program built on symphonia 0.6.1 and rubato 5.0.1. The engine runs it as a child process, as it runs Tesseract.
  - **Interface:**
    - `probe <path>` prints one JSON line (codec, sample rate, channels, duration).
    - `decode <path> <max-seconds>` streams 16 kHz mono 32-bit float samples on stdout.
    - `--version`.
    - Errors are one JSON line `{"code","message"}` on stderr with exit code 2.
  - **Formats:** WAV, MP3, M4A (AAC or ALAC), AAC, FLAC, Ogg Vorbis, AIFF, and CAF. Opus is not supported and fails with `unsupported_codec`.
  - **Limits:** the recording length limit is checked from the container's duration before decoding and again while decoding. A file with more than 1,000 damaged packets fails with `malformed_file`.
  - **Where the engine finds it:** `OMNIRECALL_AUDIO_DECODER`, then next to the engine executable (packaged app), then the checkout's release build (from source only), then `PATH`. A missing helper fails the item with `audio_decoder_unavailable`.
- **Reason:**
  - PyAV wheels bundle an FFmpeg build that includes GPL x264 and x265, which would make the engine bundle GPL. Calling a system `ffmpeg` is not something users have on Windows or macOS.
  - symphonia (MPL-2.0) and rubato (MIT) are permissive, pure Rust, and need no system libraries. The helper is about 3 MB.
  - A child process keeps a crash or a hostile file out of the engine, and killing it is how cancellation stops decoding.
  - Measured: a one-hour MP3 decodes and resamples in about 4 s with an 11 MB peak (`measurements.md` Phase 5).
- **Docs updated:** `design.md` §3, `licenses.md`, `support-matrix.md`.
- **Replaces:** none.

### D-032 — Transcription with whisper.cpp `base`, in 5-minute windows
- **Date:** 2026-10-22
- **Decision:**
  - **Engine and model:** whisper.cpp through `pywhispercpp` 1.5.1, model `ggml-base.bin`, installed by the user in Settings (download or file). It is loaded only from that local path, never by name. The language is detected per window.
  - **Threads and memory:** at most 4 threads. The model is loaded on the first recording and unloaded after 5 minutes idle, like the embedding model.
  - **Windows:** audio is transcribed in 300 s windows. Each cut falls at the quietest 100 ms within 10 s of the window edge, so words are not split. Timestamps are made absolute.
  - **Silenced output:** whisper.cpp's own log output is routed to a function that discards it, so no transcript text reaches stderr or the log.
  - **Missing model:** audio items fail with `transcription_model_missing`, and they are queued again automatically when the model is installed.
  - **Progress:** `items.progress` notifications at most once per second, with seconds done, total, and percent.
  - **Cancellation:** a running transcription checks whether its job was cancelled at most every 0.5 s and stops within one segment.
- **Reason:**
  - `base` is multilingual, MIT-licensed, 142 MB, and the plan's Phase 0 candidate (design §3).
  - Bounded windows keep memory flat for a 2-hour recording and give progress and cancellation natural checkpoints.
- **Docs updated:** `design.md` §3.
- **Replaces:** none.

### D-033 — Transcript cleanup and timed passages
- **Date:** 2026-10-22
- **Decision:**
  - **Cleanup:** remove non-speech tags such as `[Music]`, `(laughs)`, or `*applause*` (up to 60 characters) and music symbols. Collapse a phrase of 1 to 8 words repeated more than 3 times in a row to one copy (a known Whisper loop). Merge identical consecutive segments.
  - **Text:** one segment per line, chunked with the normal 500/50 chunker.
  - **Timestamps:** each chunk stores `start_ms` and `end_ms`, taken from the segments it overlaps (migration `0002_chunk_timestamps.sql`). Search results and item details return them, and the UI shows "at 1:02 in the recording" and a time range for each passage.
- **Reason:** design §3 says to keep timestamps when the engine provides them. Without cleanup, silence and music produce tags and loops that pollute keyword search.
- **Docs updated:** `design.md` §3, §5.
- **Replaces:** none.

### D-034 — Search filter by format
- **Date:** 2026-10-22
- **Decision:** `search` accepts `filters.formats`, matched against the item's `metadata.format`. The UI's "Audio notes" source option uses `["audio"]`. Audio files import as `file` items with `format: "audio"`, so the existing source types are unchanged.
- **Reason:** audio arrives through the same file import as documents and images, and a new source type would have needed a migration of every source filter.
- **Docs updated:** `design.md` §3 (Retrieval).
- **Replaces:** none.

### D-035 — A damaged search index is discarded and rebuilt from SQLite
- **Date:** 2026-10-22
- **Decision:** the LanceDB table and the FTS5 index are derived data. When the vector table cannot be read in full (damaged or missing data files, manifests, or the whole table), the engine deletes what is left and re-embeds every chunk from SQLite: at startup in reconciliation, and while running when a vector search or write fails. Search meanwhile returns keyword results with `semantic_unavailable_reason: "index_repairing"`, the UI says the index is being repaired and nothing is lost, and `index.repaired` re-runs the search when it is done. Without the model the damaged table is kept and reported until the model is installed. A damaged FTS5 index is rebuilt; if even the rebuild fails, its shadow tables are reset from a fresh template first.
- **Reason:** SQLite holds every chunk's text, so nothing in either index is irreplaceable, and a partial repair would leave results that disagree with the database.
- **Docs updated:** `design.md` §7 (Consistency); `threat-model.md` (T9); `troubleshooting.md`.
- **Replaces:** none.

### D-036 — A damaged database opens in recovery mode
- **Date:** 2026-10-22
- **Decision:** before starting, the engine runs `PRAGMA quick_check` on its database (read-only). Only SQLite's own damage codes (`SQLITE_CORRUPT`, `SQLITE_NOTADB`) count; a locked file, a full disk, or a permission error is not damage and is left to fail the normal start. On damage the engine starts in recovery mode, which serves `health`, `status`, `database.recover`, and `database.reset`, and nothing else. The app shows the choice; nothing changes until the user confirms one.
  - **Recover:** copy every readable row of settings, sources, exclusions, items, tombstones, and chunks into a new database with the current schema, in rowid ranges, skipping unreadable ranges. Items whose chunks were lost are re-read from disk (imported files) or marked failed with `recovery_lost_text` (everything else), never shown as indexed with missing text. Media no recovered item refers to is deleted. Capture is turned off, because exclusions may have been lost. Indexes, vectors, and jobs are rebuilt by the normal start.
  - **Start over:** delete the database, vectors, and all stored media. Imported originals are never touched.
  - **Newer version:** a database whose schema is newer than the engine (`schema_too_new`) opens the same screen with no actions, so a downgrade cannot destroy data.
  - One action per start; then the app restarts the engine.
- **Reason:** SQLite is the only copy of the text, so it cannot be rebuilt, and starting on a damaged file risks failing in the middle of a write. Offering recovery for a lock or a full disk would invite a destructive choice for a temporary problem.
- **Docs updated:** `threat-model.md`; `troubleshooting.md`.
- **Replaces:** none.

### D-037 — Packaging: engine one-dir folder in the app's resources
- **Date:** 2026-10-22
- **Decision:** installers carry the PyInstaller one-dir engine as the Tauri resource folder `engine/`, with the audio decoder beside the executable. Tesseract is bundled in `engine/tesseract/` on Windows (UB Mannheim build) and macOS (Homebrew build, libraries made relative with `dylibbundler`, signed ad hoc); Linux packages depend on the distribution's `tesseract-ocr` and English data. The engine prefers a bundled Tesseract and points `TESSDATA_PREFIX` at its data. Targets: NSIS (Windows), .dmg (macOS, Apple Silicon), .deb and .rpm (Linux; no AppImage, which cannot depend on Tesseract). The release workflow builds, installs, reinstalls, and uninstalls each package on its OS. Installers are unsigned until signing accounts exist.
- **Reason:** a one-dir engine starts without unpacking itself on each launch (the one-file mode would). Tauri's `externalBin` takes only single files, so the folder goes in resources. Bundling Tesseract on Linux would duplicate a library every distribution ships and updates.
- **Docs updated:** `release.md`; `licenses.md`; `design.md` §9 (Deployment).
- **Replaces:** D-015's note that the sidecar sits next to the app executable.

### D-038 — Speech-to-text is gated on findability, and measured on real speech
- **Date:** 2026-10-22
- **Decision:** the real-model gate for audio (Phase 5 exit gate, run by the `Real models` CI job) is that every spoken fixture, transcribed by whisper.cpp `base` and indexed with the real MiniLM model, is the top search result for a paraphrased question about it (`test_real_models_make_every_recording_findable`). Each fixture must also be detected as English with a word error rate under 35%, as a sanity bound. WER is computed after the usual normalization (lower case, no punctuation, number words as digits; `tests/wer.py`). Accuracy itself is a measurement, not a gate: `scripts/eval_transcription.py` reports WER and speed on the fixtures and on a LibriSpeech sample of real read speech, recorded in `measurements.md`.
- **Reason:** the Phase 5 test's "under 25% on each fixture" was set before any real run. The first run showed two problems with it. The metric counted "forty" against Whisper's "40" as an error, which speech benchmarks normalize away. And the fixtures are robotic espeak-ng voices: on `recipe.ogg` Whisper heard "of flour" as "sunflower" and "of sugar" as "unshover" (32% after normalization), which says more about the synthetic voice than about how people's recordings will be transcribed. What the product promises is that a recording can be found again, so that is the gate; real speech is the accuracy measure.
- **Docs updated:** `measurements.md`; `bugs.md` (OR-029).
- **Replaces:** the per-fixture 25% WER criterion in the Phase 5 report.

### D-039 — Beta feedback is a problem report the user reads, copies, or saves
- **Date:** 2026-10-22
- **Decision:** "opt-in user reports" (implementation plan, Phase 7) are a problem report built on request in Settings → Report a problem (`diagnostics.report`). It holds versions, OS, counts by state, failed items by source type and error code, model and index state, storage sizes, which capture sources are on, the number of exclusions, and up to 40 recent warnings re-filtered to codes, counts, and durations. It holds no content, paths, app names, exclusion rules, or item IDs. The app shows it in full; the user can copy it, save it to a file they name (the shell writes the engine's text, not text from the UI), or open the project's new-issue page in the browser. Nothing is ever sent by the app, and the issue URL carries no data.
- **Reason:** the PRD rules out analytics and remote services, and any upload path, even opt-in, would be a channel for content to leave the device. A report the user reads and carries over themselves keeps that boundary while giving triage the codes it needs.
- **Docs updated:** `beta.md`; `privacy.md`; `troubleshooting.md`; `SECURITY.md`; issue templates.
- **Replaces:** none.

### D-040 — Release provenance: pinned toolchains, SBOM, attestations
- **Date:** 2026-10-22
- **Decision:** a beta release is a `v*` tag; the version in the manifests stays a plain `0.1.x` and the GitHub release is marked pre-release, because .rpm and NSIS do not accept a pre-release suffix in the version. The release workflow pins Node (22.22.0), Rust (1.99.1), uv (0.11.32), and Python 3.12 through `uv.lock`; installs from lock files only; sets `SOURCE_DATE_EPOCH` from the commit; publishes `SHA256SUMS.txt`, a CycloneDX SBOM from the three lock files plus CPython and the bundled Tesseract (`scripts/sbom.py`), and a GitHub build provenance attestation for each installer. The draft release is published by a person.
- **Reason:** byte-for-byte reproducible builds are not verified (PyInstaller and the platform bundlers embed timestamps and paths), so the release instead records exactly which inputs built it and lets anyone check that an installer came from this repository's workflow at that commit.
- **Docs updated:** `release.md`; `beta.md`; `README.md`.
- **Replaces:** none.

### D-041 — Speech-to-text keeps greedy decoding
- **Date:** 2026-10-22
- **Decision:** whisper.cpp keeps greedy decoding (`BEAM_SIZE = 1` in `extraction/transcribe.py`). Beam search is an option of the transcriber, and the `Real models` CI job measures the other setting on every run, so the choice can be revisited on data.
- **Reason:** on the same 73 LibriSpeech recordings, beam 5 lowered corpus WER from 9.8% to 9.4%, but the mean per recording went from 12.1% to 12.3%, one recording went to 100% wrong, and transcription took about 8% longer. On the espeak-ng fixtures it went from 12.0% to 9.1%. A 0.4-point change on 481 seconds of speech, with one recording made much worse, is not a clear gain (`measurements.md`, improvement pass).
- **Docs updated:** `measurements.md`.
- **Replaces:** none.

### D-042 — Windows Tesseract is a static vcpkg build
- **Date:** 2026-10-22
- **Decision:** the Windows installer ships a single `tesseract.exe` built by `scripts/build_tesseract_windows.py`: vcpkg at a pinned commit, triplet `x64-windows-static`, with vcpkg's own tesseract port changed to build without libcurl and libarchive. LibTIFF in vcpkg is built without JBIG-KIT. English data is `tessdata_fast` 4.1.0, checked by SHA-256 (the file Debian and Homebrew ship). The build fails on any library outside a reviewed permissive list, and packaging fails if `tesseract.exe` imports any DLL that is not part of Windows. The release workflow caches vcpkg's binary packages.
- **Reason:** the UB Mannheim build used before loaded libcurl and, through it and LibTIFF, five copyleft DLLs (OR-030). OmniRecall passes Tesseract a local file and plain English data, so neither URL input nor zipped models are needed. The result is one executable with ten permissive libraries, and the Windows installer is 121 MiB instead of 144 MiB.
- **Docs updated:** `licenses.md`; `release.md`; `third_party_licenses/README.md`; `bugs.md` OR-030.
- **Replaces:** the Windows part of D-037 (UB Mannheim build from Chocolatey).

