# OmniRecall — Bug and Risk Register

**Purpose:** living register for verified defects, unresolved engineering risks, and release blockers.  
**Status convention:** `OPEN`, `IN PROGRESS`, `BLOCKED`, `FIXED`, `WONT FIX`.  
**Important:** Entries marked `RISK` are anticipated risks from the proposed design, not claims that the implementation has already been tested and found defective.

## Open risks before implementation

| ID | Type / Priority | Item | Impact | Required action / acceptance evidence | Status |
|---|---|---|---|---|---|
| OR-001 | RISK / P0 | Total runtime memory target of less than 20 MB is unrealistic with Python, OCR, embeddings, and transcription models loaded | Misleading product claim; performance failures | Define separate idle, search, OCR, and transcription memory budgets; benchmark on reference hardware; publish measured results Phase 6 measured, packaged engine on REF-CI-LINUX: 159 MB idle, 382 MB with the search model loaded; the shell 174 MB (Phase 0, debug). CPU and battery during capture on a real laptop are still unmeasured (`measurements.md`). | OPEN |
| OR-002 | RISK / P0 | Desktop and mobile background capture capabilities differ substantially | Mobile scope may be infeasible or violate platform rules | Keep mobile background capture out of MVP; design a separate companion for user-selected imports/voice notes | OPEN |
| OR-003 | RISK / P0 | Screenshot and clipboard capture can collect highly sensitive content | Privacy and trust failure | Capture off by default, explicit consent, persistent indicator, global pause, exclusions, offline verification, and privacy tests | OPEN |
| OR-004 | RISK / P0 | SQLite and LanceDB do not share a single ACID transaction | Search may return deleted/orphaned chunks or metadata | Implement tombstones, retryable reconciliation, consistency checks, and index rebuild; test crash between every cross-store write Phase 6: fault injection crashes the engine at every cross-store write point and checks that restart converges (`test_fault_injection.py`); a damaged vector index is rebuilt from SQLite (D-035) and a damaged database opens in recovery mode (D-036). | FIXED |
| OR-005 | RISK / P1 | The proposed 5% pixel-difference threshold may skip meaningful changes or retain too many frames | Recall or storage degradation | Compare perceptual hash and changed-pixel ratio; make threshold configurable; test scrolling, animation, cursor, multi-monitor, and static screens | OPEN |
| OR-006 | RISK / P1 | Model and OCR library licenses may constrain bundling or commercial use | Release or distribution blocked | Verify and record license, attribution, source, version, and checksum for every dependency/model before packaging | OPEN |
| OR-007 | RISK / P1 | Embedding model/tokenizer preprocessing mismatch can degrade search | Incorrect semantic retrieval | Pin tokenizer/model versions; add known-vector and retrieval regression tests; version all vectors | OPEN |
| OR-008 | RISK / P1 | Clipboard exclusions cannot guarantee detection of all passwords or secrets | Sensitive text may be indexed | Clearly describe best-effort filtering; allow source/app exclusions and disable toggle; never promise complete secret detection | OPEN |
| OR-009 | RISK / P1 | Local API may be abused by another local process or browser context | Unauthorized access to indexed content | Use the stdio JSON-RPC sidecar with no network port (decision D-003); if the HTTP fallback is ever used: loopback-only binding, per-launch token, strict origin checks, input limits, and security tests Evidence: the engine speaks JSON-RPC over stdio only and opens no port; `test_network_audit.py` checks for no listening socket and no outbound connection, with the real models installed in the `Real models` CI job. | FIXED |
| OR-010 | RISK / P1 | Document parsing and OCR may hang, crash, or consume excessive resources on malformed/large files | Data loss or app unresponsiveness | Apply file/page/duration limits, timeouts, worker isolation where practical, cancellation, and clear error states | OPEN |
| OR-011 | RISK / P1 | Search relevance has no evaluation corpus yet | Product may feel unreliable despite working technically | Create a labeled local test corpus and query set; track recall@k and ranking metrics before tuning Evidence: labeled corpus and queries in `tests/fixtures/eval/`, recall@10 and MRR per mode recorded in `measurements.md` and re-run in CI. | FIXED |
| OR-012 | RISK / P2 | Native capture permissions and APIs vary by operating system/version | Uneven platform support | Maintain a tested support matrix; handle denied/unavailable states; do not claim unsupported platforms | OPEN |
| OR-013 | RISK / P2 | Model download and update process may introduce supply-chain risk | Malicious or corrupted model files | Use pinned sources, checksums, license display, user-approved downloads, and safe replacement behavior Evidence: pinned URLs and SHA-256 in the model manifests, user-started downloads only, a mismatched file is refused and never installed (`test_models.py`). | FIXED |
| OR-014 | RISK / P2 | Uninstall, backup, and data-retention expectations are undefined on each OS | Users may lose data or leave sensitive files behind | Document uninstall behavior; offer export and clear-data flows; test upgrade and uninstall scenarios Phase 6: uninstall keeps the data folder on every OS, documented in `troubleshooting.md` and `privacy.md`; the release workflow installs, reinstalls, and uninstalls each package and checks the data survives; upgrades from every earlier schema are tested (`test_upgrade.py`). | FIXED |
| OR-015 | RISK / P1 | Linux Wayland routes screenshots through xdg-desktop-portal, which on many compositors asks the user per capture or per session; clipboard reads may require window focus | Periodic screenshot capture may be impossible or interactive on Wayland | Test GNOME and KDE on Wayland plus X11; ship Linux periodic capture as X11-only or clearly unavailable if silent capture is not permitted; record results in the support matrix | OPEN |
| OR-016 | RISK / P1 | Recent macOS versions periodically ask users to re-approve screen recording; Windows capture APIs differ by version | Capture stops unexpectedly or behaves differently per OS version | Treat revoked permission as the permission-denied UX state; never prompt repeatedly; record behavior per OS version in the support matrix | OPEN |
| OR-017 | RISK / P0 | Deleted content can survive in LanceDB old table versions, SQLite free pages, and the SQLite WAL file | Privacy breach: "deleted" data is recoverable from disk | Implement physical deletion (`design.md` §7); regression test scans raw store files for a deleted marker string Evidence: physical deletion (`design.md` §7); `test_deletion.py` scans every file in the data folder, including the database, its WAL, and the vector files, for a deleted marker string. | FIXED |
| OR-018 | RISK / P1 | Bundling Python, ONNX Runtime, and models makes installers large and engine start slow; every embedded native binary must be signed/notarized on macOS | Poor install experience; release blocked by signing | Measure installer size and cold start in Phase 0; make large models optional user-approved downloads; include sidecar binaries in the signing pipeline. Phase 0 measured: frozen engine 462 MB unpacked / 180 MB gzip, cold start ~150 ms (`measurements.md`) Phase 6: installers 144 MB (Windows), 203 MB (macOS), 259 MB (Linux .deb), models downloaded separately; packaged engine ready in 1.0-1.6 s. Signing is still not set up (`release.md`). | OPEN |
| OR-019 | RISK / P2 | The embedding model truncates inputs at about 256 tokens and handles non-English text poorly | Missed results for long chunks and non-English content | Verify chunk token length in the chunker; keep a non-English query set in the evaluation corpus; MVP claims English only | OPEN |
| OR-020 | RISK / P2 | `pywhispercpp` publishes no macOS x86_64 wheel | Audio transcription unavailable on Intel Macs | Build whisper.cpp from source in the macOS x86_64 release job, or mark audio transcription unavailable on Intel Macs in the support matrix. Phase 5: still open; the support matrix marks Intel Macs as not built yet | OPEN |
| OR-030 | RISK / P1 | The Windows Tesseract bundle (UB Mannheim build) loads libcurl and, through LibTIFF, JBIG-KIT (GPL-2.0-or-later), plus four LGPL libraries curl needs | Copyleft obligations (source availability) for those DLLs; a network-capable library ships although OmniRecall only ever passes local file paths | Phase 6: bundle reduced to what `tesseract.exe` imports, every DLL mapped to a reviewed license and its text shipped (`third_party_licenses/README.md`). Before the stable release, build Tesseract and Leptonica for Windows without libcurl and JBIG (for example vcpkg, static), so only permissive libraries remain | OPEN |

