# OmniRecall — Bug and Risk Register

**Purpose:** living register for verified defects, unresolved engineering risks, and release blockers.  
**Status convention:** `OPEN`, `IN PROGRESS`, `BLOCKED`, `FIXED`, `WONT FIX`.  
**Important:** Entries marked `RISK` are anticipated risks from the proposed design, not claims that the implementation has already been tested and found defective.

## Open risks before implementation

| ID | Type / Priority | Item | Impact | Required action / acceptance evidence | Status |
|---|---|---|---|---|---|
| OR-001 | RISK / P0 | Total runtime memory target of less than 20 MB is unrealistic with Python, OCR, embeddings, and transcription models loaded | Misleading product claim; performance failures | Define separate idle, search, OCR, and transcription memory budgets; benchmark on reference hardware; publish measured results | OPEN |
| OR-002 | RISK / P0 | Desktop and mobile background capture capabilities differ substantially | Mobile scope may be infeasible or violate platform rules | Keep mobile background capture out of MVP; design a separate companion for user-selected imports/voice notes | OPEN |
| OR-003 | RISK / P0 | Screenshot and clipboard capture can collect highly sensitive content | Privacy and trust failure | Capture off by default, explicit consent, persistent indicator, global pause, exclusions, offline verification, and privacy tests | OPEN |
| OR-004 | RISK / P0 | SQLite and LanceDB do not share a single ACID transaction | Search may return deleted/orphaned chunks or metadata | Implement tombstones, retryable reconciliation, consistency checks, and index rebuild; test crash between every cross-store write | OPEN |
| OR-005 | RISK / P1 | The proposed 5% pixel-difference threshold may skip meaningful changes or retain too many frames | Recall or storage degradation | Compare perceptual hash and changed-pixel ratio; make threshold configurable; test scrolling, animation, cursor, multi-monitor, and static screens | OPEN |
| OR-006 | RISK / P1 | Model and OCR library licenses may constrain bundling or commercial use | Release or distribution blocked | Verify and record license, attribution, source, version, and checksum for every dependency/model before packaging | OPEN |
| OR-007 | RISK / P1 | Embedding model/tokenizer preprocessing mismatch can degrade search | Incorrect semantic retrieval | Pin tokenizer/model versions; add known-vector and retrieval regression tests; version all vectors | OPEN |
| OR-008 | RISK / P1 | Clipboard exclusions cannot guarantee detection of all passwords or secrets | Sensitive text may be indexed | Clearly describe best-effort filtering; allow source/app exclusions and disable toggle; never promise complete secret detection | OPEN |
| OR-009 | RISK / P1 | Local API may be abused by another local process or browser context | Unauthorized access to indexed content | Use the stdio JSON-RPC sidecar with no network port (decision D-003); if the HTTP fallback is ever used: loopback-only binding, per-launch token, strict origin checks, input limits, and security tests | OPEN |
| OR-010 | RISK / P1 | Document parsing and OCR may hang, crash, or consume excessive resources on malformed/large files | Data loss or app unresponsiveness | Apply file/page/duration limits, timeouts, worker isolation where practical, cancellation, and clear error states | OPEN |
| OR-011 | RISK / P1 | Search relevance has no evaluation corpus yet | Product may feel unreliable despite working technically | Create a labeled local test corpus and query set; track recall@k and ranking metrics before tuning | OPEN |
| OR-012 | RISK / P2 | Native capture permissions and APIs vary by operating system/version | Uneven platform support | Maintain a tested support matrix; handle denied/unavailable states; do not claim unsupported platforms | OPEN |
| OR-013 | RISK / P2 | Model download and update process may introduce supply-chain risk | Malicious or corrupted model files | Use pinned sources, checksums, license display, user-approved downloads, and safe replacement behavior | OPEN |
| OR-014 | RISK / P2 | Uninstall, backup, and data-retention expectations are undefined on each OS | Users may lose data or leave sensitive files behind | Document uninstall behavior; offer export and clear-data flows; test upgrade and uninstall scenarios | OPEN |
| OR-015 | RISK / P1 | Linux Wayland routes screenshots through xdg-desktop-portal, which on many compositors asks the user per capture or per session; clipboard reads may require window focus | Periodic screenshot capture may be impossible or interactive on Wayland | Test GNOME and KDE on Wayland plus X11; ship Linux periodic capture as X11-only or clearly unavailable if silent capture is not permitted; record results in the support matrix | OPEN |
| OR-016 | RISK / P1 | Recent macOS versions periodically ask users to re-approve screen recording; Windows capture APIs differ by version | Capture stops unexpectedly or behaves differently per OS version | Treat revoked permission as the permission-denied UX state; never prompt repeatedly; record behavior per OS version in the support matrix | OPEN |
| OR-017 | RISK / P0 | Deleted content can survive in LanceDB old table versions, SQLite free pages, and the SQLite WAL file | Privacy breach: "deleted" data is recoverable from disk | Implement physical deletion (`design.md` §7); regression test scans raw store files for a deleted marker string | OPEN |
| OR-018 | RISK / P1 | Bundling Python, ONNX Runtime, and models makes installers large and engine start slow; every embedded native binary must be signed/notarized on macOS | Poor install experience; release blocked by signing | Measure installer size and cold start in Phase 0; make large models optional user-approved downloads; include sidecar binaries in the signing pipeline. Phase 0 measured: frozen engine 462 MB unpacked / 180 MB gzip, cold start ~150 ms (`measurements.md`) | OPEN |
| OR-019 | RISK / P2 | The embedding model truncates inputs at about 256 tokens and handles non-English text poorly | Missed results for long chunks and non-English content | Verify chunk token length in the chunker; keep a non-English query set in the evaluation corpus; MVP claims English only | OPEN |
| OR-020 | RISK / P2 | `pywhispercpp` publishes no macOS x86_64 wheel | Audio transcription unavailable on Intel Macs | Build whisper.cpp from source in the macOS x86_64 release job, or mark audio transcription unavailable on Intel Macs in the support matrix | OPEN |

