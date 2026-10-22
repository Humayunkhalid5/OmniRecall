"""Assemble the engine sidecar folder that the installers ship (D-037).

Usage: python scripts/package_engine.py [--tesseract bundle|system] [--tesseract-dir DIR]

1. Builds the audio decoder (release) and the engine (PyInstaller one-dir).
2. Puts the decoder next to the engine executable, where the engine looks first.
3. On Windows and macOS copies Tesseract and its English data into
   `engine/tesseract/`; Linux packages depend on the distribution's Tesseract.
4. Copies the result to apps/desktop/src-tauri/resources/engine/, which
   tauri.release.conf.json maps into the installer, with docs/licenses.md.

Run it with the engine's environment: `uv run --project services/local-engine
--frozen python scripts/package_engine.py`. Nothing is downloaded here; the
build machine provides Tesseract (CI installs it from the OS package manager).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC = ROOT / "services" / "local-engine"
DECODER_SRC = ROOT / "services" / "audio-decoder"
RESOURCES = ROOT / "apps" / "desktop" / "src-tauri" / "resources"
EXE = ".exe" if sys.platform == "win32" else ""


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def replace_dir(path: Path) -> None:
    # Only ever the build's own output folders, named by constants above.
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def build_engine(work: Path) -> Path:
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(work / "dist"),
            "--workpath",
            str(work / "build"),
            "packaging/omnirecall-engine.spec",
        ],
        ENGINE_SRC,
    )
    return work / "dist" / "omnirecall-engine"


def build_decoder() -> Path:
    run(["cargo", "build", "--release", "--locked"], DECODER_SRC)
    return DECODER_SRC / "target" / "release" / f"omnirecall-audio-decode{EXE}"


def bundle_tesseract_windows(source: Path, target: Path) -> None:
    target.mkdir()
    # The UB Mannheim build: tesseract.exe and the DLLs beside it.
    for f in source.iterdir():
        if f.name.lower() == "tesseract.exe" or f.suffix.lower() == ".dll":
            shutil.copy2(f, target / f.name)
    (target / "tessdata").mkdir()
    shutil.copy2(source / "tessdata" / "eng.traineddata", target / "tessdata")


def bundle_tesseract_macos(source: Path, target: Path) -> None:
    """Copy the Homebrew binary and make its libraries relative to it."""
    target.mkdir()
    binary = target / "tesseract"
    shutil.copy2(source / "bin" / "tesseract", binary)
    binary.chmod(0o755)
    run(
        [
            "dylibbundler",
            "--overwrite-dir",
            "--bundle-deps",
            "--fix-file",
            str(binary),
            "--dest-dir",
            str(target / "lib"),
            "--install-path",
            "@executable_path/lib/",
        ],
        target,
    )
    # Rewriting load paths breaks the signatures; sign ad hoc so macOS runs them.
    # The release workflow signs again with the Developer ID when one is set.
    for f in [binary, *sorted((target / "lib").glob("*.dylib"))]:
        run(["codesign", "--force", "--sign", "-", str(f)], target)
    (target / "tessdata").mkdir()
    shutil.copy2(source / "share" / "tessdata" / "eng.traineddata", target / "tessdata")


def default_tesseract_dir() -> Path | None:
    if sys.platform == "win32":
        return (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR"
        )
    if sys.platform == "darwin":
        prefix = subprocess.run(
            ["brew", "--prefix", "tesseract"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(prefix)
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tesseract",
        choices=("bundle", "system"),
        default="system" if sys.platform.startswith("linux") else "bundle",
    )
    parser.add_argument("--tesseract-dir", type=Path)
    parser.add_argument("--work", type=Path, default=ROOT / "build" / "engine")
    args = parser.parse_args()

    decoder = build_decoder()
    engine = build_engine(args.work)
    shutil.copy2(decoder, engine / decoder.name)

    if args.tesseract == "bundle":
        source = args.tesseract_dir or default_tesseract_dir()
        if source is None or not source.is_dir():
            sys.exit(f"Tesseract not found at {source}; pass --tesseract-dir")
        target = engine / "tesseract"
        if sys.platform == "win32":
            bundle_tesseract_windows(source, target)
        elif sys.platform == "darwin":
            bundle_tesseract_macos(source, target)
        else:
            sys.exit("bundling Tesseract is only set up for Windows and macOS")

        # Every bundled file, for the license review (licenses.md).
        listing = sorted(
            p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()
        )
        (target / "FILES.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")

    out = RESOURCES / "engine"
    replace_dir(out)
    shutil.copytree(engine, out, dirs_exist_ok=True, symlinks=True)
    shutil.copy2(ROOT / "docs" / "licenses.md", RESOURCES / "licenses.md")
    print(f"engine folder ready: {out}")


if __name__ == "__main__":
    main()
