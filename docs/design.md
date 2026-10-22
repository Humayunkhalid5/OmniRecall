# OmniRecall — System Design

## 1. Design principles

1. **Local by default:** personal content stays on the device.
2. **Explicit consent:** each capture source is off until enabled.
3. **Visible control:** users can see capture state and pause immediately.
4. **Evidence over guesswork:** search results show source snippets and timestamps.
5. **Recoverable pipeline:** each stage is observable, retryable, and idempotent.
6. **Replaceable components:** capture, OCR, transcription, embedding, and storage adapters have defined interfaces.
7. **Measured claims:** performance and resource targets are verified on reference hardware.

## 2. High-level architecture

```text
┌──────────────────────────────────────────────┐
│ Tauri Desktop App                             │
│ React + TypeScript                            │
│ Search / Results / Settings / Import / Status  │
└──────────────────────┬───────────────────────┘
                       │ JSON-RPC over stdio (sidecar)
┌──────────────────────▼───────────────────────┐
│ Local Engine (supervised Python process)       │
│                                               │
│ Source adapters → bounded job queue            │
│        ↓                                      │
│ Deduplication → extraction → chunking          │
│        ↓                                      │
│ Local OCR / Whisper / ONNX embeddings          │
│        ↓                                      │
│ Retrieval: FTS5 + vector search + fusion       │
└───────────────┬─────────────────┬─────────────┘
                │                 │
       ┌────────▼──────┐  ┌───────▼──────────┐
       │ SQLite        │  │ LanceDB          │
       │ Metadata, FTS │  │ Embedding vectors│
       │ Jobs, config  │  │ Chunk IDs        │
       └───────────────┘  └──────────────────┘
                │
       ┌────────▼─────────────────────────────┐
       │ Local media directory                │
       │ Screenshots, imported files (optional)│
       └──────────────────────────────────────┘
```

Tauri/Rust owns desktop lifecycle, permissions, secure configuration, and OS-native integrations. The Python engine owns model inference and retrieval because its local ML ecosystem is mature. Keep the process boundary narrow and documented.

**IPC decision:** the Python engine runs as a Tauri sidecar and speaks versioned JSON-RPC 2.0 over stdin/stdout. It opens no network port, so there is no local endpoint for other processes or browser pages to reach and no token to manage. Diagnostic output goes to stderr, never stdout. Loopback HTTP is a documented fallback only, and if ever used it must follow the HTTP rules in `implementation_plan.md` §6.

A Rust-only backend can be reconsidered if deployment or resource measurements justify the added ML integration work.

## 3. Component responsibilities

### Desktop UI
- First-run consent and privacy education.
- Search input, filters, results, item preview, and source links.
- Import/drop zone and processing queue.
- Capture indicators and one-action pause.
- Settings for source toggles, exclusions, capture interval, model selection, storage, and diagnostics.
- No direct access to raw database files or arbitrary filesystem paths outside approved commands.

### Tauri/Rust shell
- Start and supervise the local engine; detect crash and restart with backoff.
- Use OS-supported permissions for screen capture and clipboard.
- Launch the engine as a sidecar and exchange JSON-RPC messages over stdin/stdout; open no network port.
- If the HTTP fallback is ever used, keep its per-launch secret out of UI logs and URLs.
- Validate paths passed between UI and engine.
- Package native dependencies and expose only a narrow command surface.

### Source adapters
Every adapter returns a common `IngestionEnvelope`: stable ID, source type, capture timestamp, source label/URI, media URI or text payload, content hash, and privacy classification. Adapters must honor disabled sources and exclusion rules before persistence.

- **Clipboard (Phase 3, D-023):** the shell watches the clipboard because only it can read the OS clipboard and the frontmost application. It reads nothing unless the engine reports clipboard capture as active (enabled and not paused), treats the clipboard content present when capture turns on as a baseline rather than a copy, and uses the OS change counter where one exists (Windows sequence number, macOS `changeCount`; Linux compares text). Each new copy goes to the engine's `capture.clipboard`, which re-checks capture state and applies the size limit, app and pattern exclusions, and the secret filter before anything is stored. A dropped copy leaves no item, hash, payload, or log line; only in-memory per-session counters by reason (D-022).
- **Screenshots (Phase 4, D-027, D-028):** the shell captures each display on the configured interval while the engine reports screenshot capture as active.
  - **Skipped before capture:** while the screen is locked, after the inactivity period, without OS permission, while OmniRecall is in front, or when the engine's `capture.screenshot_check` refuses (pause, app exclusions, OCR missing).
  - **Dropped after capture:** near-identical frames, by perceptual hash (§6). New frames are handed to `capture.screenshot` as PNG files in `media/incoming/`.
  - **After OCR:** the engine drops frames with no text, excluded or secret-looking text, or the same text as the previous frame on that display.