## Verified defects

No implementation has been inspected or executed as part of preparing this specification. Therefore, **there are currently no verified implementation bugs recorded**. Do not convert the risks above into claims of observed defects.

Use this template when a real bug is found:

### OR-XXX — Short title
- **Type:** BUG
- **Priority:** P0 / P1 / P2 / P3
- **Status:** OPEN
- **Environment:** OS, app version, model versions, relevant configuration
- **Steps to reproduce:**
  1. ...
  2. ...
- **Expected:** ...
- **Actual:** ...
- **Evidence:** sanitized logs, test name, or reproducible fixture (never attach private captured content without explicit consent)
- **Root cause:** unknown until verified
- **Fix plan:** ...
- **Regression test:** ...
- **Resolution:** fill only after fix and verification

## Priority guide

- **P0:** privacy breach, data loss, unauthorized access, or core application unusable.
- **P1:** major ingestion/search/deletion behavior broken or release-critical platform issue.
- **P2:** significant defect with a workaround; should be addressed before stable release where practical.
- **P3:** minor visual issue, polish, or low-impact edge case.

## Release-blocking checklist

- [ ] No network transfer of captured content, embeddings, queries, or file paths.
- [ ] Capture is off by default and fully stops when paused/disabled.
- [ ] Delete and clear-index remove data from SQLite, FTS5, LanceDB, and owned media, and deleted content cannot be found in raw store files (including the WAL and old LanceDB versions).
- [ ] Crash recovery and index reconciliation pass fault-injection tests.
- [ ] The engine opens no network port; if the HTTP fallback is used, it is not reachable from the LAN and requires authentication.
- [ ] Relevance (recall@10, MRR) and latency results are recorded against the labeled evaluation corpus.
- [ ] Model/dependency licenses and checksums are documented.
- [ ] Resource and search latency results are measured on documented hardware.
- [ ] Clean install, upgrade, and uninstall behavior are tested.