## Verified defects

No implementation has been inspected or executed as part of preparing this specification. Defects below were observed in the implementation itself. Do not convert the risks above into claims of observed defects.

### OR-021 — Engine ignored a `shutdown` request until stdin closed
- **Type:** BUG
- **Priority:** P2
- **Status:** CLOSED
- **Environment:** Linux, engine 0.1.0 run directly (not under the desktop shell).
- **Steps to reproduce:**
  1. Start `omnirecall-engine --data-dir <dir>` with a pipe on stdin.
  2. Send a `shutdown` request and keep stdin open.
- **Expected:** the engine answers and exits.
- **Actual:** it answered `{"stopping": true}` but stayed blocked reading stdin until EOF. The desktop shell was not affected, because it closes stdin right after `shutdown`.
- **Evidence:** a seeding script hung for 20 s waiting on the process (Phase 2 live run).
- **Root cause:** `request_stop` only set a flag; the main thread was blocked in `readline` and never rechecked it.
- **Fix plan:** after answering, interrupt the main thread's read with a signal aimed at that thread (POSIX). On Windows the shell's stdin close remains the stop path.
- **Regression test:** `tests/test_rpc_server.py::test_real_engine_exits_on_shutdown_request_with_stdin_open`.
- **Resolution:** fixed in Phase 2 and verified by the regression test.

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

