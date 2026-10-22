# Measurements

Every number here was measured, with the command that produced it. Nothing here is a guarantee (rules.md §1.6).

## Reference machines

| ID | Machine | Notes |
|---|---|---|
| REF-CI-LINUX | Cloud container: 4 vCPU Intel Xeon (KVM), 15 GB RAM, Ubuntu 24.04, Python 3.12.3 | Development reference. Not representative of a laptop. |
| GH-UBUNTU | GitHub-hosted runner `ubuntu-24.04` / `ubuntu-22.04` (4 vCPU, 16 GB) | Real-model and Linux installer jobs. Shared hardware; timings vary by about 10% between runs. |
| GH-MACOS | GitHub-hosted runner `macos-14` (Apple M1, 3 cores, 7 GB) | macOS installer job. |
| GH-WINDOWS | GitHub-hosted runner `windows-2022` (4 vCPU, 16 GB) | Windows installer job. |

No laptop or desktop owned by a user has been measured yet. CPU and battery use during capture on a real laptop are still unmeasured (OR-001).

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
`pywhispercpp` 1.5.1 loads its native whisper.cpp build (AVX2, OpenMP). The `ggml-base` model could not be downloaded from this build environment (huggingface.co is blocked by its network policy), so accuracy and speed are **not yet measured**. Tracked for Phase 5 (still not measured at the end of Phase 5; see below).

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

## Phase 4 (2026-10-22, REF-CI-LINUX)

### OCR (Tesseract 5.3.4, `eng`)
| Input | Median of 3 |
|---|---|
| 1280x800 screenshot of the app and a terminal (upscaled to 1600 px wide before OCR) | 0.45-0.47 s |
| Same screen resized to 2560x1600 | 0.45 s |

Fixture accuracy (`tests/test_ocr.py`): character error rate below 5% on all four fixture images.

### Screenshot live run (Xvfb 1280x800, 5 s interval)
From intake to `indexed`, a new frame took 0.46-1.53 s over 6 frames (OCR plus embedding; the first included loading the model). The engine log for the whole session recorded 68 frame outcomes:
- 11 captured;
- 46 dropped in the shell as unchanged, before anything was written;
- 5 skipped while idle;
- 5 refused because an app exclusion existed and the app was unknown;
- 1 dropped after OCR as sensitive.

CPU and battery impact on a real laptop are not measured here (Phase 6).

## Phase 5 (2026-10-22, REF-CI-LINUX)

### Audio decoder (`omnirecall-audio-decode` 0.1.0, release build, 2.9 MB)
| Input | Decode and resample to 16 kHz mono | Peak memory (helper) |
|---|---|---|
| 1-hour MP3, 44.1 kHz stereo, 128 kb/s | 4.0 s | 10 MB |
| 1-hour M4A (AAC), 48 kHz mono, 96 kb/s | 3.7 s | 11 MB |
| 8-10 s spoken fixtures (M4A, WAV, MP3, Ogg Vorbis, FLAC) | 4-11 ms each | |

The one-hour files were synthetic tones made with `ffmpeg -f lavfi -i sine=…`. Timing came from a Python `subprocess.run` of `decode <file> 7200`, with the peak taken from `getrusage(RUSAGE_CHILDREN)`.

The resampler test checks each output length and pitch: a 440 Hz tone at 8, 22.05, 44.1, and 48 kHz gives 870-890 zero crossings per second after resampling.

### Transcription
**Not measured in Phase 5.** The `ggml-base.bin` model could not be downloaded from this environment. Measured in Phase 6 on CI instead; see below.

## Phase 6 (2026-10-22)

### Speech-to-text with the real whisper.cpp `base` model (GH-UBUNTU)
Downloaded through the engine's own verified `ModelManager` in the `Real models` CI job, then run by `scripts/eval_transcription.py`. WER after normalization (`tests/wer.py`: lower case, no punctuation, number words as digits).

