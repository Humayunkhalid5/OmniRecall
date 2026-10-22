# Phase 7 — Beta and release

## Task brief

- **Phase:** Phase 7.
- **Goal (implementation plan):** a clearly labeled beta with known limitations and issue templates; opt-in user reports without captured content or automatic telemetry; data-loss, privacy, crash, and incorrect-source issues fixed before features; tagged reproducible releases with checksums, changelog, and SBOM.
- **Acceptance criteria:**
  - The app and the README say it is a beta; the changelog lists known limitations.
  - Issue templates that ask for no content, a private route for vulnerabilities, and labels for the triage order.
  - A problem report the user reads before sharing, with no content, paths, app names, or exclusions, and no sending by the app (D-039).
  - A release workflow that publishes checksums, an SBOM, and provenance, from pinned toolchains (D-040).
- **Files:**
  - Engine: `omnirecall/diagnostics.py`, `app.py` (`diagnostics.report`), `storage/repository.py` (`failed_codes`).
  - Shell: `commands.rs` (`save_problem_report`, `open_issue_page`, `diagnostics.report` allowed for the UI), `lib.rs`.
  - UI: Settings → Report a problem (`SettingsView.tsx`), a Beta label in the header (`App.tsx`), `api/engine.ts`, `styles.css`.
  - Repository: `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md`, `SECURITY.md`, `scripts/sbom.py`, `.github/workflows/release.yml`.
  - Docs: `beta.md`, `README.md`, `CHANGELOG.md`, `release.md`, `privacy.md`, `troubleshooting.md`.
- **Tests:** engine (report contents against marker content, the log filter), UI (preview before copy, save and issue page only on request, errors, axe), shell (the issue URL carries no query and the report method is UI-callable).
- **Privacy impact:** a new way for information to leave the app, so it is designed to carry none of the user's content and to go only where the user takes it. The app makes no new network request; the browser opens a fixed URL.

## End report

- **Done:**
  - **Problem report** (D-039): Settings → Report a problem → Create report shows the report in a read-only box, with **Copy report**, **Save report…** (save dialog, written by the shell from the engine's text), and **Open issue page in browser**. Recent log records are filtered again to codes, counts, and durations, without item IDs.
  - **Beta labeling:** a Beta badge in the window header; the README starts with the beta notice, install steps for each system including the unsigned-installer warnings, how to check downloads, and how to report problems.
  - **Issue intake:** bug report and idea templates that ask testers not to paste content and offer the problem report; blank issues off; a private vulnerability route in `SECURITY.md`. Labels `needs-triage`, `P0`–`P3`, `privacy`, and `data-loss` were created on the repository.
  - **Triage order** in `beta.md`: data loss and privacy first, then crashes, then incorrect sources, then features.
  - **Release provenance** (D-040): pinned Node and Rust in the release workflow, `SOURCE_DATE_EPOCH` from the commit, a CycloneDX SBOM (`sbom.py`: 44 engine packages, 608 shell crates, 51 decoder crates, 6 window packages, CPython, and the bundled Tesseract), and a build provenance attestation per installer.
- **Commands run:**
  - Engine: `ruff format --check .`, `ruff check .`, `mypy omnirecall` clean; `pytest -q` 251 passed, 7 skipped locally (the skips are real-model and archive tests that run in the `Real models` CI job).
  - UI: format, lint, typecheck clean; `npm test` 43 passed, including the 3 new report tests with axe.
  - Shell: `cargo fmt --check` clean; clippy and tests in CI.
  - `python scripts/sbom.py`: 692 components, 1 without a license in its metadata (`colorama`, a Windows-only dependency not installed on Linux, so its metadata could not be read there; the SBOM is generated on the Windows runner, where it is).
- **Exit evidence:** see the PR checks. The tag itself waits for two things outside this environment: the project license (a decision for the owner) and turning on private vulnerability reporting in the repository settings (the API refused the change from here).
- **Not done or skipped:**
  - Signing and notarization (no accounts; `release.md`).
  - The manual pass on each OS, which the beta testers' first round should cover (`release.md` checklist).
  - Byte-for-byte reproducible builds are not claimed (D-040).
- **Bugs:** none opened. OR-030 (Windows copyleft DLLs) stays open for the stable release.
- **Docs updated:** `decisions.md` D-039, D-040; the docs listed above.