- [x] No network transfer of captured content, embeddings, queries, or file paths.
- [x] Capture is off by default and fully stops when paused/disabled.
- [x] Delete and clear-index remove data from SQLite, FTS5, LanceDB, and owned media, and deleted content cannot be found in raw store files (including the WAL and old LanceDB versions).
- [x] Crash recovery and index reconciliation pass fault-injection tests.
- [x] The engine opens no network port; if the HTTP fallback is used, it is not reachable from the LAN and requires authentication.
- [x] Relevance (recall@10, MRR) and latency results are recorded against the labeled evaluation corpus.
- [x] Model/dependency licenses and checksums are documented. (Windows copyleft DLLs: OR-030.)
- [ ] Resource and search latency results are measured on documented hardware.
- [x] Clean install, upgrade, and uninstall behavior are tested.

### OR-029 — The first real speech-to-text check failed for the wrong reasons
- **Type:** BUG (test)
- **Priority:** P2
- **Status:** CLOSED
- **Environment:** GitHub `ubuntu-24.04` runner, whisper.cpp `base` (`ggml-base.bin`, SHA-1 `465707469ff3…`), engine 0.1.0.
- **Steps to reproduce:**
  1. Install the real speech model and run `test_real_model_transcribes_fixtures_offline` (Phase 5 version).
- **Expected:** the gate measures whether recordings are transcribed well enough to be found.
- **Actual:** `recipe.ogg` failed at 42.9% WER. Whisper wrote "40 minutes" where the script says "forty minutes", and the check counted every number as an error. After normalizing numbers the clip is still at 32%, because the espeak-ng voice made "of flour" sound like "sunflower".
- **Evidence:** first `Real models` job on PR #6; transcripts in `measurements.md` Phase 6.
- **Root cause:** the metric lacked the number normalization speech benchmarks use, and a per-fixture 25% bound on robotic synthetic voices measured the voice more than the model.
- **Fix plan:** normalize WER (`tests/wer.py`), gate on findability with the real models, and measure accuracy on real speech (D-038).
- **Regression test:** `tests/test_audio.py::test_real_models_make_every_recording_findable` and `::test_real_model_transcribes_fixtures_offline` (now with a 35% sanity bound) in the `Real models` CI job.
- **Resolution:** fixed in Phase 6; the job passes, and LibriSpeech WER is 9.8% on 73 recordings.

### OR-028 — A corruption test raced the engine's own start-up repair
- **Type:** BUG (test)
- **Priority:** P3
- **Status:** CLOSED
- **Environment:** REF-CI-LINUX; failed in about 5 of 6 runs once the full suite ran in parallel with other work.
- **Steps to reproduce:** `pytest tests/test_corruption.py::test_damage_found_while_running_falls_back_then_repairs`.
- **Expected:** the test damages the vector table under a running engine, then sees search fall back to keywords.
- **Actual:** search still used vectors. The engine's start-up reconciliation had not run yet when the test damaged the files, so it found the damage first and rebuilt the table before the search.
- **Root cause:** the test waited for `index.verify` to report consistent, which is already true before the start-up reconciliation runs. The engine behaved correctly.
- **Fix plan:** the engine sets `startup_reconciled` when its start-up reconciliation has finished; the test waits for it before damaging the table.
- **Regression test:** the same test, run 8 times in a row without a failure.
- **Resolution:** fixed in `app.py` and `tests/test_corruption.py`.