| Set | Recordings | Audio | Corpus WER | English detected | Speed |
|---|---|---|---|---|---|
| LibriSpeech sample (`hf-internal-testing/librispeech_asr_dummy`, validation-clean, real read speech, CC BY 4.0; parquet SHA-256 `4e69a06f…27c603`) | 73 | 481 s | **9.8%** (mean per recording 12.1%, worst 75% on a 4-word line with a made-up name) | 73 of 73 | 2.6-3.3 s per recording |
| Spoken fixtures (espeak-ng synthetic voices: M4A, MP3, Ogg Vorbis, FLAC, WAV) | 5 | 46 s | 12.0% (0%, 6.9%, 32%, 15.8%, 0%) | 5 of 5 | 2.7-3.2 s each |

- Whisper processes audio in 30-second windows, so each recording costs at least about 2.6 s on this runner however short it is. On the longest LibriSpeech recording (29.4 s) that was 3.3 s, a real-time factor of 0.11, which suggests about 7 minutes for an hour of speech. A one-hour recording has not been timed with the real model.
- Most errors are proper names (Quilter, Ruggedo, Calico) and rare words. The worst fixture, `recipe.ogg`, lost "of flour" and "of sugar" in a robotic voice.
- Published figures for Whisper `base` on LibriSpeech test-clean are about 5% WER with OpenAI's fuller text normalizer and beam search; this sample, the simpler normalizer, and greedy decoding are not directly comparable.
- Findability, the gate (D-038): each of the four distinct recordings, transcribed and indexed with the real models, was the top result for a paraphrased question (`test_real_models_make_every_recording_findable`). The network audit passed in the same job with both real models installed.

### Search latency at 100,000 chunks (REF-CI-LINUX, real MiniLM model)
| Metric | Result |
|---|---|
| Search median / p95 / max (hybrid, 156 queries, end to end through `Engine.search`) | **126.8 ms / 157.6 ms / 203.1 ms** (target: p95 under 1 s, design §11) |
| Index build (100,000 synthetic chunks of about 480 characters, until every item is `indexed`) | 6507 s, about 15 chunks/s. Most of that was OR-031, fixed in the improvement pass: 1372 s, about 73 chunks/s (below) |
| SQLite database (with FTS5) | 227 MB |
| LanceDB vectors (after compaction) | 162 MB |
| Peak engine RSS during bulk indexing | 1358 MB |
| Start-up on this index: database check / engine set-up / reconciliation | 559 ms / 7 ms / 1.7 s |

Latency grew about 6× from 10,000 chunks (23 ms p95) for 10× the data; the vector search is a flat scan (no ANN index yet), so it grows roughly linearly. Peak memory during bulk indexing is high because the indexer batches vector writes; a user importing a large folder will see it.

Command: `uv run --project services/local-engine python scripts/bench_search.py <data_dir_with_models> --chunks 100000`.

### Relevance re-run (GH-UBUNTU, real MiniLM model)
Unchanged from Phase 2 on the same corpus and queries:

| Mode | recall@10 | MRR | Query latency median / p95 |
|---|---|---|---|
| Hybrid | 0.982 | 0.958 | 8.4 ms / 10.7 ms |
| Vector only | 0.963 | 0.962 | 7.9 ms / 8.9 ms |
| Keyword only | 0.901 | 0.881 | 0.7 ms / 1.4 ms |

Label calibration (hybrid): **strong** relevant 100% of the time (n = 44), **possible** 50% (n = 8).

### Installers (release workflow, unsigned)
| Package | Runner | Size | Tesseract | Engine ready | Install, reinstall, uninstall checks |
|---|---|---|---|---|---|
| .deb | REF-CI-LINUX (built locally) and GH-UBUNTU 22.04 | 258.9 MiB (271,447,680 bytes) | system package (dependency) | about 1.15 s | all passed; data kept after removal |
| .dmg | GH-MACOS | 202.7 MiB (212,570,519 bytes) | bundled 5.5.3, used after Homebrew's was uninstalled | 999 ms | all passed; data kept |
| NSIS setup.exe | GH-WINDOWS | 121.0 MiB (126,854,661 bytes); 143.7 MiB with the Phase 6 UB Mannheim Tesseract | bundled static 5.5.3 (D-042); no other Tesseract on the runner | 2351 ms and 2791 ms in two runs of the same job (1642 ms in Phase 6) | all passed; data kept in `%APPDATA%` |

