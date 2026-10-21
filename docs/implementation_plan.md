# OmniRecall — Implementation Plan

**Delivery principle:** build a small, verifiable local pipeline first. Do not implement all capture drivers before import, indexing, search, and deletion are reliable.

## 1. Architecture decisions

- **Desktop shell/UI:** Tauri 2 + React + TypeScript.
- **Desktop-native responsibilities:** window lifecycle, OS permissions, tray/menu, secure app configuration, and platform capture integration.
- **Local processing service:** Python engine run as a supervised Tauri sidecar, speaking versioned JSON-RPC 2.0 over stdin/stdout. It opens no network port. Loopback HTTP (for example FastAPI) is a fallback only, used if stdio proves unworkable and recorded in `decisions.md`.
- **ML inference:** ONNX Runtime for embeddings; OCR chosen in Phase 0 between RapidOCR (ONNX) and Tesseract 5; `whisper.cpp` with a `base` model as the transcription candidate. See `design.md` §3.
- **Metadata/jobs:** SQLite with migrations and transactions.
- **Vectors:** LanceDB, with a stable chunk ID shared with SQLite.
- **Keyword retrieval:** SQLite FTS5 where available.
- **Packaging:** Tauri bundling plus a reproducible strategy for the Python runtime, native dependencies, and model files.

**Important constraint:** Tauri + React + Python + OCR + transcription models cannot honestly guarantee total runtime memory below 20 MB. Treat memory as a measured budget by subsystem and allow models to load on demand.

## 2. Data flow

1. A user-approved source emits an item.
2. A source adapter creates an ingestion envelope and computes a stable content hash.
3. The deduplicator checks the hash and screenshot difference threshold.
4. A bounded job queue persists the job state in SQLite.
5. The extractor produces normalized text and source metadata.
6. The chunker creates stable, overlapping chunks with offsets.
7. The embedding worker creates normalized 384-dimensional vectors using a pinned local model.
8. SQLite stores item/chunk metadata, FTS5 text, and a `vector_outbox` entry in one transaction; the outbox worker writes vectors and chunk IDs to LanceDB.
9. Search runs lexical and vector retrieval, fuses/reranks candidates, and joins them to SQLite metadata.
10. UI displays the answer as source-backed snippets. The MVP should retrieve evidence, not generate unsupported answers.
11. Deletion marks the item, removes its chunks from both indexes, deletes owned media, and runs consistency checks.

## 3. Suggested repository layout

```text
omnirecall/
  apps/
    desktop/                 # Tauri + React + TypeScript
      src/
      src-tauri/
  services/
    local-engine/            # Python ingestion, OCR, embeddings, search
      omnirecall/
        api/
        capture/
        ingestion/
        extraction/
        chunking/
        embeddings/
        retrieval/
        storage/
        jobs/
      tests/
      pyproject.toml
  models/                     # model manifests only; large weights handled separately
  migrations/                 # versioned schema migrations if shared here
  docs/
    prd.md
    implementation_plan.md
    design.md
    rules.md
    bugs.md
    decisions.md
  scripts/
  .github/workflows/
  README.md
```

## 4. Delivery phases and exit gates

### Phase 0 — repository and risk spike
- Create repo, formatter/linter/type-check/test commands, CI, dependency lockfiles, and architecture decision records.
- Test Tauri-to-worker startup/shutdown on each target OS.
- Validate OCR candidates (RapidOCR versus Tesseract 5), the embedding model, and `whisper.cpp` on a clean machine; record the choices in `decisions.md`.
- Prove the stdio JSON-RPC sidecar round trip, crash detection, and restart on each target OS.
- Measure installer size and engine cold-start time with the bundled Python runtime (OR-018).
- Confirm licenses and distribution rules for every model and native dependency.
- Measure baseline idle RAM/CPU and model-loaded resource usage.

**Exit gate:** a clean machine can launch the shell and supervised worker; dependencies and model licenses are understood.

### Phase 1 — local data foundation
- Define SQLite schema and migrations for items, chunks, jobs, sources, exclusions, and schema version.
- Implement stable IDs, content hashes, job states, retry semantics, and consistency checks.
- Integrate LanceDB and verify insert/search/delete/rebuild behavior.
- Implement the `vector_outbox` and `tombstones` tables and physical deletion (`design.md` §7).
- Add FTS5 and a deterministic local fixture corpus with about 50 labeled queries (expected items for each), including a small non-English set.

**Exit gate:** tests prove item/chunk metadata and vector records remain consistent after retries, crashes, deletion, and index rebuild.

### Phase 2 — text import to search vertical slice
- Implement paste/import of plain text and supported documents.
- Normalize and chunk text; embed locally in batches with the embedding cache; store metadata and vectors.
- Implement lexical + vector retrieval and result previews.
- Add empty-state, loading, error, and index progress UI.

**Exit gate:** user imports a fixture corpus, queries it semantically, opens source details, deletes an item, and confirms it no longer appears. A baseline of recall@10, MRR, and p95 search latency at 10,000 chunks is recorded on the reference machine.