- **Images (Phase 4, D-029):** imported images are read with Tesseract OCR, first frame only, up to 100 MP.

### Ingestion/job manager
- Persist jobs before processing.
- Use bounded concurrency and backpressure.
- Use idempotency keys so retries do not duplicate chunks.
- Store stage, status, attempts, and sanitized error codes.
- Support cancellation and graceful shutdown.

### Extraction
- Text: normalize Unicode and whitespace while preserving meaningful formatting.
- Documents: use format-specific extractors; reject unsupported types with a clear error.
- Images/screenshots: OCR locally; store OCR engine/version for debugging. Candidates for the Phase 0 spike: RapidOCR (ONNX models, reuses ONNX Runtime so the app carries one inference runtime) versus Tesseract 5. Choose after the license check (OR-006) and a quality test on the fixture corpus; record the choice in `decisions.md`.
- Audio: transcribe locally; retain timestamps if provided by the engine. Phase 0 candidate: `whisper.cpp` with a `base` model, validated for license, speed, and accuracy before adoption.
  - Phase 5 (D-031 to D-034): files are decoded to 16 kHz mono by the bundled `omnirecall-audio-decode` helper (symphonia; WAV, MP3, M4A, AAC, FLAC, Ogg Vorbis, AIFF, CAF; not Opus) and transcribed by whisper.cpp `base` in 5-minute windows split at silence. The transcript is cleaned of non-speech tags and repetition loops, and each chunk keeps `start_ms`/`end_ms`. Without the speech model, audio items fail with `transcription_model_missing` and are queued again once it is installed.
- Treat all extracted text as untrusted user data.

### Chunking and embeddings
- Start with 500-character chunks and 50-character overlap as a configurable baseline, not a universal optimum.
- Avoid splitting inside words when possible; preserve source offsets.
- Use a pinned `all-MiniLM-L6-v2` ONNX model only after validating its license, tokenizer compatibility, normalization, and output dimension.
- Record model ID/version on each chunk. Model upgrades require an explicit re-embedding migration.
- Normalize vectors consistently between ingestion and query.
- Keep each chunk below the model's input limit (about 256 tokens for all-MiniLM-L6-v2); the 500-character baseline normally fits, but the chunker must verify token length and split further when needed.

Efficiency rules:
- Embed in batches (default 32 chunks) rather than one chunk per call.
- Cache embeddings by `(text_hash, embedding_model)`: identical chunk text from a re-import or a repeated screenshot reuses the stored vector instead of running the model.
- After OCR, hash the extracted text; if it matches the last accepted frame for that display, skip chunking and embedding.
- Load each model on first use and unload it after the idle timeout (see §11).
- Heavy work (OCR, transcription, bulk embedding) can optionally be deferred until the machine is idle or on AC power.

### Storage
- SQLite is the source of truth for item metadata, chunk text, jobs, settings, and FTS5.
- LanceDB stores vectors keyed by stable chunk ID and model version, with **one table per embedding model and dimension**, named `chunks__<model-id>__<dim>` (for example `chunks__all-minilm-l6-v2__384`). A model upgrade builds the new table in the background, then switches the active-table setting; rollback switches back. Mixed dimensions in one table are therefore impossible.
- Media files live in an app-owned data directory with random/stable IDs, not untrusted original filenames.
- Use transactional outbox/reconciliation logic because SQLite and LanceDB cannot share one ACID transaction.
- Provide index rebuild and orphan cleanup tools.

### Retrieval
1. Validate query and filters (date range, source types, and formats such as `audio`, D-034).
2. Embed query locally.
3. Retrieve top-K vector candidates.
4. Retrieve top-K lexical candidates via FTS5.
5. Fuse rankings (for example, reciprocal rank fusion) and optionally rerank locally.
6. Join candidates to current SQLite metadata and discard deleted/excluded records.
7. Return source-backed snippets, scores, timestamps, and provenance.
8. If no good evidence exists, say no strong match was found. Do not fabricate a definitive answer.

