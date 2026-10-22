"""Local OCR behind a replaceable adapter (design.md §3, D-012).

Images are untrusted input: Pillow's decompression-bomb limit is enforced,
only the first frame of multi-frame files is read, and Tesseract runs as a
local subprocess with a timeout. Recognised text is never logged.
"""

from __future__ import annotations

import os
import shutil
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from omnirecall.errors import EngineError, LimitExceededError

# Largest image accepted, in pixels: an 8K display is 33 MP; 100 MP leaves room
# for multi-display captures and scans while refusing decompression bombs.
MAX_IMAGE_PIXELS = 100_000_000
# Text in UI screenshots is often small; Tesseract does best near 30 px x-height,
# so narrow images are upscaled before recognition.
MIN_OCR_WIDTH = 1600
OCR_TIMEOUT_S = 120
TESSERACT_ENV = "OMNIRECALL_TESSERACT_CMD"
# Pillow warns above this many pixels and refuses twice as many.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@dataclass
class OcrResult:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def version(self) -> str | None: ...

    def recognize(self, image: Image.Image) -> OcrResult: ...


class OcrUnavailableError(EngineError):
    def __init__(self) -> None:
        super().__init__("ocr_unavailable", "Text recognition (Tesseract) is not available")


def open_image(path: Path) -> Image.Image:
    """Open and fully decode the first frame of an image, with size limits."""
    with warnings.catch_warnings():
        # Pillow warns between MAX_IMAGE_PIXELS and twice that; treat it as an error.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(path) as source:
                width, height = source.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise LimitExceededError("image_pixels", MAX_IMAGE_PIXELS)
                source.seek(0)
                image = ImageOps.exif_transpose(source)
                image.load()
                return image
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise LimitExceededError("image_pixels", MAX_IMAGE_PIXELS) from None
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise EngineError("malformed_file", "The image could not be read") from exc


def prepare(image: Image.Image) -> Image.Image:
    """Grayscale, flatten transparency onto white, and upscale small images."""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba)
    gray = image.convert("L")
    if gray.width < MIN_OCR_WIDTH:
        factor = min(3.0, MIN_OCR_WIDTH / max(gray.width, 1))
        if factor > 1.2:
            size = (round(gray.width * factor), round(gray.height * factor))
            gray = gray.resize(size, Image.Resampling.LANCZOS)
    return gray


class TesseractOcr:
    name = "tesseract"

    def __init__(self, command: str | None = None, lang: str = "eng") -> None:
        self.lang = lang
        self._command = command
        self._version: str | None = None
        self._lock = threading.Lock()

    def _resolve(self) -> str | None:
        configured = self._command or os.environ.get(TESSERACT_ENV)
        if configured:
            return configured if Path(configured).is_file() else None
        return shutil.which("tesseract")

    def available(self) -> bool:
        return self.version() is not None

    def version(self) -> str | None:
        with self._lock:
            if self._version is None:
                command = self._resolve()
                if command is None:
                    return None
                import pytesseract

                pytesseract.pytesseract.tesseract_cmd = command
                try:
                    self._version = str(pytesseract.get_tesseract_version())
                except (pytesseract.TesseractNotFoundError, OSError, RuntimeError):
                    return None
            return self._version

    def recognize(self, image: Image.Image) -> OcrResult:
        version = self.version()
        if version is None:
            raise OcrUnavailableError()
        import pytesseract

        prepared = prepare(image)
        try:
            text = pytesseract.image_to_string(prepared, lang=self.lang, timeout=OCR_TIMEOUT_S)
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            raise EngineError("ocr_timeout", "Text recognition took too long") from exc
        except pytesseract.TesseractError as exc:
            raise EngineError("ocr_failed", "Text recognition failed") from exc
        return OcrResult(
            text=text,
            metadata={
                "ocr_engine": self.name,
                "ocr_version": version,
                "ocr_lang": self.lang,
                "width": image.width,
                "height": image.height,
            },
        )


def ocr_file(engine: OcrEngine, path: Path) -> OcrResult:
    if not engine.available():
        raise OcrUnavailableError()
    return engine.recognize(open_image(path))
