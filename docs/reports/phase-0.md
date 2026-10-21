# Phase 0 — Repository and risk spike

## Task brief

- **Phase:** Phase 0. Exit gate: a clean machine can launch the shell and supervised worker; dependencies and model licenses are understood.
- **Acceptance criteria:**
  - Repo with formatter/linter/type-check/test commands, CI, dependency lockfiles, and architecture decision records (`docs/decisions.md`).
  - Tauri-to-worker startup/shutdown; stdio JSON-RPC sidecar round trip, crash detection, and restart.
  - OCR candidates (RapidOCR vs Tesseract 5), embedding model, and `whisper.cpp` validated; choices recorded.
  - Installer size and engine cold-start measured (OR-018).
  - Licenses for every model and native dependency confirmed.
  - Baseline idle RAM/CPU and model-loaded resource usage measured.
- **Files:** repo skeleton per `implementation_plan.md` §3; `services/local-engine/pyproject.toml`, `uv.lock`, `omnirecall/api/*` (JSON-RPC server), `apps/desktop/*` (Tauri + React shell, Rust supervisor), `models/*.json` (manifests), `scripts/*` (spike/measurement scripts), `.github/workflows/ci.yml`, `docs/licenses.md`, `docs/measurements.md`.
- **Tests:** Python tests for the JSON-RPC framing (valid request, malformed JSON, unknown method, oversized line, protocol version mismatch, shutdown); Rust tests for supervisor restart/backoff; a spike script that launches the engine, round-trips `health`, kills it, and verifies restart.
- **Privacy impact:** none captured. Engine opens no network port (verified by test); diagnostics go to stderr without payloads.
- **Defaults used:** none from §11 yet beyond max query length (1,000 chars) used in request validation of `search` once added.

## End report

- **Done:**
  - Repo layout per plan §3; engine pinned with `uv.lock` (Python 3.12), desktop with `package-lock.json` and `Cargo.lock`; ruff/mypy(strict)/pytest, eslint/prettier/tsc(strict)/vitest, rustfmt/clippy/cargo test; CI matrix for Linux, Windows, macOS (`.github/workflows/ci.yml`).
  - Engine JSON-RPC 2.0 stdio server: framing, size limit, parse/invalid/unknown-method errors, sanitized errors, concurrent dispatch, `engine.ready` notification, protocol-version handshake, graceful shutdown on EOF/SIGTERM/`shutdown`, structured content-free logging, no network port (tested).
  - Rust `Supervisor`: spawn, handshake, request correlation with timeouts, notification forwarding, crash detection, exponential backoff (1 s → 30 s), crash-loop stop after 5, manual restart, protocol-mismatch fail-fast, graceful stop with kill fallback. Verified with the real app under Xvfb: SIGKILL of the engine → restarted; app exit → engine stopped.
  - Spikes: OCR (Tesseract chosen, D-012), embeddings (D-013), whisper.cpp runtime (D-014), packaging size and cold start (D-015). Licenses in `docs/licenses.md`; numbers in `docs/measurements.md`.
- **Commands run:**
  - `uv run pytest -q` → 9 passed. `uv run ruff check .` → pass. `uv run mypy` → no issues (19 files).
  - `cargo test` → 7 passed. `cargo clippy --all-targets -- -D warnings` → pass.
  - `npm run typecheck` → pass. `npm run lint` → pass. `npm test` → 1 passed.
  - `python scripts/spike_ocr.py …`, `python scripts/spike_embeddings.py …`, PyInstaller build + cold-start timing, `xvfb-run target/debug/omnirecall` with engine kill → results in `docs/measurements.md`.
- **Not done or skipped:**
  - Startup/shutdown verified on Linux only. Windows and macOS are covered by the CI matrix once pushed; a clean-machine launch on each OS still needs a real machine (Phase 6 clean-install test).
  - Whisper model accuracy/speed not measured: huggingface.co is blocked in the build environment. Needs the `ggml-base.bin` file (Phase 5).
  - Full installer size (Tauri bundle + sidecar) measured in Phase 6 when the sidecar is wired into `externalBin`; engine bundle measured now.
- **Bugs:** opened OR-020 (no macOS x86_64 pywhispercpp wheel). OR-018 updated with measurements (no status change).
- **Docs updated:** `decisions.md` D-012–D-016; `bugs.md` OR-020; new `measurements.md`, `licenses.md`, `README.md`, `models/README.md`.
