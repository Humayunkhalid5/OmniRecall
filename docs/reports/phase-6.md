# Phase 6 — Hardening and packaging

## Task brief

- **Phase:** Phase 6.
- **Exit gate:** the PRD §10 release checklist is complete for each supported OS.
- **Acceptance criteria:**
  - Fault injection at every cross-store write, with crash and restart recovery (OR-004).
  - Recovery from a damaged search index and from a damaged database, without silent data loss.
  - Migration tests on data written by every earlier schema.
  - Performance at 100,000 chunks (p95 search under 1 s, design §11) and a re-run of the relevance baseline.
  - Signed and notarized packages where feasible; tested clean install, upgrade, uninstall, and data retention on each OS.
  - Threat model, privacy statement, supported formats, model licenses, and troubleshooting docs.
- **Files:**
  - Engine: `storage/salvage.py`, `recovery.py`, `api/server.py`, `app.py`, `extraction/ocr.py`, `packaging/omnirecall-engine.spec`.
  - Shell: `commands.rs`, `paths.rs`, `lib.rs`, `tauri.release.conf.json`.
  - UI: `views/DatabaseRecovery.tsx`, `App.tsx`, `hooks/useEngine.ts`, `api/engine.ts`.
  - Scripts and CI: `package_engine.py`, `smoke_engine.py`, `install_check.py`, `bench_search.py`, `eval_transcription.py`, `.github/workflows/release.yml`, the `Real models` job in `ci.yml`.
  - Docs: `formats.md`, `threat-model.md`, `privacy.md`, `troubleshooting.md`, `release.md`, `CHANGELOG.md`.
- **Tests:** fault injection, index and database damage, upgrades from saved fixtures of each schema, the packaged engine's smoke test, install checks on each OS, real-model tests, and UI tests with axe checks.
- **Privacy impact:** none on capture. Recovery mode turns capture off, because exclusions may have been lost. Installers add no network access; the only downloads remain the models the user asks for.
- **Defaults used (design §11):** 100,000-chunk latency target p95 < 1 s; data folder kept on uninstall.

## End report

- **Done:**
  - **Fault injection** (`test_fault_injection.py`): the engine is killed at each write point between SQLite and LanceDB while indexing and while deleting, and repeatedly. Every restart converges to a consistent index, and deletes finish physically.
  - **Damaged search index** (D-035): an unreadable vector table is discarded and rebuilt from SQLite, at start-up or while running. Search meanwhile returns keyword results and says the index is being repaired.
  - **Damaged database** (D-036): a start-up check, using SQLite's own damage codes only, opens a recovery screen. **Recover what can be read** copies every readable row into a new database and says what was lost; **Start over** deletes everything OmniRecall stored. A database from a newer version opens the same screen with no actions, so a downgrade cannot destroy data.
  - **Upgrades** (`test_upgrade.py`): data written by the Phase 4 (schema 1) and Phase 5 (schema 2) code opens, keeps items, deletions, settings, exclusions, capture switches, media, and vectors, and accepts new imports. A failed migration leaves the file untouched. A guard fails if a schema has no saved fixture.
  - **Installers** (D-037): NSIS for Windows, .dmg for macOS on Apple Silicon, .deb and .rpm for Linux, with the frozen engine, the audio decoder, and (on Windows and macOS) Tesseract with its libraries and their license files. The release workflow builds each one, installs it, reinstalls it over itself, uninstalls it, and checks the data survives; on Windows and macOS it removes the system Tesseract first, so OCR must work from the bundled copy.
  - **100,000 chunks:** hybrid search p95 157.6 ms (target under 1 s), database 227 MB, vectors 162 MB, peak memory 1.36 GB during bulk indexing (`measurements.md`).
  - **Real models in CI**: the `Real models` job downloads the search and speech models through the engine's verified downloader, then measures speech-to-text on real speech, re-runs relevance, runs the real-model tests, and the network audit with both models installed.
  - **Docs:** supported formats, threat model, privacy statement, troubleshooting, building and releasing, and the changelog with known limitations.
- **Commands run:**
  - Engine: `ruff format --check .`, `ruff check .`, and `mypy omnirecall` are clean. `pytest -q` passes on Linux, Windows, and macOS in CI; locally the new suites pass (`test_fault_injection`, `test_corruption`, `test_database_damage` 7, `test_upgrade` 5, `test_ocr`).
  - Shell: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and `cargo test` pass in CI on all three systems.
  - UI: format, lint, and typecheck are clean; `npm test` 40 passed, including 6 recovery-screen tests with axe checks.
  - Release workflow: every installer job green (sizes and start times in `measurements.md` Phase 6). `Real models` job: 42 passed.
- **Exit gate evidence:**
  - Met, automatically, on all three systems: no network transfer or open port (network audit with the real models), capture off by default and stopped by pause, physical deletion, crash recovery and reconciliation under fault injection, relevance recorded, clean install, upgrade, and uninstall on a fresh profile, and the documentation PRD §10 lists.
  - Speech-to-text with the real model (left open in Phase 5): 9.8% WER on 73 real LibriSpeech recordings, and every test recording is the top result for a question about it (D-038).
  - **Not met:** the manual pass of the privacy flows on each OS (PRD §10, "pass manual tests"). There is no Windows or macOS desktop in this environment, and on Linux only Xvfb. This needs a person on each system; it is the first item of the beta checklist (`release.md`).
  - **Not done:** code signing and notarization. There are no signing accounts (`release.md` lists exactly what is needed). Installers are unsigned and the changelog says so.
- **Found and fixed:**
  - OR-028: a corruption test raced the engine's own start-up repair.
  - A locked or busy database would have opened the recovery screen; only SQLite's damage codes count now.
  - Windows SQLite has no `dbstat`, so the recovery test damaged the wrong pages there; it now finds pages by their content.
  - The Linux installer check got a relative engine path from the .deb listing.
  - The Windows bundle copied all 57 DLLs of the UB Mannheim folder, including Pango, Cairo, GLib, and ICU for its training tools. It now copies the 32 that `tesseract.exe` imports, and ships each one's license text; the build fails on an unreviewed DLL.
  - OR-029: the first real speech-to-text check counted "forty" against "40" as an error, and judged the model by a robotic synthetic voice.
- **Not done or skipped:**
  - Signing and notarization, and the manual OS passes, as above.
  - CPU and battery use during capture on a real laptop (OR-001).
  - Intel Mac build (OR-020).
  - A one-hour recording timed with the real speech model; the estimate from the longest test recording is about 7 minutes.
- **Bugs:** OR-028 and OR-029 opened and closed. OR-030 opened (Windows Tesseract bundle loads libcurl and copyleft DLLs). Evidence added to OR-001, OR-004, OR-014, and OR-018. Release-blocking checklist: 8 of 9 ticked; measurements on a user's own hardware remain.
- **Docs updated:** `decisions.md` D-035 to D-038; `design.md` §7 and §9; `measurements.md`; `bugs.md`; `licenses.md`; `release.md`; and the new docs above.
