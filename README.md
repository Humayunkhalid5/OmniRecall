# OmniRecall

Local-first personal context engine: find what you have already seen, copied, saved, or recorded, without it leaving your device.

> **Beta.** OmniRecall 0.1 is a first public beta for Windows 10/11, macOS 12+ on Apple Silicon, and Linux (.deb, .rpm). Read the known limitations in `CHANGELOG.md` before trusting it with anything important. Installers are not code-signed yet.

## Install

Download the installer for your system from the [Releases](https://github.com/Humayunkhalid5/OmniRecall/releases) page and check it against `SHA256SUMS.txt`. Each installer also has a GitHub build provenance attestation (`gh attestation verify <file> --repo Humayunkhalid5/OmniRecall`).

- **Windows:** run `OmniRecall_<version>_x64-setup.exe`. SmartScreen warns about an unknown publisher; choose More info → Run anyway.
- **macOS:** open the .dmg and drag OmniRecall to Applications. The first time, right-click the app and choose Open.
- **Linux:** `sudo apt install ./omni-recall_<version>_amd64.deb` or `sudo dnf install ./omni-recall-<version>-1.x86_64.rpm`.

Then download the search model in Settings → Local models (83 MB), and, for audio notes, the speech model (148 MB). Everything else works offline. See `docs/troubleshooting.md` if something goes wrong.

## Reporting problems

Settings → Report a problem creates a report with versions, counts, and error codes, and none of your content. Read it, then attach it to a [new issue](https://github.com/Humayunkhalid5/OmniRecall/issues/new/choose). Report anything that could expose someone's data privately instead (`SECURITY.md`). During the beta, data-loss, privacy, crash, and wrong-result problems are fixed before new features (`docs/beta.md`).

See `docs/reports/` for per-phase reports and `docs/bugs.md` for known risks.

## Architecture

- `apps/desktop` — Tauri 2 shell (Rust) + React/TypeScript UI. Rust owns the window, OS permissions, native dialogs, capture integration, and supervises the engine.
- `services/local-engine` — Python 3.12 engine: ingestion, extraction (documents, Tesseract OCR, whisper.cpp), chunking, ONNX embeddings, SQLite (metadata, jobs, FTS5) and LanceDB (vectors), hybrid retrieval.
- The engine is a sidecar speaking JSON-RPC 2.0 over stdin/stdout and **opens no network port** (D-003). The UI can only call an allow-listed set of engine methods; anything that takes a filesystem path goes through Rust, which gets the path from a native dialog or drop event (D-016).

Docs: `docs/prd.md` (what), `docs/design.md` (how, schema, defaults), `docs/implementation_plan.md` (order), `docs/rules.md` (rules, precedence), `docs/decisions.md`, `docs/bugs.md`, `docs/measurements.md`, `docs/licenses.md`.

## Development

Prerequisites: Rust stable, Node 22, [uv](https://docs.astral.sh/uv/) 0.11+, Python 3.12, Tesseract 5 with English data. Linux also needs the Tauri system libraries (`libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev`).

```bash
# Engine
cd services/local-engine
uv sync --frozen --python 3.12
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q

# Desktop
cd apps/desktop
npm ci
npm run lint && npm run typecheck && npm test
OMNIRECALL_ENGINE_SOURCE=$PWD/../../services/local-engine npm run tauri dev
(cd src-tauri && cargo clippy --all-targets -- -D warnings && cargo test)
```

## Privacy

All capture sources start disabled. Captured content, embeddings, queries, and file paths stay on the device; the app sends nothing to any server. The only outbound request is a model download you start yourself. Local storage is **not encrypted** by the app; use OS disk encryption (FileVault, BitLocker, LUKS).
