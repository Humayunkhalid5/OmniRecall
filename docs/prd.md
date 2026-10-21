# OmniRecall — Product Requirements Document (PRD)

**Status:** Draft for implementation  
**Product type:** Local-first personal context engine  
**Primary release target:** Desktop MVP for Windows, macOS, and Linux  
**Core promise:** Find information you have already seen, copied, saved, or recorded—without remembering which app it came from.

## 1. Product goal

Build a privacy-first desktop application that continuously and transparently captures user-approved personal context, extracts searchable text locally, and lets users retrieve it with natural-language queries. The product must work without cloud accounts, hosted inference, or sending personal content to external services.

**Success means:** a user can enable capture, collect supported content, ask a question in plain language, inspect the source and timestamp of a result, and delete that content permanently from the local index.

## 2. Problem

Personal information is fragmented across screenshots, copied text, documents, and voice notes. Keyword search is unreliable when users cannot remember the exact phrase, file, application, or date. Cloud-based recall tools can also create unacceptable privacy and cost concerns.

## 3. Target users and use cases

- Students retrieving a concept, slide, or page they saw earlier.
- Developers finding a command, error message, code snippet, or technical page.
- Knowledge workers recalling a meeting note, copied message, or document passage.
- Anyone who wants searchable personal history but requires local data control.

Primary user stories:
1. As a user, I can explicitly enable or pause each capture source.
2. As a user, I can import documents, images, and audio notes.
3. As a user, I can search by meaning even if my query does not match the original wording.
4. As a user, I can see why a result matched, when it was captured, and where it came from.
5. As a user, I can exclude applications, folders, and sensitive content.
6. As a user, I can delete an item and its associated text, vectors, and media.
7. As a user, I can export my data (MVP) and restore it on the same or another device (restore is P1).
8. As a user, I can inspect indexing status, storage use, and background resource use.

## 4. MVP scope

### P0 — required for first usable release
- Tauri desktop application with React and TypeScript UI.
- First-run privacy explanation and explicit opt-in for every capture source.
- Local daemon/worker lifecycle: start, stop, pause, restart, and clear status.
- Manual import of text, PDF, common document formats, images, and audio files.
- Clipboard capture behind an explicit toggle, with deduplication and size limits.
- Periodic screenshot capture behind an explicit toggle, with a visible status indicator, configurable interval, app exclusions, and pause-on-lock/inactivity behavior where supported.
- Local OCR for screenshots and images; local transcription for audio.
- Local text normalization, chunking, embeddings, and hybrid retrieval: vector search plus a SQLite FTS5 keyword index, fused by rank.
- SQLite metadata store and LanceDB vector store.
- Search UI with ranked results, snippets, timestamps, source/application/file path, and open-preview action.
- Item detail view with original-source reference where available.
- Delete item, clear index, pause/resume, and export controls.
- Retention controls: screenshot image retention period, media storage cap, and text-only mode (defaults in `design.md`).
- Logs that avoid recording captured content by default.
- Safe failure behavior when a model is missing, a source is unsupported, or indexing fails.

### P1 — after MVP is stable
- Search filter UI for date, source type, application, and file. The search API accepts optional filters from the MVP so the UI can be added without a contract change.
- Search result feedback (helpful/not helpful) stored locally.
- Duplicate and near-duplicate detection improvements.
- Explainable ranking: show why a result matched (keyword hit, semantic similarity, or both).
- Backup/restore and index rebuild tools.
- Optional mobile companion for user-selected imports and voice notes, subject to platform limitations.

### Explicitly out of scope for MVP
- Cloud sync, hosted inference, accounts, team workspaces, or remote analytics.
- Hidden or covert surveillance.
- Capturing protected/DRM content or bypassing OS permissions.
- Guaranteed capture of every app, every screen, or every mobile event.
- Autonomous actions based on recalled content.
- A claim of sub-20 MB total runtime memory while OCR/embedding/transcription models are loaded.
- Production-grade mobile background screen recording; mobile platforms restrict this and require a separate design.

## 5. Supported content and ingestion behavior

| Source | MVP behavior | Required metadata |
|---|---|---|
| Clipboard | Capture new text only when enabled; skip secrets/oversized payloads where detectable | timestamp, source=`clipboard`, content hash |
| Screenshot | Capture on configured interval only when enabled and permitted; hash/deduplicate before expensive OCR | timestamp, display identifier if available, image URI |
| File import | User selects files/folders; supported types listed in UI | path or import label, MIME/type, modified time |
| Audio note | User imports or drops audio; local transcription | file URI, duration if available, transcript timestamp |
| Text | Paste or import plain text | timestamp, source label |

Supported document formats should be declared in the UI and tested. Do not silently claim support for formats that cannot be extracted reliably.

