# Phase 3 — Clipboard and privacy controls

## Task brief

- **Phase:** Phase 3. Exit gate: the privacy test suite passes, and no source captures while disabled or paused.
- **Acceptance criteria:**
  - Clipboard capture of new text only, behind an explicit opt-in toggle that is off by default (PRD §4, §7). Disabled or paused capture reads nothing and records nothing.
  - Size limit (100 KB), duplicate detection, best-effort sensitive-content filter with honest wording (rules §1.7, OR-008), and exclusions by application, folder, and keyword, applied before anything is persisted.
  - A capture indicator that stays visible (window header and system tray), one-action global pause, per-source pause, and a pause shortcut.
  - Clear-index confirmation (Phase 2) kept; export to a zip per design §13; retention settings (screenshot image retention, media cap, text-only mode) with a background enforcement job; storage use shown against the media cap.
  - First-run screen that explains what is and is not captured, with every capture source off.
  - Audit: logs never contain captured text, queries, or paths; the engine makes no network connections outside the user-started model download; the shell has no network permissions beyond that.
- **Files:** engine `capture/{clipboard,sensitive,exclusions}.py`, `storage/retention.py`, `export.py`, `settings.py`, `api/schemas.py`, `app.py`, `ingestion/service.py`; shell `src-tauri/src/{capture,tray,commands,lib}.rs`; UI first-run screen, capture indicator, privacy and data settings; tests for each; `docs/privacy-audit.md`.
- **Tests:** clipboard accepted only when enabled and not paused (global and per-source); oversized, duplicate, sensitive, keyword- and app-excluded copies leave no record; app exclusions fail closed when the app is unknown; folder exclusions on import; export zip contents and checksums, export path validation; retention prunes old screenshot media and enforces the cap oldest-first while keeping text searchable; logs scanned for a marker after every flow; static scan of network-capable imports; syscall-level network audit of a full session; shell watcher state transitions; UI first-run, indicator, pause, exclusions, export.
- **Privacy impact:** this phase adds the first background source. Clipboard text is captured only after opt-in, never while paused, and filtered before persistence. Excluded, sensitive, and oversized copies are not stored at all, not even as a hash (D-022). The tray indicator stays visible whenever the app is running.
- **Defaults used:** max clipboard text 100 KB; screenshot retention 7 days; media cap 5 GB; text-only mode off; capture off; search query storage off.

## End report

- **Done:**
  - Engine capture state in the `sources` table plus a global pause setting; every capture re-checks it (`capture/state.py`). Disabling a source clears its pause.
  - Clipboard capture (`capture/clipboard.py`): size limit, duplicate detection, app exclusions that fail closed when the app is unknown, literal pattern exclusions, and the best-effort secret filter (`capture/sensitive.py`). Dropped copies leave no item, hash, payload, or log line, only per-session counters (D-022).
  - Exclusion rules by app, folder, and pattern (`capture/exclusions.py`, D-025). Folder rules apply to file and folder import; the data folder is always excluded.
  - Export to a zip with manifest and checksums from one snapshot, written via `.partial` and renamed (`export.py`, D-026). Media retention job (screenshot age, media cap, oldest first, text kept) running hourly and on settings change; storage usage API.
  - Shell clipboard watcher that reads nothing while capture is inactive, with a baseline on enable and OS change tokens on Windows and macOS (D-023). Tray indicator (on / paused / off) with pause, open, and quit; global pause shortcut CommandOrControl+Alt+Shift+P; close-to-tray only while a source is enabled and a tray exists (D-024). New allow-listed methods; export, folder exclusion, and clipboard capture are not callable from the UI.
  - UI: first-run screen with capture off and an explanation of what is and is not captured; header capture indicator with one-click pause; privacy settings (clipboard switch, per-source pause, secret filter switch with best-effort wording, session counts, shortcut), exclusion rules, export, retention days, and media cap.
  - Audit: `docs/privacy-audit.md` and `tests/test_network_audit.py` (static import scan plus an strace trace of a full engine session showing no `connect` to a network address). `docs/support-matrix.md`.
- **Commands run:**
  - Engine: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` → clean (44 files). `uv run pytest -q` → 151 passed, 1 skipped (the real-model archive test).
  - Shell: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` → clean. `cargo test` → 15 passed.
  - UI: `npm run format:check`, `npm run lint`, `npm run typecheck` → clean. `npm test` → 21 passed (8 new privacy tests). `npm run build` → 266 KB JS (82 KB gzip).
- **Exit gate evidence:**
  - Automated: `tests/test_privacy.py` (27 tests) covers disabled, globally paused, and source-paused capture, every drop reason leaving no record, fail-closed app exclusions, folder exclusions, and a log scan for a marker after each flow. Shell `capture.rs` tests show the watcher never reads while inactive and treats the existing clipboard as a baseline.
  - Live run of the debug desktop build under Xvfb with real `xclip` copies: a copy made before enabling was not captured; after enabling, a plain copy was captured and a repeated copy was a duplicate; a GitHub token was dropped as sensitive; the pause shortcut paused capture and a copy made while paused was not stored; resume worked; export through the save dialog produced a valid zip with 4 items; a grep of the data folder found no trace of the filtered copies; quitting the app stopped the engine.
- **Not done or skipped:**
  - The text-only mode toggle is not shown: it only affects screenshots, which arrive in Phase 4. The setting exists and the toggle returns with screenshot capture.
  - The tray menu could not be driven in the live run (no AppIndicator host under Xvfb); its state mapping is unit-tested and pause was exercised through the shortcut and the header. Close-to-tray was therefore not exercised live.
  - The Windows and macOS clipboard change-token code is compiled and tested in CI but was not run on a real desktop; Phase 6 covers real hardware.
  - Secret detection is best effort (OR-008) and is described that way in the UI.
- **Bugs:** none opened. Notes added for OR-003, OR-008, OR-015 (all still OPEN by design or pending Phase 4).
- **Docs updated:** `decisions.md` D-022 to D-026; `design.md` §3 (clipboard adapter), §5 (exclusion semantics), §13 (export details); `bugs.md` Phase 3 notes; new `privacy-audit.md` and `support-matrix.md`.
