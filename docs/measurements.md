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

## Phase 2 (2026-10-21, REF-CI-LINUX)

### Relevance baseline (evaluation corpus: 44 documents, 52 labeled queries, 6 non-English)
| Mode | recall@10 | MRR | Notes |
|---|---|---|---|
| Hybrid (FTS5 + vector, RRF k = 60, stopwords removed from the keyword query) | 0.982 | 0.958 | English 0.980 / 0.953; non-English 1.000 / 1.000; exact-identifier queries 1.000 / 1.000 |
| Vector only | 0.963 | 0.962 | Exact-identifier queries 0.667: misses `E0382` entirely |
| Keyword only | 0.901 | 0.881 | Paraphrased queries 0.895; four queries with no relevant result |

Hybrid before the stopword filter scored lower, because words such as "to" flooded the keyword ranks (D-020).

Relevance label calibration on the same run: results labeled **strong** were relevant 100% of the time (n = 44); **possible** (moderate) 50% (n = 8). Query latency on this small index: median 7.4 ms, p95 8.8 ms (re-run at the end of the phase; the first run measured about 12 ms median).

Command: `uv run --project services/local-engine python scripts/eval_relevance.py <data_dir_with_models> --mode hybrid` (also `--mode vector`, `--mode keyword`).

### Search latency at 10,000 chunks
| Metric | Result |
|---|---|
| Index build (10,000 synthetic 500-char chunks, real MiniLM model, until every item is `indexed`) | 141 s |
| Search median / p95 (hybrid, 200 queries) | 20.3 ms / 23.3 ms |
| SQLite database (with FTS5) | 24.9 MB |
| LanceDB vectors (after compaction) | 17 MB |
| Peak engine RSS during bulk indexing | 743 MB |

The first build took far longer (about 4.5 items/s) because every item wrote its own LanceDB version. Batching vector writes across items in a dedicated worker and compacting every 64 writes fixed it (D-019).

Command: `uv run --project services/local-engine python scripts/bench_search.py <data_dir_with_models> --chunks 10000`.

### Model setup
Downloading all-MiniLM-L6-v2 through `ModelManager` (HTTPS, archive SHA-256 and per-file SHA-256 verified, staged then renamed): 2.4 s for 83 MB on this machine's network.