### Phase 3 — clipboard and privacy controls
Clipboard is text-only and reuses the Phase 2 pipeline, so it is the first background source. The shared privacy controls ship with it, so they exist before any screen capture.
- Add clipboard listener behind an explicit opt-in toggle.
- Add size limits, duplicate detection, sensitive-pattern exclusions as a best-effort safeguard, and application/path exclusion controls where platform APIs allow.
- Add the persistent capture indicator, global pause, per-source pause, clear-index confirmation, export (format in `design.md` §13), retention settings, and storage usage.
- Audit logs and outbound network behavior.

**Exit gate:** privacy test suite passes, and no source captures while disabled or paused.

### Phase 4 — images and screenshots
- Implement image import and OCR first, using the OCR engine chosen in Phase 0.
- Add explicit screenshot opt-in, reusing the Phase 3 indicator, pause control, and exclusion settings; add inactivity/lock behavior where supported.
- Implement image hashing and configurable change detection; record why a frame was skipped without storing the image. Skip embedding when OCR text matches the previous frame.
- Enforce screenshot image retention and the media storage cap.
- Test multiple displays, DPI/scaling, permissions (including revoked and re-prompted permissions), lock screen, Wayland and X11 on Linux, and remote desktop edge cases.

**Exit gate:** capture is opt-in, transparent, deduplicated, recoverable, bounded in storage, and verified on each supported OS.

### Phase 5 — audio notes
- Support user-selected audio import and local transcription.
- Add model setup, progress, cancellation, failure/retry states, and transcript timestamps where supported.
- Add transcription cleanup tests and long-file limits.

**Exit gate:** common audio fixtures transcribe offline and produce searchable transcript chunks.

### Phase 6 — hardening and packaging
- Add fault injection, crash/restart recovery, corrupted-index recovery, migration tests, and performance tests, including the 100,000-chunk latency target and a re-run of the relevance baseline.
- Build signed/notarized packages where feasible.
- Test clean install, upgrade, uninstall, and data-retention behavior.
- Write threat model, privacy statement, supported-format list, model licenses, and troubleshooting docs.

**Exit gate:** release checklist in PRD is complete for each supported OS.

### Phase 7 — beta and release
- Publish a clearly labeled beta with known limitations and issue templates.
- Collect opt-in user reports without captured content or automatic telemetry.
- Fix data-loss, privacy, crash, and incorrect-source issues before feature expansion.
- Tag reproducible releases and attach checksums, changelog, and SBOM/dependency inventory.

## 5. Core data model

The schema is defined only in `design.md` §5 (tables, columns, indexes) and §10 (item states). Do not repeat it here. Do not store secrets or full payloads in job error fields. Keep raw media only when required and enabled by the user, within the retention policy.

## 6. API / IPC contract

JSON-RPC 2.0 methods over the sidecar's stdin/stdout, with typed request/response schemas and a `protocol_version` checked at startup. Minimum methods:
- `health`
- `status` — worker, queue, model, index, and storage status
- `items.import` — user-selected file/text metadata
- `items.get` — item metadata and chunk previews
- `items.delete` — returns `deleting` until all stores are verified clean
- `items.retry` and `jobs.cancel`
- `capture.pause` and `capture.resume`
- `sources.update` — enable/disable or configure a source
- `exclusions.list`, `exclusions.create`, `exclusions.update`, `exclusions.delete`
- `search` — query, optional filters (source type, date range, application, file), limit
- `index.rebuild`
- `index.clear` — requires explicit UI confirmation
- `export.create` — writes the `design.md` §13 zip to a user-chosen path
- `restore.run` — P1
- `settings.get` and `settings.update`

**HTTP fallback only:** if a loopback HTTP boundary is ever used instead, bind only to `127.0.0.1`/`::1`, use a per-launch secret, validate request sizes, and reject browser-origin requests not issued by the app. Never rely on CORS alone as authentication.

## 7. CI and test strategy

- Python: unit tests, type checks, lint/format, migration tests, integration tests with temporary directories.
- Frontend: component tests, accessibility checks, typecheck, lint, production build.
- End-to-end: import → index → search → preview → delete; pause/resume; worker restart.
- Platform matrix: Windows, macOS, Linux for every capture driver claimed as supported.
- Offline test: disable network after model setup and run all core flows.
- Security tests: local endpoint exposure, path traversal, oversized files, malformed media, log redaction, permission denial.
- Performance corpus: deterministic data set with documented machine specs and query set.

## 8. Release-blocking risks

1. OS capture and clipboard APIs differ and may require permissions or platform-specific implementation.
2. OCR/transcription/model licenses may restrict bundling or redistribution.
3. LanceDB and SQLite can diverge if writes are not coordinated; build reconciliation and rebuild tooling.
4. Screenshot indexing can create large amounts of sensitive data; capture must be off by default and storage bounded.
5. Semantic relevance requires evaluation data; do not promise perfect recall.
6. Mobile background capture is not equivalent to desktop capture and is deferred.
