# Licenses and provenance

Verified in Phase 0 (2026-10-21) from package metadata and upstream model cards. Re-check on every dependency or model change (rules.md §3.8, OR-006).

## Models (never bundled in the repo; installed by explicit user action)

| Model | Use | License | Source / version | Checksum |
|---|---|---|---|---|
| all-MiniLM-L6-v2 (ONNX export) | Embeddings, 384-dim | Apache-2.0 | Upstream `sentence-transformers/all-MiniLM-L6-v2` @ `7dbbc90392e2f80f3d3c277d6e90027e55de9125`; download mirror `chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz` (83,178,821 bytes) | archive SHA-256 `913d7300…16ec3`; per-file SHA-256 in `omnirecall/model_manifests/all-minilm-l6-v2.json` |
| Whisper `base` (ggml, whisper.cpp) | Audio transcription | MIT (OpenAI Whisper weights and whisper.cpp) | `huggingface.co/ggerganov/whisper.cpp` `ggml-base.bin` | SHA-1 `465707469ff3a37a2b9b8d8f89f2f99de7299dac` (published in whisper.cpp `models/README.md`) |
| Tesseract `eng` traineddata | OCR | Apache-2.0 | OS package (`tesseract-ocr-eng`), Homebrew `tesseract`, or the UB Mannheim Windows build | from the OS package manager |

Redistribution: all three licenses permit bundling with attribution. The MVP still downloads the embedding and Whisper models on user action to keep the installer small (OR-018).

## Native runtimes

| Component | License | Notes |
|---|---|---|
| Tesseract 5 (binary) | Apache-2.0 | Called as a subprocess via `pytesseract`. Linux/macOS: system package; Windows installer must ship the UB Mannheim build (Apache-2.0) — Phase 6 packaging task. |
| ONNX Runtime 1.31.0 | MIT | Wheel bundles the CPU provider only. |
| whisper.cpp (via `pywhispercpp` 1.5.1) | MIT | No macOS x86_64 wheel is published; Intel Macs need a source build (tracked in `bugs.md` OR-020). |
| LanceDB 0.40.0 / Lance | Apache-2.0 | |
| Apache Arrow (`pyarrow` 26.0.0) | Apache-2.0 | |
| SQLite (CPython `sqlite3`) | Public domain | FTS5 availability checked at startup. |
| `omnirecall-audio-decode` (this repo, `services/audio-decoder`) | Project license | Rust helper that decodes audio (D-031). Its dependencies are listed below. |
| Tauri 2.12 and plugins | MIT OR Apache-2.0 | |
| WebKitGTK (Linux runtime) | LGPL-2.1 | Dynamically linked system library, not bundled. |

## Python packages (runtime)

numpy (BSD-3-Clause and bundled permissive), pyarrow (Apache-2.0), lancedb (Apache-2.0), onnxruntime (MIT), tokenizers (Apache-2.0), huggingface-hub (Apache-2.0, transitive; its download functions are never called and `HF_HUB_OFFLINE=1` is forced), pypdf (BSD-3-Clause), python-docx (MIT), lxml (BSD-3-Clause), Pillow (MIT-CMU), pytesseract (Apache-2.0), pydantic (MIT), pywhispercpp (MIT), requests (Apache-2.0), tqdm (MPL-2.0 AND MIT), platformdirs (MIT), packaging (Apache-2.0 OR BSD-2-Clause), typing-extensions (PSF-2.0). Exact versions are pinned in `services/local-engine/uv.lock`.

## Audio decoder dependencies (Rust, statically linked into `omnirecall-audio-decode`)

Checked with `cargo metadata` on 2026-10-22; exact versions are pinned in `services/audio-decoder/Cargo.lock`.

- symphonia 0.6.1 and its codec and format crates (aac, alac, adpcm, flac, mp3, pcm, vorbis, isomp4, ogg, riff, caf, mkv, metadata): MPL-2.0. MPL-2.0 is file-level copyleft. Linking it into a binary is allowed under any license, as long as the symphonia source (unmodified here) stays available, so the release notes must point to the upstream source.
- rubato 5.0.1, rustfft, realfft, audioadapter: MIT OR Apache-2.0. windowfunctions, extended, realfft: MIT.
- serde_json, serde, itoa, ryu (Apache-2.0 OR BSL-1.0), memchr (Unlicense OR MIT), bytemuck and visibility (Zlib OR MIT OR Apache-2.0), audio-codec-algorithms (0BSD OR Apache-2.0), and the num, log, smallvec, bitflags, lazy_static, regex-lite, transpose, strength_reduce, and primal-check crates: MIT OR Apache-2.0.

PyAV was rejected because its wheels bundle FFmpeg with GPL x264 and x265 (D-031).

## Frontend packages (runtime)

react / react-dom 19.3.1 (MIT), @tauri-apps/api and plugins (MIT OR Apache-2.0). Exact versions in `apps/desktop/package-lock.json`.

## Fonts used for test fixtures only

DejaVu fonts (Bitstream Vera / public-domain changes) render OCR fixtures in `scripts/make_image_fixtures.py`; they are not shipped.

## Project license

Not chosen yet. A product decision for the repository owner; no license file is added until then.
