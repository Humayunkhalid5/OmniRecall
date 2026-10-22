# Supported formats

What OmniRecall can read, and the limits it applies. The app shows the same list in Library → Import, from the engine's `formats.list`. Every limit can be changed in Settings unless it says otherwise.

## Documents

| Format | Extensions | How it is read |
|---|---|---|
| Plain text | `.txt`, `.text`, `.log` | UTF-8 or UTF-16 (with a byte-order mark); anything else is read as Latin-1. Files with binary content are refused (`binary_content`). |
| Markdown | `.md`, `.markdown` | As text; the markup stays in the text so code and headings are searchable. |
| CSV | `.csv`, `.tsv` | Row by row, with the delimiter detected (comma, semicolon, tab, or vertical bar). |
| JSON | `.json` | Each value with its key path, such as `trip.ferry: 7:40`. Invalid JSON is refused (`malformed_file`). |
| HTML | `.html`, `.htm` | Visible text only; scripts and styles are dropped. Nothing is fetched. |
| PDF | `.pdf` | The text layer only. Scanned PDFs without a text layer give no text (`extraction_empty`); OCR of PDF pages is not offered. Password-protected PDFs are refused (`encrypted_file`). Up to 500 pages. |
| Word | `.docx` | Paragraphs and tables. The older `.doc` format is not supported. |

## Images (Tesseract OCR, English)

PNG, JPEG (`.jpg`, `.jpeg`), WebP, BMP, TIFF (first page), and GIF (first frame). Images up to 100 megapixels are read, which refuses decompression bombs; this limit is fixed. Text is recognized with Tesseract 5 and its English data. Other languages are not supported in this release.

## Audio (whisper.cpp `base`, after the speech model is installed)

| Format | Extensions |
|---|---|
| WAV | `.wav`, `.wave` |
| MP3 | `.mp3` |
| M4A (AAC or Apple Lossless) | `.m4a` |
| AAC | `.aac` |
| FLAC | `.flac` |
| Ogg Vorbis | `.ogg`, `.oga` |
| AIFF | `.aif`, `.aiff` |
| Core Audio | `.caf` |

Opus (in `.ogg`, `.opus`, or `.webm`) is not supported (`unsupported_codec`). Recordings up to 2 hours are read. Audio is transcribed on this device in 5-minute windows; each passage keeps its time in the recording.

OmniRecall does not record from the microphone. Audio comes only from files you import.

## Capture sources (off until you turn them on)

| Source | What is kept | Limit |
|---|---|---|
| Clipboard | Copied text. Copies that look like passwords, keys, or tokens are dropped by default (best effort, not a guarantee). | 100 KB per copy |
| Screenshots | Text recognized in each screen, every 30 seconds while the screen changes. Images are kept for 7 days, then only the text. Text-only mode keeps no images at all. | Media cap 5 GB in total |

## Limits

| Setting | Default |
|---|---|
| Largest file | 100 MB |
| PDF pages | 500 |
| Recording length | 2 hours |
| Clipboard copy | 100 KB |
| Search query | 1,000 characters |
| Queue | 1,000 items waiting |

A file over a limit is listed in the Library as failed with `limit_exceeded`, so you can see that it was not read.

## Languages

Search, OCR, and the embedding model are built for English. The speech model recognizes other languages too, and shows the detected language, but search quality for non-English text has only been checked on a small labeled set (docs/measurements.md).
