# Changelog

## 0.1.0 (unreleased, first beta)

The first packaged version of OmniRecall: a local-first app that indexes what you import, copy, and see on screen, and finds it again by keywords and meaning. Nothing leaves your computer.

### Features
- Import documents (text, Markdown, CSV, JSON, HTML, PDF text layer, Word .docx), images (OCR with Tesseract, English), and audio files (transcribed on this device with whisper.cpp `base`). See `docs/formats.md`.
- Clipboard and screenshot capture, both off until you turn them on, with a capture indicator, a global pause shortcut, app and pattern exclusions, and best-effort secret detection.
- Hybrid search (SQLite FTS5 keywords and MiniLM embeddings), with relevance labels, an explanation of each match, filters by source, date, and format, and the time in the recording for passages from audio.
- Physical deletion of items and of the whole index; export to a documented zip format; screenshot retention and a media cap.
- Self-repair: crashes during any write converge on restart; a damaged search index is rebuilt from the database; a damaged database opens in a recovery screen that can save the readable part.
- Installers for Windows (NSIS), macOS (Apple Silicon .dmg), and Linux (.deb, .rpm).

### Known limitations
- The data folder is not encrypted by OmniRecall; use OS disk encryption.
- Installers are not code-signed or notarized; Windows and macOS will warn on first launch.
- No Intel Mac build. No screenshot capture on Linux Wayland.
- English only for OCR and search quality. Speech is recognized in other languages, but search for non-English text is only lightly evaluated.
- Speech-to-text accuracy has not yet been measured with the real `base` model (`docs/measurements.md`).
- Secret detection is pattern-based and will miss some secrets; use exclusions for sensitive apps.

See `docs/privacy.md`, `docs/threat-model.md`, `docs/troubleshooting.md`, and `docs/support-matrix.md`.