## 4. Storage layout

```text
<AppData>/OmniRecall/
  config/
  db/omnirecall.sqlite
  vectors/                  # LanceDB tables
  media/
    screenshots/
    imports/
    audio/
  models/
  logs/
  exports/
```

Actual OS-specific paths must be resolved through Tauri's app-data APIs. Display the active data location in settings. Restrict permissions to the current user where supported. The MVP does not claim encryption-at-rest unless it is implemented and tested.

## 5. SQLite schema

This section is the **only** schema definition. Other documents refer here instead of repeating it. Schema changes are made through migrations and updated here in the same change.

### `items`
- `id TEXT PRIMARY KEY`
- `source_type TEXT NOT NULL`
- `source_label TEXT`
- `source_uri TEXT`
- `captured_at TEXT NOT NULL`
- `content_hash TEXT`
- `media_uri TEXT` (relative to the app media directory)
- `media_status TEXT NOT NULL DEFAULT 'none'` (`none`, `present`, `pruned`, `deleted`)
- `metadata_json TEXT NOT NULL DEFAULT '{}'` (validated source metadata from PRD §5: MIME type, modified time, page count, duration, display ID)
- `status TEXT NOT NULL` (see §10 for allowed states)
- `error_code TEXT`
- `skip_reason TEXT` (why a `skipped` item was not indexed, for example `duplicate` or `excluded_pattern`)
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- Unique index on `(source_type, content_hash)` so the same content is not ingested twice.

### `chunks`
- `id TEXT PRIMARY KEY`
- `item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE`
- `ordinal INTEGER NOT NULL`
- `text TEXT NOT NULL`
- `start_offset INTEGER`
- `end_offset INTEGER`
- `start_ms INTEGER`, `end_ms INTEGER` (position in a recording for transcript chunks, otherwise NULL; migration 0002, D-033)
- `text_hash TEXT NOT NULL` (SHA-256 of normalized chunk text; used by the embedding cache)
- `chunker_version TEXT NOT NULL`
- `embedding_model TEXT NOT NULL`
- `created_at TEXT NOT NULL`

Add an FTS5 virtual table for chunk text and maintain it through tested triggers or explicit transactional updates. Implemented as external-content `chunks_fts` (`porter unicode61 remove_diacritics 2`) with insert/update/delete triggers.

A deleted item keeps only its row with `id`, `source_type`, timestamps, and status `deleted`; `content_hash`, `source_label`, `source_uri`, `media_uri`, and `metadata_json` are cleared, so the same content can be imported again.