### OR-027 — Engine crashed with a segmentation fault on exit after transcribing
- **Type:** BUG
- **Priority:** P1
- **Status:** CLOSED
- **Environment:** REF-CI-LINUX, Python 3.12, `pywhispercpp` 1.5.1.
- **Steps to reproduce:** transcribe one recording, then shut the engine down.
- **Expected:** the engine exits with code 0.
- **Actual:** the process exited with signal 11 (exit code -11) after the shutdown reply.
- **Root cause:** whisper.cpp's log output was redirected to a Python lambda. At interpreter shutdown the lambda was freed while the native library still held a pointer to it, and the model's destructor logged through that pointer.
- **Fix plan:**
  - Route whisper.cpp logs to a module-level function that lives as long as the process.
  - Free the model in `Engine.close()` before the database closes, and reset the log callback after the model is freed.
  - Also free the model and reset the callback on the idle unload and in an `atexit` hook, which runs before module teardown. The first fix missed two paths: a model already unloaded by the idle timer left the callback set, and a process that exited without `close()` depended on teardown order. CI found the second on Windows.
- **Regression test:** `tests/test_audio.py::test_process_exits_cleanly_after_a_transcription`, with an explicit close, a plain exit, and an idle unload followed by close. Each case crashed before its fix.
- **Resolution:** fixed in `extraction/transcribe.py` and `app.py`.

### OR-026 — Cancelling an item while it was being transcribed did not stop it
- **Type:** BUG
- **Priority:** P2
- **Status:** CLOSED
- **Environment:** REF-CI-LINUX.
- **Steps to reproduce:** import a long recording and press **Cancel** while it shows "Transcribing".
- **Expected:** transcription stops within a second or two and the item shows "Processing was cancelled".
- **Actual:** transcription ran to the end and the item was indexed.
- **Root cause:** the worker checked only for engine shutdown between stages. A cancel marks the job `cancelled` in the database, and nothing running read it.
- **Fix plan:** the stage check (`_check_live`) also stops on a cancelled job, and the transcriber's abort callback re-reads the job status at most every 0.5 s. The decoder child process is killed when the stream is abandoned.
- **Regression test:** `tests/test_audio.py::test_cancel_stops_a_running_transcription`. It fails without the fix.
- **Resolution:** fixed in `ingestion/pipeline.py`.

### OR-025 — Network audit failed on CI runners with IPv6: an IPv6 check, not a connection
- **Type:** BUG (test)
- **Priority:** P2
- **Status:** CLOSED
- **Environment:** GitHub Actions `ubuntu-24.04` (IPv6 loopback available). The build sandbox has no IPv6, so the call failed there before reaching `bind` and the audit passed.
- **Steps to reproduce:** run `tests/test_network_audit.py::test_engine_session_makes_no_network_calls` on a Linux host with IPv6.
- **Expected:** the audit passes when the engine makes no network calls.
- **Actual:** the trace held one call, `bind(AF_INET6, "::1", port 0) = 0`, and the audit failed.
- **Root cause:** `lancedb` imports its REST namespace client, which imports `urllib3`. At import time urllib3 checks whether IPv6 works by binding a socket to `::1` port 0 and closing it. Nothing connects, sends, or listens; the engine still opens no port. (Traced with a Python audit hook: `lancedb/__init__` → `lance_namespace_urllib3_client` → `urllib3.util.connection._has_ipv6`.)
- **Fix plan:** the audit allows only a `bind` to a loopback address on port 0, also traces `listen`, and fails on any `listen` call, so a probe can never become an open port. Every `connect`, `sendto`, and `sendmsg` on an IP socket still fails the audit.
- **Regression test:** the audit itself, now green on the IPv6 runner.
- **Resolution:** fixed in the test. No engine change was needed.

### OR-023 — ONNX Runtime sent telemetry to Microsoft and kept a device ID
- **Type:** BUG (privacy)
- **Priority:** P0
- **Status:** CLOSED
- **Environment:** Linux, engine 0.1.0 with `onnxruntime==1.31.0` and the MiniLM model installed. The library code is the same on Windows and macOS.
- **Steps to reproduce:**
  1. Start the engine with an installed embedding model.
  2. Import a text and let it index (the model loads).
  3. Trace the process with `strace -f -e trace=connect,sendto,openat`.
