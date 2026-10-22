# Building and releasing

How installers are made, what is checked, and what is not done yet (D-037).

## What an installer contains

| Part | Where it comes from |
|---|---|
| App shell (Rust, Tauri 2) and UI | `apps/desktop`, built by `tauri build` |
| Engine (Python 3.12, frozen) | PyInstaller one-dir build of `services/local-engine` (`packaging/omnirecall-engine.spec`), about 510 MB unpacked |
| Audio decoder | `services/audio-decoder`, release build, in the engine folder |
| Tesseract 5 with English data | Windows: the UB Mannheim build from Chocolatey. macOS: Homebrew's, with its libraries copied in and made relative (`dylibbundler`) and signed ad hoc. Linux: not bundled; the .deb and .rpm depend on the distribution's packages |
| License notices | `docs/licenses.md`, plus each Python package's license files inside the engine folder |

Models are not in the installer. The user downloads them in Settings (`licenses.md`).

The engine folder is placed in the app's resources as `engine/` (`tauri.release.conf.json`). The shell starts `<resources>/engine/omnirecall-engine` (`paths.rs`); the engine finds the decoder and Tesseract next to its own executable.

## Build locally

```bash
cd services/local-engine && uv sync --frozen --python 3.12 && cd ../..
uv run --project services/local-engine --frozen python scripts/package_engine.py
uv run --project services/local-engine --frozen python scripts/smoke_engine.py \
    apps/desktop/src-tauri/resources/engine/omnirecall-engine --require-ocr
cd apps/desktop && npm ci
npx tauri build --config src-tauri/tauri.release.conf.json --bundles deb   # or rpm, dmg, nsis
```

Windows needs Tesseract installed (`choco install tesseract`); macOS needs `brew install tesseract dylibbundler`.

## What the release workflow checks

`.github/workflows/release.yml` runs on every `v*` tag, on demand, and on pull requests that change packaging. On Ubuntu 22.04, macOS 14 (Apple Silicon), and Windows Server 2022 it:

1. builds the engine folder and runs `smoke_engine.py` on it: start-up, health, the bundled decoder and Tesseract, a model download through the engine's own checksum-verified downloader, indexing, search, and a clean exit;
2. builds the installers: .deb and .rpm, .dmg, NSIS .exe;
3. installs the package on the runner and runs `install_check.py`: the installed engine passes the smoke test, the app starts on a fresh user profile and its engine creates the database, a marker item is saved, the package is installed again over itself and the marker survives, and after uninstalling the program is gone and the data is still there. On macOS and Windows the system Tesseract is removed first, so OCR has to work from the bundled copy.

A tag also creates a draft pre-release with the installers, `SHA256SUMS.txt`, and `CHANGELOG.md` as notes.

Verified so far: the Linux .deb was built, installed, reinstalled, and removed with these scripts on REF-CI-LINUX (Ubuntu 24.04). The macOS and Windows jobs are verified only when the workflow has run on them; see the Phase 6 report.

## Not done yet

- **Code signing and notarization.** Installers are unsigned. Windows SmartScreen and macOS Gatekeeper will warn; on macOS, open the app with right-click → Open the first time. Signing needs accounts the project does not have yet:
  - macOS: a Developer ID Application certificate and an Apple ID for notarization. Every Mach-O file in `engine/` (the engine executable, Python extension modules, Tesseract and its libraries, the decoder) must be signed with the hardened runtime before `tauri build`, because Tauri signs only the app's own binaries. Then set `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, and `APPLE_TEAM_ID` for Tauri.
  - Windows: an Authenticode certificate, set as `bundle.windows.certificateThumbprint` or a `signCommand` that signs the app, the engine executable, the decoder, and Tesseract.
- **Intel Macs:** no x86_64 build (OR-020: `pywhispercpp` has no x86_64 wheel).
- **Upgrade from an earlier installer:** this is the first packaged version, so the workflow can only reinstall over itself. Upgrades of the data itself, from every earlier schema, are tested in `tests/test_upgrade.py`.
- **AppImage:** not built, because it cannot depend on the system Tesseract.

## Release checklist

Before a tag:

- [ ] CI and the release workflow are green on all three systems.
- [ ] `privacy-audit.md` re-run (network trace with the real model) and `threat-model.md` reviewed.
- [ ] `measurements.md` updated for this version; relevance not lower than the last release.
- [ ] `licenses.md` checked against `uv.lock`, `Cargo.lock`, and `package-lock.json`.
- [ ] `CHANGELOG.md` lists changes and known limitations; the version is set in `tauri.conf.json`, `Cargo.toml`, `package.json`, and `pyproject.toml`.
- [ ] Manual pass on each system: first run, capture on and off, pause shortcut, exclusions, delete, Delete everything, export, offline use after models are installed (PRD §10).
