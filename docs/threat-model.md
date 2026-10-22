# Threat model

What OmniRecall protects, from whom, and where it stops. Written for Phase 6 from the code as it is; each control names the test or decision that backs it. Re-check before each release, together with `privacy-audit.md`.

## What is worth protecting

- **Captured and imported content:** clipboard text, recognized screen text and the screenshots themselves, document text, transcripts, and the original audio and images OmniRecall stores.
- **Derived data:** embeddings (they can leak meaning), the keyword index, and item metadata (source app, file path, time).
- **Queries:** what the user searches for. Searches are not stored unless the user turns on recent searches (off by default).
- **Exclusions:** the list itself shows which apps and patterns the user considers sensitive.

## Trust boundaries

```text
 user ── UI (React, WebView) ──IPC allow-list── Rust shell ──stdio JSON-RPC── Python engine
                                                    │                            │
                                         OS: clipboard, screen,          data folder (SQLite,
                                         dialogs, tray, shortcuts         LanceDB, media, logs)
                                                                                 │
                                                          child processes: Tesseract, audio decoder
```

1. **WebView to shell.** The UI can only call commands the shell registers, and only the engine methods on its allow-list (`commands.rs`, `UI_METHODS`). Methods that take a file path are not on it: paths come from native dialogs or drag-and-drop in Rust (D-016). The Content Security Policy allows no remote scripts, styles, images, or connections.
2. **Shell to engine.** The engine is a child process speaking JSON-RPC over stdin and stdout. It opens no network port, so no other local process or web page can reach it (D-003, `test_engine_opens_no_network_port`). Requests are size-capped and schema-validated.
3. **Engine to files it reads.** Imported files, screenshots, and audio are untrusted input. See "Malicious files" below.
4. **Engine to the network.** Only a model download that the user starts (HTTPS, pinned URL, checksum verified before use).

## Threats and controls

| # | Threat | Control | Evidence |
|---|---|---|---|
| T1 | Content leaves the device | No network code outside the model downloader; ONNX Runtime telemetry off; Hugging Face libraries forced offline | `test_network_audit.py` (import scan and a full traced session), OR-023 |
| T2 | Another local program or website reads the index through an API | No listening socket; stdio only | D-003, `test_rpc_server.py` |
| T3 | Capture runs without the user knowing | Every source starts off; a capture indicator shows in the window and the tray; one shortcut pauses everything; capture stops whenever the engine is not running | D-024, `privacy.test.tsx` |
| T4 | Sensitive content is captured | App and pattern exclusions, checked before capture (fail closed when the app is unknown); secret detection on clipboard and screen text (best effort, OR-008); OmniRecall's own window is never captured | `test_privacy.py`, `test_screenshots.py`, `test_sensitive.py` |
| T5 | Deleted content can still be recovered from the app's files | Physical deletion: SQLite `secure_delete` zeroes freed pages, the FTS index is optimized, the WAL is checkpointed, LanceDB is compacted and old versions are cleaned up, and stored media files are deleted. Clearing the whole index also vacuums the database | D-007, `test_deletion.py` raw-file scans, fault injection on every deletion step (`test_fault_injection.py`) |
| T6 | Logs leak content | Logs keep only an allow-list of fields: events, IDs, counts, codes, durations. Never text, queries, paths, app names, or exclusion values | `test_privacy.py::test_logs_never_contain_*` |
| T7 | A malicious file attacks the engine | Size, page, pixel, and duration limits; first frame only for images; Tesseract and the audio decoder run as separate processes (Tesseract with a time limit; the decoder's probe with a time limit, and decoding stops at the length limit); nothing in a document is executed or followed; HTML is parsed for text only | `formats.md`, `test_extraction.py`, `test_ocr.py`, `test_audio.py` |
| T8 | A tampered or wrong model file | Pinned URLs; SHA-256 of the archive and of every file (embedding model) or the published SHA-1 (Whisper) checked before install; staged, then renamed into place | `test_models.py`, OR-013 |
| T9 | A crash or full disk corrupts data | SQLite WAL with one transaction per write; vector writes through an outbox; reconciliation at every start; damaged indexes rebuilt from SQLite; a damaged database opens in recovery mode instead of being used | D-035, D-036, `test_fault_injection.py`, `test_corruption.py`, `test_database_damage.py` |
| T10 | The UI is tricked into passing a path or running a command | No path-taking engine method is callable from the UI; `freezePrototype`; no `eval` or remote content | `commands.rs` tests |
| T11 | Another user on the same computer reads the data | The data folder is created with owner-only permissions on macOS and Linux; on Windows it is in the user's own AppData | `paths.rs` test |
| T12 | An old export or a downgrade destroys data | Exports are separate zip files with checksums; a database from a newer version is reported and never changed | D-026, `test_database_damage.py` |

## Not protected (stated limits)

- **Encryption at rest:** OmniRecall does not encrypt its data folder. Anyone who can read the user's files, or a stolen disk without OS disk encryption, can read it. Use FileVault, BitLocker, or LUKS.
- **Malware running as the user:** it can read the data folder, the clipboard, and the screen directly. OmniRecall cannot defend against it.
- **Secret detection:** pattern-based and best effort. It will miss secrets that do not look like known formats; use exclusions for password managers and other sensitive apps.
- **Backups and sync:** if the data folder is inside a folder that is backed up or synced (for example a synced home folder), copies leave OmniRecall's control, and deletion cannot reach them.
- **Files outside the data folder:** OmniRecall never deletes or changes the files you import. Deleting an item removes OmniRecall's copy of the text, not your original.
- **Blocks the file system keeps:** deleted media files are removed, not overwritten. On SSDs and copy-on-write file systems (APFS, Btrfs), old blocks and snapshots can survive until the system reuses them. OS disk encryption covers this.
- **Unsigned installers:** this release is not code-signed (`release.md`). Check the SHA-256 checksums published with each release.

## Review triggers

Re-run this review when any of these change: a new capture source, a new engine method on the UI allow-list, any network code, a new native dependency or child process, the data folder layout, or the deletion steps.
