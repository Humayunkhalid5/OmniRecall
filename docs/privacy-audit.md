# Privacy audit

Phase 3 audit of what leaves the device and what is written to logs. Re-run before every release (bugs.md release checklist).

## Network

| Component | Outbound network | How it was checked |
|---|---|---|
| Engine (Python) | Only `models.py`, for a model download the user starts in Settings (HTTPS only, checksum verified). | `tests/test_network_audit.py::test_only_model_setup_imports_network_modules` scans every engine module's imports. `test_engine_session_makes_no_network_calls` traces a full session (capture, import, indexing with the real model, search, export, delete) with `strace` and finds no `connect`, `sendto`, or `sendmsg` on an IP socket, no `listen`, and no `bind` except urllib3's import-time IPv6 check (a bind to `::1` port 0 that is closed at once, OR-025), and no file created under the home folder outside the data folder. |
| ONNX Runtime | Ships Microsoft 1DS telemetry, on by default: it uploads events to `mobile.events.data.microsoft.com` and keeps a device ID in `~/.cache/Microsoft/DeveloperTools/.onnxruntime/`. The engine turns it off (`ORT_DISABLE_TELEMETRY=1` before load and `disable_telemetry_events()`), see OR-023. | The traced session with the real model. The first version of this audit claimed that session had been run with the model and found nothing; that was wrong, and the telemetry was found in Phase 4. `test_onnxruntime_is_imported_only_with_telemetry_off` keeps the guard in place. |
| Engine dependencies | `tokenizers` could reach Hugging Face if asked to load a model by name; the engine never does, and sets `HF_HUB_OFFLINE=1` and `HF_HUB_DISABLE_TELEMETRY=1`. LanceDB's OpenTelemetry hook does nothing unless an OpenTelemetry SDK is installed and configured, which OmniRecall does not do. | Code reading, plus the syscall trace above with the real model loaded (`OMNIRECALL_TEST_MODELS_DIR`). CI runs the trace without the model until Phase 6. |
| Engine IPC | No listening socket; JSON-RPC over stdin/stdout (D-003). | `test_rpc_server.py::test_engine_opens_no_network_port`. |
| Desktop shell (Rust) | None. The clipboard watcher, tray, and shortcut are local OS APIs. | Dependency review; no HTTP client crate is a direct dependency. |
| Web UI | Content Security Policy allows only `'self'` and the Tauri IPC origin (`connect-src ipc: http://ipc.localhost`); no remote scripts, fonts, or images. | `tauri.conf.json`. |

## Logs

The engine writes JSON lines to stderr and `logs/engine.log`. `logs.py` keeps only an allow-list of fields (event, IDs, counts, codes, durations); values are scalars. Captured text, queries, file paths, app names, and exclusion values are never logged.

Checked by `tests/test_privacy.py::test_logs_never_contain_captured_text_or_queries`, which turns on debug logging, runs clipboard capture (stored, excluded, and secret copies), search, paste import, and delete, and asserts that no marker word, app name, or query appears in the log.

Phase 3 live run: the engine log after real clipboard copies contained only `clipboard_capture` events with an outcome (`captured`, `sensitive`, `duplicate`), and the copied text appeared nowhere in the data folder for copies made before capture was on, while it was paused, or that looked like a secret.

## Storage of filtered copies

Copies dropped as too large, excluded, unknown-app, or possibly secret are not written anywhere: no item, no hash, no payload file (D-022). Only per-session counters in memory record that filtering happened.

## Screenshots (Phase 4)

- **Before capture:** nothing is captured while screenshot capture is off or paused, the screen is locked, the user is idle, OS permission is missing, OmniRecall is in front, or an app exclusion applies. If app exclusions exist and the front app is unknown, nothing is captured either.
  - Tests: `tests/test_screenshots.py` for the engine side, and the shell `screenshot.rs` tests for hashing and file handling.
  - Live run on Xvfb: pause shortcut, idle pause, and fail-closed exclusion.
- **Frames written to disk:** frames go to `media/incoming/` with user-only permissions and are removed by the engine in every outcome. The engine also clears leftovers at start.
  - Unchanged frames are dropped before they are written.
  - Frames dropped after OCR (no text, excluded text, secret-looking text, same text) leave no row, job, image, or thumbnail (D-028).
  - In the live run, a terminal showing a GitHub token was dropped as `sensitive`. A search of the data folder found no trace of the token.
- **Logs:** they record outcome codes only (`screenshot_capture` with a status). `test_logs_never_contain_ocr_text` checks that OCR text, app names, and queries never appear. In the live run, the engine log held no captured words.
- **Network:** Tesseract runs as a local child process. The traced audit session (`test_engine_session_makes_no_network_calls`) now includes image import and a screenshot, and strace follows child processes.