**Language scope:** the MVP officially supports English content and queries, because the pinned embedding model is trained mainly on English. Other languages may be indexed but are not claimed as supported. A multilingual embedding model is a P1 candidate, delivered through the re-embedding migration.

## 6. Privacy and security requirements

- Default to **capture off** until the user explicitly opts in.
- Never send captured content, embeddings, filenames, or telemetry to a remote endpoint.
- Bind local service endpoints to loopback only; use an unpredictable per-session token or equivalent IPC authentication if HTTP is used.
- Do not expose an unauthenticated local API to the LAN.
- Provide visible capture status and one-action pause.
- Exclude configured applications, paths, and content types before persistence where feasible.
- Store all indexes and media in a documented local data directory with restrictive OS permissions.
- Never place secrets or raw captured content in diagnostic logs.
- Deletion must remove metadata, vectors, and owned media; define and test behavior for orphan cleanup.
- Explain that local storage is not automatically encrypted. If encryption-at-rest is not implemented, state this clearly and recommend OS disk encryption.
- Treat imported documents, OCR output, and transcripts as untrusted data, never as executable instructions.
- Do not store search queries by default. An optional recent-searches list may be enabled; it stays local and can be cleared.
- Bound storage with a retention policy. Default: keep screenshot images for 7 days, then keep only their extracted text; cap app-owned media at 5 GB and prune oldest media first; keep text items until the user deletes them. All values are user-configurable.
- Deletion must be physical, not only logical: deleted content must not remain recoverable from the app's store files (see `design.md` §7).

## 7. Functional requirements and acceptance criteria

### Capture and ingestion
- The user can independently enable/disable clipboard and screenshot capture.
- A disabled source produces no new records.
- Duplicate screenshots are discarded using a documented image hash/difference policy.
- An ingestion failure is visible and does not crash the UI or daemon.
- A source item has a stable ID and an ingestion state: `queued`, `processing`, `indexed`, `failed`, `skipped` (duplicate or excluded), `deleting` (tombstoned, cleanup running), or `deleted`. Allowed transitions are defined in `design.md`.

### Processing
- OCR, transcription, chunking, and embedding execute locally.
- Processing can be retried safely without duplicate records.
- Long-running work does not block the UI.
- Model downloads, if offered, require user action and show size/license information; bundled models must have verified redistribution rights.
- Missing model files produce a useful setup message.

### Search
- Search accepts natural-language text and returns semantically relevant indexed chunks.
- Results combine vector similarity with lexical matching when the lexical index is available.
- Results include a snippet, source, timestamp, and confidence/relevance indication without presenting similarity as factual certainty.
- Empty, malformed, or very long queries fail gracefully.
- Clicking a result opens an in-app detail/preview; opening the original file is offered only if the path remains valid and the user chooses it.
- Search remains usable while ingestion is running.

### Lifecycle and data management
- The user can pause all capture and see that it is paused.
- The user can delete a result and verify it no longer appears in search.
- The user can clear all indexed data after confirmation.
- The user can export an inventory and user-owned data in a documented format.
- On restart, the app recovers queued/failed jobs safely and reconciles SQLite/LanceDB state.

## 8. Non-functional requirements

- **Privacy:** local-only processing and no remote content transfer by default.
- **Reliability:** ingestion is restartable and idempotent; corrupted index state is detectable.
- **Performance:** UI remains responsive; indexing uses a bounded queue and configurable concurrency.
- **Resource control:** configurable capture interval, queue limits, model selection, and idle behavior. Measure CPU, RAM, disk, and battery impact on target hardware.
- **Search latency target:** p95 under 1 second for a 100,000-chunk local test corpus on a documented reference machine; publish measured results, not guarantees.
- **Packaging:** signed/notarized installers where platform accounts and infrastructure permit.
- **Accessibility:** keyboard navigation, visible focus, readable contrast, and screen-reader labels for core workflows.
- **Observability:** local diagnostic logs and health status without captured payloads.

## 9. Product metrics

- Successful indexing rate by source type.
- Median and p95 query latency on a reproducible local corpus.
- Search success rate from a manually labeled evaluation set.
- Duplicate capture rejection rate.
- Crash-free sessions and recovery success after forced restart.
- Idle and active CPU/RAM/disk measurements on reference hardware.
- User ability to pause capture and delete records without assistance.

Do not collect these metrics remotely in the privacy-first MVP.

## 10. Release definition

A release candidate is acceptable only when:
- All P0 acceptance criteria pass on each supported OS.
- Privacy permissions, exclusions, pause, deletion, and clear-index flows pass manual tests.
- The app operates with network access disabled after models are installed.
- No captured content appears in logs or network traffic.
- Installer, model licensing, data locations, limitations, recovery steps, and known issues are documented.
- A clean install and upgrade path are tested on a fresh user profile.