"Engine ready" is from spawning the installed engine to its first `health` answer, on an empty data folder, as measured by `smoke_engine.py`. The installers do not contain models (83 MB search model, 148 MB speech model, downloaded on request).

### Engine memory, packaged (REF-CI-LINUX, frozen one-dir engine from the .deb)
| State | Resident memory |
|---|---|
| Idle after start, no model loaded | 159 MB |
| Search model loaded, after indexing and searching | 382 MB |

Phase 0's 24 MB was the engine skeleton run from source, before the storage, search, and extraction libraries (LanceDB, PyArrow, ONNX Runtime, whisper.cpp) were added. 159 MB is the idle figure for the engine as shipped. The search model is unloaded after 5 minutes idle; the speech model likewise.

## Improvement pass (2026-10-22)

### Memory on a large library (REF-CI-LINUX, a copy of the 100,000-chunk data folder, real MiniLM model)
Resident memory after each stage of starting the engine and adding 200 new items:

| Stage | Before | After |
|---|---|---|
| Engine set up | 138 MB | 138 MB |
| Start-up reconciliation done (peak) | 645 MB (676 MB) | 260 MB (333 MB) |
| 200 items indexed (peak) | 921 MB (938 MB) | 555 MB (562 MB) |

The consistency check read the whole vector table, vectors included, to collect chunk IDs, and did so three times at start-up; it now reads only the ID column, and the damage check reads the table in batches of 4,096 rows.

Embedding (ONNX Runtime 1.31, 4 threads, 60 batches of 32 texts of 5 to 200 words): turning off the memory pattern planner lowered peak memory from 614-616 MB to 420-421 MB, with times of 26.0-27.0 s against 26.9-27.1 s (two runs each). Turning off the CPU memory arena instead saved more (405 MB) but was 44% slower, so it was not used.

### Adding items to a large library (REF-CI-LINUX)
500 new, unique items added to the 100,000-chunk library, timed until every one was indexed (`scripts/bench_add.py`): 72.2 items/s with scalar indexes on the vector table, 74.2 items/s without them, and 77.8 items/s with the memory changes above (peak 596 MB). At 10,000 chunks the rate is about 70 items/s. The scalar indexes were dropped because they made no end-to-end difference.

### Building a large library from scratch (REF-CI-LINUX, `bench_search.py`)
The whole-library build was slow for a different reason (OR-031). The queue capacity counted extraction jobs only, and extraction is much faster than embedding, so up to 30,000 items piled up waiting for their vectors; marking each item indexed then scanned that whole pile. The rate fell from 55 items/s to about 8 and recovered only as the pile drained.

| Build | Before | After (D-043) |
|---|---|---|
| 30,000 chunks | 636 s, 47 items/s | not re-run |
| 40,000 chunks | stopped after 7 minutes: 30,000 items waiting for vectors, draining at about 25 items/s | 568 s, 70 items/s |
| 100,000 chunks | 6650 s, 15 items/s | **1372 s, 73 items/s** |
| Search p95 at 100,000 (hybrid, 156 queries) | 141.7-198.3 ms over three builds | 197.3 ms |
| Peak engine RSS during the 100,000 build | 1223-1263 MB | 1294 MB |

Peak memory during a bulk build is still about 1.3 GB; it is not the backlog, which is now held under 1,000 items, and remains open (OR-001).

### Speech-to-text, greedy decoding against beam search (GH-UBUNTU, whisper.cpp `base`)
| Set | Decoding | Corpus WER | Mean / worst per recording | Mean real-time factor |
|---|---|---|---|---|
| LibriSpeech sample (73 recordings, 481 s) | greedy (default) | 9.8% | 12.1% / 75% | 0.566 |
| LibriSpeech sample | beam 5 | 9.4% | 12.3% / 100% | 0.610 |
| Spoken fixtures (5, 46 s) | greedy (default) | 12.0% | 10.9% / 32% | 0.324 |
| Spoken fixtures | beam 5 | 9.1% | 8.5% / 20% | 0.367 |

Greedy decoding stays the default (D-041). The mean real-time factor is high because every recording costs at least one 30-second window, and most of these are short.