### `jobs`
- `id TEXT PRIMARY KEY`
- `item_id TEXT NOT NULL`
- `stage TEXT NOT NULL`
- `status TEXT NOT NULL`
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `next_attempt_at TEXT`
- `last_error_code TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### `vector_outbox`
Cross-store writes to LanceDB are recorded here in the same SQLite transaction as the chunk change, then applied and marked done.
- `id TEXT PRIMARY KEY`
- `chunk_id TEXT NOT NULL`
- `operation TEXT NOT NULL` (`upsert` or `delete`)
- `vector_table TEXT NOT NULL`
- `status TEXT NOT NULL` (`pending`, `done`, `failed`)
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### `tombstones`
- `item_id TEXT PRIMARY KEY`
- `requested_at TEXT NOT NULL`
- `pending_stores TEXT NOT NULL` (which of sqlite, fts, vectors, media still need cleanup)
- `completed_at TEXT`

### `sources`
- `id TEXT PRIMARY KEY`
- `source_type TEXT NOT NULL UNIQUE`
- `enabled INTEGER NOT NULL DEFAULT 0`
- `configuration_json TEXT NOT NULL` (validated against a versioned schema, never accepted as arbitrary JSON)
- `updated_at TEXT NOT NULL`

### `exclusions`
- `id TEXT PRIMARY KEY`
- `rule_type TEXT NOT NULL` (for example `app`, `path`, `pattern`)
- `rule_value TEXT NOT NULL`
- `enabled INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`

Rule semantics (D-025): `app` matches the frontmost application name case-insensitively, ignoring a `.exe` or `.app` suffix; while any app rule is enabled, a copy whose app cannot be determined is dropped (fail closed). `path` excludes a folder and everything under it from import and folder walks; the app data folder is always excluded. `pattern` is a literal, case-insensitive text match on the copied text. Folder rules are added only through the shell's folder dialog.

### `settings`
- `key TEXT PRIMARY KEY`
- `value_json TEXT NOT NULL` (validated against the settings model; defaults in §11)
- `updated_at TEXT NOT NULL`

### `schema_migrations`
- `version INTEGER PRIMARY KEY`
- `applied_at TEXT NOT NULL`

## 6. Screenshot deduplication

Implemented algorithm (D-027, D-028):
1. Capture only after consent and permission checks, and only when the engine's admission check allows it.
2. Box-downscale a copy to 32x32 and convert to grayscale.
3. Compute a 64-bit perceptual hash: a 2-D DCT-II, keep the 8x8 lowest frequencies, and set each bit by comparison with their median (DC excluded from the median). Compare the Hamming distance to the last accepted frame for that display. A distance of 5 or less counts as a duplicate (§11).
4. Discard near-identical frames in the shell, before anything is written, OCR'd, or stored.
5. After OCR, hash the normalized text. If it matches the last accepted frame for that display, drop the new frame and record `last_seen_at` on the earlier item.

The changed-pixel ratio was not needed: on the fixtures, a text cursor stays within distance 5 and different screens are far apart (`screenshot.rs` tests).
6. Store the hash, comparison version, and skip reason—not the discarded image.

A raw byte hash only detects exact duplicates, not visually similar frames. The 5% threshold must be configurable and tested; scrolling text can matter even when the overall image changes little.

## 7. Security and privacy model

### Assets to protect
- Screenshots and OCR text.
- Clipboard contents.
- Imported files and transcripts.
- Embeddings, metadata, and file paths.
- Search queries: not stored by default. If the optional recent-searches list is enabled, it stays local, is excluded from logs, and has a clear action.
- Local service token and configuration.

### Threats and controls
- **Accidental capture:** opt-in, visible state, exclusions, pause shortcut, lock/inactivity policy.
- **Local API abuse:** no network port (stdio JSON-RPC sidecar), strict schemas, and request limits. If the HTTP fallback is ever used: loopback only, per-launch authentication, and origin checks as defense-in-depth.
- **Path traversal:** resolve paths, enforce allowed app-data/import roots, avoid trusting filenames.
- **Malicious files:** size/type limits, parser isolation where possible, timeouts, no execution of imported content.
- **Sensitive logs:** structured error codes and redaction; no raw payload logging.
- **Index inconsistency:** reconciliation, tombstones, rebuild, and deletion tests.
- **Model supply chain:** pinned versions, checksums, license notices, documented download source.
- **Prompt injection in retrieved content:** treat retrieved text as evidence, never as instructions to the application or agent.

### Data deletion
Delete the item record, FTS entries, chunks, vector records, and app-owned media. Because vector deletion may not be atomic with SQLite, use a deletion tombstone and retry/reconciliation job. Do not report deletion as complete until all stores have been checked; if cleanup is pending, show that state clearly (item state `deleting`).

Deletion must be **physical**, because both stores keep deleted bytes by default:
1. SQLite runs with `PRAGMA secure_delete = ON`, so freed pages are overwritten.
2. After deletes, run the FTS5 `optimize` command so removed text is merged out of the index segments.
3. Checkpoint the WAL (`PRAGMA wal_checkpoint(TRUNCATE)`) so deleted rows do not linger in the WAL file.
4. LanceDB deletes leave rows in older table versions. Run compaction and old-version cleanup (in current LanceDB, `optimize` with an immediate cleanup threshold) before marking the tombstone complete.
5. Delete owned media files and their thumbnails.

A regression test must insert a unique marker string, delete the item, and confirm the marker cannot be found by scanning the raw SQLite, WAL, and LanceDB files.

Chunk text never enters LanceDB; it holds chunk ID, item ID, text hash, model ID, and vector. After deletion the test also confirms that the deleted chunks' text hashes and raw vector bytes are absent from every LanceDB file. LanceDB's transaction log keeps the delete predicate, which names the opaque item ID; it holds no content (implemented in `tests/test_deletion.py`).

## 8. UX states

- First launch: explain exactly what is and is not captured; all capture toggles off.
- Ready: show engine status, source toggles, last indexing time, and storage use.
- Indexing: show queued/processing/failed counts without exposing sensitive text unnecessarily.
- Search results: snippet, source type, timestamp, relevance, preview/open-source action.
- No results: offer query simplification and show active filters.
- Model missing: explain what is missing, size, license, and user-controlled setup action.
- Permission denied: explain OS setting needed; never repeatedly prompt or silently fall back.
- Engine unavailable: allow restart and show sanitized diagnostics.
- Clear index: explicit confirmation with a clear statement of what will be deleted.

## 9. Deployment model

- Desktop installer bundles app shell and engine runtime where licensing and packaging permit.
- Large model weights may be downloaded by explicit user action, with checksum verification and license display.
- Core functionality must work offline after setup.
- No hosted database, remote inference, account, or mandatory telemetry.
- Release artifacts include platform-specific installer, checksums, changelog, dependency/model license notices, and known limitations.

## 10. Item lifecycle states

| State | Meaning | Allowed next states |
|---|---|---|
| `queued` | Persisted, waiting for a worker | `processing`, `skipped`, `deleting` |
| `processing` | A pipeline stage is running | `indexed`, `failed`, `skipped`, `deleting` |
| `indexed` | Searchable in all stores | `processing` (re-index or re-embed), `deleting` |
| `failed` | Stage failed; sanitized error code recorded | `queued` (retry), `deleting` |
| `skipped` | Duplicate or excluded; no content kept beyond the hash and reason | `deleting` |
| `deleting` | Tombstoned; hidden from search; cleanup running | `deleted` |
| `deleted` | All stores verified clean | none |

Search must never return an item that is not `indexed`.

## 11. Default values

Starting defaults, all configurable. They are tuned only with measurements from the evaluation corpus and reference hardware, and any change is recorded in `decisions.md`.

| Setting | Default |
|---|---|
| Max imported file size | 100 MB |
| Max PDF pages | 500 |
| Max audio duration | 2 hours |
| Max clipboard text | 100 KB |
| Max query length | 1,000 characters |
| Screenshot interval | 30 s (minimum 5 s) |
| Screenshot duplicate threshold | perceptual-hash Hamming distance of 5 or less (of 64 bits) |
| Screenshot inactivity pause | 5 minutes without input (0 = off) |
| Screenshot secret filter | on (best effort) |
| Job queue capacity | 1,000 jobs (backpressure beyond this) |
| Worker concurrency | 2 |
| Job retries | 3, with backoff of 10 s, 60 s, 5 min |
| Chunk size / overlap | 500 / 50 characters, capped by model token limit |
| Embedding batch size | 32 chunks |
| Vector candidates (top-K) | 50 |
| Keyword (FTS5) candidates | 50 |
| Rank fusion | reciprocal rank fusion, k = 60 |
| Results shown | 20 |
| Model idle unload | 5 minutes |
| Screenshot image retention | 7 days, then text only (text-only mode: image removed once indexed) |
| Media storage cap | 5 GB, prune oldest media first |
| Text item retention | until the user deletes it |
| Search query storage | off |

## 12. Identifiers and formats

- Item, job, outbox, and exclusion IDs: UUIDv7 (time-sortable, never reused).
- Chunk ID: deterministic, derived from `item_id`, `ordinal`, and `chunker_version` (for example a UUIDv5 over those values), so a retry produces the same IDs instead of duplicates.
- Content and text hashes: SHA-256, hex-encoded.
- Timestamps: ISO 8601 in UTC with milliseconds (`2026-10-21T22:14:24.123Z`), rendered in local time in the UI.
- Media filenames: the owning item ID plus a validated extension; never the original filename.

## 13. Retention and export

**Retention:** a background job enforces the §11 retention defaults. Pruning a screenshot image keeps its OCR text and chunks searchable and marks the media as `pruned` in the item detail view. The settings page shows current media usage against the cap.

**Export format:** one zip file containing:
- `manifest.json`: app version, schema version, export timestamp, item count, and SHA-256 checksum of every other file.
- `items.jsonl` and `chunks.jsonl`: one JSON record per line, using the §5 fields.
- `media/`: app-owned media that still exists.

Details (D-026): the export is built from one read snapshot of the database, so it is consistent while indexing continues. It is written to `<name>.zip.partial` and renamed when complete. The target must be an absolute `.zip` path outside the data folder, chosen in the shell's save dialog; the UI cannot pass a path. `manifest.json` carries `format_version: 1`.

Vectors are not exported. Restore (P1) re-imports items and chunks and rebuilds vectors with the active embedding model, which keeps exports small and independent of model versions.
