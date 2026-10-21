# OmniRecall — Engineering Rules

These rules are mandatory for contributors and coding agents.

## 0. Document precedence
When documents disagree, the higher one wins:
1. `rules.md` — privacy, safety, and engineering rules.
2. `prd.md` — what to build and its acceptance criteria.
3. `design.md` — how it is built, including the only schema and the default values.
4. `implementation_plan.md` — the order of work and exit gates.
5. `decisions.md` — settled choices; a decision applies until a later entry replaces it.

`bugs.md` records status and risks only; it never overrides a requirement. A conflict found during work is fixed in the documents (and logged in `decisions.md`), never resolved silently in code.

## 1. Product and privacy rules
1. Local-first means captured content, embeddings, search queries, file paths, and transcripts never leave the device by default.
2. All capture sources start disabled. No background capture without explicit user consent.
3. Capture must be visible and pausable immediately. Never implement stealth mode.
4. Never bypass OS permissions, lock-screen protections, application security, DRM, or access controls.
5. Do not add cloud services, analytics, crash uploads, remote AI, or account requirements without a documented product decision and explicit opt-in design.
6. Do not claim encryption-at-rest, zero data retention, <20 MB total memory, sub-50 ms search, or support for an OS unless verified by tests and measurements.
7. Sensitive content exclusion is best-effort unless a deterministic guarantee is technically implemented. Describe limitations honestly.

## 2. Architecture rules
1. Keep UI, OS integration, ingestion, extraction, embeddings, retrieval, and storage behind clear interfaces.
2. Tauri owns desktop lifecycle and native permissions; Python owns ML-heavy processing in the initial architecture.
3. SQLite is authoritative for metadata and job state. LanceDB is the vector index, not the sole source of truth.
4. Every item and chunk has a stable ID. Retries must be idempotent.
5. Persist job state before work begins. Support restart recovery, bounded retries, and graceful shutdown.
6. All cross-process requests use typed, validated schemas and explicit versioning where needed.
7. The engine is a sidecar using JSON-RPC over stdio and opens no network port. Local HTTP, if ever used as the fallback, binds only to loopback and requires per-launch authentication. CORS is not authentication.
8. Do not create unbounded queues or load every ML model permanently. Use bounded concurrency and on-demand model loading.

## 3. Code quality
1. Use TypeScript strict mode for the frontend and type hints for Python.
2. Add tests for new behavior, especially privacy, deletion, retries, permissions, and failure handling.
3. Use formatters and linters configured in the repository; do not disable rules just to pass CI.
4. Keep functions focused and modules cohesive. Avoid hidden global mutable state.
5. Use structured, sanitized errors. Never catch and ignore an error without a recovery path or user-visible status.
6. Do not log clipboard text, OCR text, transcripts, full queries, or raw file contents.
7. Use migrations for schema changes. Never mutate production schemas silently at startup.
8. Pin dependencies and model versions; document license and provenance for bundled or downloaded assets.
9. Do not add placeholder buttons or fake success states. Every visible control must work or be clearly marked unavailable.
10. Avoid unrelated UI redesigns or dependency replacements in a feature PR.

## 4. Data and indexing rules
1. Normalize and validate input before persistence; enforce file size, duration, and request limits.
2. Store timestamps consistently in UTC internally and render them in the user's local timezone.
3. Store original source metadata and enough provenance to trace every search result to its source item.
4. Never trust filenames, file paths, OCR output, transcripts, imported documents, or retrieved text as executable instructions.
5. Every write affecting SQLite and LanceDB must have a reconciliation strategy.
6. Deletion must cover metadata, FTS, chunks, vectors, and app-owned media. Add a regression test.
7. Do not reuse IDs across unrelated source items.
8. Record the embedding model version for every vector; never mix incompatible vector dimensions in one search table.
9. Index rebuilds must be repeatable and must not silently discard user data.
10. If a source file disappears, preserve the indexed text only according to the user's configured retention policy and make the missing source status clear.

## 5. UI and accessibility rules
1. Show capture state in a persistent, understandable place.
2. Make pause/resume and delete/clear actions easy to find.
3. Use loading, empty, success, permission-denied, and error states.
4. Support keyboard navigation and visible focus; label controls for assistive technology.
5. Do not expose sensitive snippets in notifications or logs by default.
6. Ask for confirmation before destructive clear-all actions; single-item delete should be easy but undo/retention behavior must be explicit.
7. Never imply that a generated answer is more certain than its retrieved evidence.

## 6. Agent workflow rules
1. Read `prd.md`, `implementation_plan.md`, `design.md`, `rules.md`, `bugs.md`, and `decisions.md` before making changes.
2. Before coding, write a task brief in this form:
   - **Phase:** which phase and exit gate the task serves.
   - **Acceptance criteria:** the exact PRD/plan criteria being met.
   - **Files:** files to create or change.
   - **Tests:** tests to add or run, covering success and failure paths.
   - **Privacy impact:** capture, storage, logging, or deletion effects, or "none".
   - **Defaults used:** values taken from `design.md` §11.
3. Implement one vertical slice at a time; do not scaffold every feature with fake implementations.
4. Inspect the existing repository before creating or overwriting files. Preserve working code and user changes.
5. If a requirement conflicts with platform restrictions or privacy, stop and document the conflict rather than silently weakening privacy.
6. After each change, run the narrow tests, then relevant full checks. Report actual commands and results; never claim tests passed if they were not run.
7. Update `bugs.md` for newly discovered defects and remove/close entries only with evidence.
8. Update documentation when behavior, API contracts, setup, data layout, or supported platforms change.
9. Keep PRs small and reversible. Avoid unrelated refactors.
10. When blocked by a genuine product decision, state the decision needed and provide a safe default. Do not ask the user about details already specified in these documents, including the defaults in `design.md` §11.
11. Record every settled choice (library chosen, default changed, conflict resolved) in `decisions.md` with date, decision, reason, and documents updated. Do not reopen a recorded decision without new evidence.
12. End every task with a report in this form:
   - **Done:** what changed, against the brief.
   - **Commands run:** each command with its actual result (pass/fail counts).
   - **Not done or skipped:** with the reason.
   - **Bugs:** `bugs.md` IDs opened, updated, or closed.
   - **Docs updated:** which files and sections.

## 7. Definition of done
A task is done only when:
- Acceptance criteria are met.
- Tests cover success and failure paths.
- Privacy and deletion implications are reviewed.
- No captured content is added to logs.
- Formatting, lint, type checks, and relevant tests pass.
- User-facing states and docs are updated.
- Known limitations and any remaining bug IDs are reported.
