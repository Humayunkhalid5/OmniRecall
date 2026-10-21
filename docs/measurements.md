# Measurements

Every number here was measured, with the command that produced it. Nothing here is a guarantee (rules.md §1.6).

## Reference machines

| ID | Machine | Notes |
|---|---|---|
| REF-CI-LINUX | Cloud container: 4 vCPU Intel Xeon (KVM), 15 GB RAM, Ubuntu 24.04, Python 3.12.3 | Development reference. Not representative of a laptop; repeat on real hardware before release (Phase 6). |

## Phase 0 (2026-10-21, REF-CI-LINUX)

### Engine sidecar
| Metric | Result | Command |
|---|---|---|
| Frozen engine size (PyInstaller one-dir, without models) | 462 MB unpacked, 180 MB gzip | `pyinstaller … packaging/engine_entry.py`; `du -sh`; `tar czf` |
| Largest parts | lancedb 178 MB, pyarrow 160 MB, onnxruntime 30 MB, numpy 41 MB | `du -sh _internal/*` |
| Cold start to first `health` response (frozen) | 143–158 ms (3 runs) | spawn → `engine.ready` → `health` |
| Idle RSS, engine from source | 24 MB | `ps` while supervised by the Tauri shell |
| Idle RSS, Tauri shell (debug build, WebKitGTK) | 174 MB | `ps` under Xvfb |

RapidOCR was dropped from the bundle after the OCR spike, removing about 245 MB (OpenCV + Shapely).

### OCR (4 rendered fixtures in `services/local-engine/tests/fixtures/images`)
| Engine | Mean CER | Time per image | Peak memory |
|---|---|---|---|
| Tesseract 5.3.4 (`eng`, via pytesseract) | 0.006 | 97–167 ms | 36 MB (child process) |
| RapidOCR 1.4.4 (ONNX) | 0.068 | 429–1175 ms | +458 MB in-process |

RapidOCR's errors were mostly dropped spaces between words (`ThequarterlyreviewmovedtoThursday`), which breaks keyword search. Command: `python scripts/spike_ocr.py services/local-engine/tests/fixtures/images` (RapidOCR needs `uv run --with rapidocr-onnxruntime==1.4.4`).

### Embeddings (all-MiniLM-L6-v2 ONNX, 2 intra-op threads)
| Metric | Result |
|---|---|
| Model load + first embed | 205 ms |
| RSS with model loaded | 218 MB after load, 295 MB peak after a 32-chunk batch |
| Batch of 32 × 500-char chunks | ~300 ms |
| Single query embed | 3.6 ms |
| Tokens in a 500-char English chunk | 97 (limit 256) |
| Sanity: related pairs cosine | 0.63–0.67; unrelated pairs −0.04 to −0.03; norms 1.0; deterministic |

Command: `python scripts/spike_embeddings.py <models>/all-minilm-l6-v2`.

### Transcription
`pywhispercpp` 1.5.1 loads its native whisper.cpp build (AVX2, OpenMP). The `ggml-base` model could not be downloaded from this build environment (huggingface.co is blocked by its network policy), so accuracy and speed are **not yet measured**. Tracked for Phase 5.
