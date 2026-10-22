# Changelog

## 0.1.0 (unreleased, first beta)

The first packaged version of OmniRecall: a local-first app that indexes what you import, copy, and see on screen, and finds it again by keywords and meaning. Nothing leaves your computer.

### Features
- Import documents (text, Markdown, CSV, JSON, HTML, PDF text layer, Word .docx), images (OCR with Tesseract, English), and audio files (transcribed on this device with whisper.cpp `base`). See `docs/formats.md`.
- Clipboard and screenshot capture, both off until you turn them on, with a capture indicator, a global pause shortcut, app and pattern exclusions, and best-effort secret detection.
- Hybrid search (SQLite FTS5 keywords and MiniLM embeddings), with relevance labels, an explanation of each match, filters by source, date, and format, and the time in the recording for passages from audio.
- Physical deletion of items and of the whole index; export to a documented zip format; screenshot retention and a media cap.
- Self-repair: crashes during any write converge on restart; a damaged search index is rebuilt from the database; a damaged database opens in a recovery screen that can save the readable part.
- Installers for Windows (NSIS), macOS (Apple Silicon .dmg), and Linux (.deb, .rpm). On Windows, OCR is a single static Tesseract with only permissively licensed libraries and no network library.
- Settings → Report a problem: a report with versions, counts, and error codes, and none of your content, that you read and then copy or save; nothing is sent by the app.
- Each release comes with checksums, a software bill of materials, and build provenance attestations.

### Known limitations
- The data folder is not encrypted by OmniRecall; use OS disk encryption.
- Installers are not code-signed or notarized; Windows and macOS will warn on first launch.
- No Intel Mac build. No screenshot capture on Linux Wayland.
- English only for OCR and search quality. Speech is recognized in other languages, but search for non-English text is only lightly evaluated.
- Speech-to-text uses Whisper `base`: about 10% of words wrong on clear read English speech (LibriSpeech sample), more on names, rare words, and noisy recordings. Search still finds recordings by their other words, but quotes from transcripts may be wrong (`docs/measurements.md`).
- The engine uses about 160 MB of memory when idle and about 380 MB with the search model loaded. Building a library of 100,000 passages and searching it peaks at about 850 MB on Linux.
- Secret detection is pattern-based and will miss some secrets; use exclusions for sensitive apps.

See `docs/privacy.md`, `docs/threat-model.md`, `docs/troubleshooting.md`, and `docs/support-matrix.md`.
