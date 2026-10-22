"""Phase 0 OCR spike: RapidOCR (ONNX) vs Tesseract 5 on the fixture images.

Reports character error rate (CER), wall time per image, and peak RSS delta.
Usage: python scripts/spike_ocr.py <fixtures_dir>
"""

from __future__ import annotations

import resource
import sys
import time
from pathlib import Path


def cer(reference: str, hypothesis: str) -> float:
    ref = " ".join(reference.split())
    hyp = " ".join(hypothesis.split())
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(1, len(ref))


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run_rapidocr(images: list[Path]) -> list[tuple[str, float]]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    out = []
    for path in images:
        start = time.perf_counter()
        result, _ = engine(str(path))
        text = "\n".join(item[1] for item in (result or []))
        out.append((text, time.perf_counter() - start))
    return out


def run_tesseract(images: list[Path]) -> list[tuple[str, float]]:
    import pytesseract
    from PIL import Image

    out = []
    for path in images:
        start = time.perf_counter()
        text = pytesseract.image_to_string(Image.open(path), lang="eng")
        out.append((text, time.perf_counter() - start))
    return out


def main() -> None:
    fixtures = Path(sys.argv[1])
    images = sorted(fixtures.glob("*.png"))
    for name, runner in (("tesseract", run_tesseract), ("rapidocr", run_rapidocr)):
        before = rss_mb()
        results = runner(images)
        total_cer = 0.0
        for path, (text, seconds) in zip(images, results, strict=True):
            truth = path.with_suffix(".txt").read_text(encoding="utf-8")
            score = cer(truth, text)
            total_cer += score
            print(f"{name:10s} {path.stem:22s} CER={score:.3f} time={seconds * 1000:.0f}ms")
        print(
            f"{name:10s} MEAN CER={total_cer / len(images):.3f} peak_rss_after={rss_mb():.0f}MB (before {before:.0f}MB)"
        )


if __name__ == "__main__":
    main()
