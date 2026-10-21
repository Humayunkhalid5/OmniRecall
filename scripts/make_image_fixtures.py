"""Render deterministic OCR fixtures (images + ground-truth text).

Usage: python scripts/make_image_fixtures.py <out_dir>
Uses DejaVu fonts (Bitstream Vera license) shipped with most Linux distros.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

FIXTURES = {
    "terminal_error": {
        "bg": (24, 24, 27),
        "fg": (229, 231, 235),
        "font": "DejaVuSansMono.ttf",
        "size": 22,
        "lines": [
            "$ cargo build --release",
            "error[E0382]: borrow of moved value: `config`",
            "  --> src/main.rs:42:17",
            "help: consider cloning the value",
        ],
    },
    "slide_photosynthesis": {
        "bg": (255, 255, 255),
        "fg": (17, 24, 39),
        "font": "DejaVuSans.ttf",
        "size": 34,
        "lines": [
            "Photosynthesis",
            "Light reactions occur in the thylakoid",
            "The Calvin cycle fixes carbon dioxide",
            "Chlorophyll absorbs red and blue light",
        ],
    },
    "chat_message": {
        "bg": (243, 244, 246),
        "fg": (31, 41, 55),
        "font": "DejaVuSans.ttf",
        "size": 18,
        "lines": [
            "Priya: The quarterly review moved to Thursday 3pm",
            "Sam: Can you share the budget spreadsheet before then?",
            "Priya: Sure, I will send the Q3 forecast tonight",
        ],
    },
    "small_ui_text": {
        "bg": (255, 255, 255),
        "fg": (55, 65, 81),
        "font": "DejaVuSans.ttf",
        "size": 13,
        "lines": [
            "Settings  >  Network  >  Proxy configuration",
            "Use system proxy settings for all connections",
            "Last updated 12 minutes ago",
        ],
    },
}


def render(name: str, spec: dict, out_dir: Path) -> None:
    font = ImageFont.truetype(str(FONT_DIR / spec["font"]), spec["size"])
    line_h = int(spec["size"] * 1.6)
    width = 60 + max(int(font.getlength(line)) for line in spec["lines"])
    height = 60 + line_h * len(spec["lines"])
    image = Image.new("RGB", (width, height), spec["bg"])
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(spec["lines"]):
        draw.text((30, 30 + index * line_h), line, font=font, fill=spec["fg"])
    image.save(out_dir / f"{name}.png")
    (out_dir / f"{name}.txt").write_text("\n".join(spec["lines"]) + "\n", encoding="utf-8")


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in FIXTURES.items():
        render(name, spec, out_dir)


if __name__ == "__main__":
    main()
