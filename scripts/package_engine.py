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
build machine provides Tesseract (on Windows `scripts/build_tesseract_windows.py`
builds it into build/tesseract-windows; on macOS it comes from Homebrew).
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
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


LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE")


def copy_license_files(source: Path, destination: Path) -> int:
    """Copy the license and notice files at the top of `source` (not recursive)."""
    copied = 0
    for f in sorted(source.iterdir()) if source.is_dir() else []:
        if f.is_file() and f.name.upper().startswith(LICENSE_NAMES):
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, destination / f.name)
            copied += 1
    return copied


def pe_imports(path: Path) -> list[str]:
    """DLL names a Windows executable or DLL imports, including delay-loaded ones."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
    optional = pe + 24
    directories = optional + (
        112 if struct.unpack_from("<H", data, optional)[0] == 0x20B else 96
    )
    table = optional + optional_size
    spans = [
        struct.unpack_from("<II4xI", data, table + 40 * i + 8)  # size, rva, raw offset
        for i in range(sections)
    ]

    def offset(rva: int) -> int:
        for size, start, raw in spans:
            if start <= rva < start + max(size, 1):
                return raw + rva - start
        raise ValueError("RVA outside every section")

    def name_at(rva: int) -> str:
        at = offset(rva)
        return data[at : data.index(b"\0", at)].decode("ascii")

    names = []
    for index, entry_size, name_field in ((1, 20, 12), (13, 32, 4)):
        rva = struct.unpack_from("<I", data, directories + 8 * index)[0]
        if not rva:
            continue
        at = offset(rva)
        while any(data[at : at + entry_size]):
            names.append(name_at(struct.unpack_from("<I", data, at + name_field)[0]))
            at += entry_size
    return names


VENDORED_LICENSES = ENGINE_SRC / "packaging" / "third_party_licenses"


def bundle_tesseract_windows(source: Path, target: Path) -> None:
    """Copy the static build from scripts/build_tesseract_windows.py (OR-030)."""
    exe = source / "tesseract.exe"
    # Static: every import must be a part of Windows itself, so no library
    # ships beside the executable except the ones linked in and listed in licenses/.
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    foreign = sorted(n for n in pe_imports(exe) if not (system / n).is_file())
    if foreign:
        sys.exit(f"tesseract.exe loads DLLs that are not part of Windows: {foreign}")
    if not (source / "licenses").is_dir():
        sys.exit(
            f"no licenses folder in {source}; build it with build_tesseract_windows.py"
        )
    target.mkdir()
    shutil.copy2(exe, target / exe.name)
    shutil.copytree(source / "licenses", target / "licenses")
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
    # Each bundled library's license, from the Homebrew keg it came from.
    bundled = {f.name for f in (target / "lib").glob("*.dylib")}
    formulas = subprocess.run(
        ["brew", "deps", "--installed", "tesseract"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for formula in ["tesseract", *formulas]:
        keg = Path(
            subprocess.run(
                ["brew", "--prefix", formula],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        ).resolve()
        used = formula == "tesseract" or any(
            (keg / "lib" / n).exists() for n in bundled
        )
        if used and not copy_license_files(keg, target / "licenses" / formula):
            vendored = VENDORED_LICENSES / formula
            if not vendored.is_dir():
                sys.exit(
                    f"no license file for bundled {formula} (third_party_licenses)"
                )
            shutil.copytree(vendored, target / "licenses" / formula)


def default_tesseract_dir() -> Path | None:
    if sys.platform == "win32":
        return ROOT / "build" / "tesseract-windows"
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
        print("bundled Tesseract files:", *listing, sep="\n  ", flush=True)

    out = RESOURCES / "engine"
    replace_dir(out)
    shutil.copytree(engine, out, dirs_exist_ok=True, symlinks=True)
    shutil.copy2(ROOT / "docs" / "licenses.md", RESOURCES / "licenses.md")
    print(f"engine folder ready: {out}")


if __name__ == "__main__":
    main()