- **Expected:** no network connection and no files outside the data folder (rules.md §1.1, §1.5).
- **Actual:** a background thread sent `CONNECT mobile.events.data.microsoft.com:443` (here through the sandbox's HTTP proxy) and ONNX Runtime created `~/.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db`, a telemetry store with a device ID. It did not happen on every run, which is why the Phase 3 audit missed it.
- **Evidence:** the strace output above, found while extending the network audit in Phase 4. The string `events.data.microsoft.com` is in `onnxruntime/capi/libonnxruntime.so.1.31.0`, built with 1DS telemetry (`telemetry_1ds.cc`).
- **Root cause:** ONNX Runtime 1.31 enables Microsoft 1DS telemetry by default on every platform. The engine did not turn it off.
- **Fix plan:** set `ORT_DISABLE_TELEMETRY=1` at engine start and before the library is imported, and call `onnxruntime.disable_telemetry_events()` before a session is created.
- **Regression tests:** `tests/test_network_audit.py::test_onnxruntime_is_imported_only_with_telemetry_off` (static: the only import goes through the guarded helper) and `test_engine_session_makes_no_network_calls`, which now also fails on any file created under the home folder outside the data folder. The runtime test needs the real model (`OMNIRECALL_TEST_MODELS_DIR`); CI does not have it yet, so Phase 6 adds a model download to the release audit job.
- **Resolution:** fixed. With the fix, repeated traced sessions with the real model show no `AF_INET` calls and no telemetry files. Without it, the same test fails.

### OR-022 — Requests in flight at shutdown could lose their reply
- **Type:** BUG
- **Priority:** P2
- **Status:** CLOSED
- **Environment:** Linux, engine 0.1.0 run directly with stdin left open.
- **Steps to reproduce:** send several requests and then `shutdown` in one write, keeping stdin open.
- **Expected:** every request is answered, then the engine exits cleanly.
- **Actual:** sometimes a reply was missing and a `Traceback` was printed on exit.
- **Root cause:** every request that finished after the stop flag was set signalled the main thread again (the OR-021 fix). A second signal raised inside the shutdown path.
- **Fix plan:** signal the main thread once, and have the signal handler ignore further signals once shutdown has begun.
- **Regression test:** `tests/test_rpc_server.py::test_requests_in_flight_at_shutdown_are_answered` (fails 4 of 4 runs without the fix).
- **Resolution:** fixed.

### OR-024 — Pausing capture reset the screenshot interval in the shell
- **Type:** BUG
- **Priority:** P2
- **Status:** CLOSED
- **Environment:** Linux (Xvfb), debug desktop build, Phase 4 branch.
- **Steps to reproduce:** set the screenshot interval to 5 s, then pause and resume capture, or leave and reopen Settings.
- **Expected:** the 5 s interval stays.
- **Actual:** the timing field showed 30 again. The shell could also fall back to the 30 s default, because the `capture.state` notification sent on pause carried no screenshot settings.
- **Evidence:** Phase 4 live run.
- **Root cause:** `_capture_changed` sent the bare snapshot, not the full state that `capture.state` returns.
- **Fix plan:** notify with the full state.
- **Regression test:** `tests/test_screenshots.py::test_watcher_settings_are_published_with_capture_state` (asserts the pause notification carries the interval).
- **Resolution:** fixed. Re-checked in the live run: the field kept 5 s after the app restarted.

### Phase 3 notes

- **OR-003:** mitigations in place for clipboard: capture off by default, explicit opt-in on the first-run screen and in settings, tray and header indicator, global pause (tray, header, CommandOrControl+Alt+Shift+P), per-source pause, app/folder/pattern exclusions, dropped copies leave no trace (D-022), and the network audit in `docs/privacy-audit.md`. Stays OPEN until screenshots (Phase 4) carry the same controls and the beta privacy review passes.
- **OR-008:** `capture/sensitive.py` detects common key and token formats, credential assignments, connection strings with passwords, Luhn-valid card numbers, and lone password-like tokens. The settings page says detection is best effort and offers the on/off switch and exclusions. Stays OPEN by design: complete detection cannot be promised.
- **OR-015:** clipboard reading on Linux works on X11 and on Wayland compositors with the data-control protocol (arboard `wayland-data-control`); global shortcuts may not register on Wayland, and the tray needs an AppIndicator host. Recorded in `docs/support-matrix.md`. The screenshot half is Phase 4 work; stays OPEN.

### Phase 4 notes

- **OR-003:** the screenshot source now has the same controls as the clipboard:
  - off by default;
  - first-run explanation;
  - tray and header indicator;
  - global and per-source pause and the shortcut;
  - app and text exclusions (fail closed);
  - lock and inactivity pause;
  - OmniRecall's own window skipped;
  - best-effort secret filter on OCR text;
  - retention, text-only mode, and the media cap.

  It stays OPEN until the beta privacy review (Phase 7).
- **OR-015:** screenshots run on X11 (verified on Xvfb) and are disabled on Wayland with an explanation. GNOME and KDE on real hardware are still untested. It stays OPEN until those runs in Phase 6.
