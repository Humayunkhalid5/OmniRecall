"""Build a static tesseract.exe for the Windows installer (OR-030).

Usage: python scripts/build_tesseract_windows.py <out_dir> [--vcpkg-root DIR]

Builds Tesseract with vcpkg at a pinned commit for the `x64-windows-static`
triplet, without libcurl and libarchive. Tesseract uses curl only to read
images from URLs and libarchive only for zipped models; OmniRecall passes a
local file and a plain model, so neither is needed. LibTIFF in vcpkg is built
without JBIG-KIT. Every remaining library is permissively licensed, and the
build fails if a port outside that reviewed list appears.

<out_dir> receives `tesseract.exe`, `tessdata/eng.traineddata` (tessdata_fast
4.1.0, checksum verified, the same file Debian and Homebrew ship), and
`licenses/<port>/copyright` for every library linked in. Network access is
needed here (vcpkg sources, the language data); never at run time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

VCPKG_REPO = "https://github.com/microsoft/vcpkg"
VCPKG_COMMIT = "67972e92edd181d433927b42d8ab4bfa52ac164a"  # tesseract 5.5.3
TRIPLET = "x64-windows-static"
TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata"
TESSDATA_SHA256 = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"

# Ports allowed in the static build, with the license reviewed for each.
REVIEWED_PORTS = {
    "tesseract": "Apache-2.0",
    "leptonica": "BSD-2-Clause",
    "giflib": "MIT",
    "libjpeg-turbo": "IJG AND BSD-3-Clause AND Zlib",
    "libpng": "libpng-2.0",
    "libwebp": "BSD-3-Clause",
    "openjpeg": "BSD-2-Clause",
    "tiff": "libtiff",
    "liblzma": "0BSD",
    "zlib": "Zlib",
}

# Edits to vcpkg's own tesseract port, each of which must apply exactly once.
PORTFILE_EDITS = (
    ("-DCMAKE_REQUIRE_FIND_PACKAGE_LibArchive=ON", "-DDISABLE_ARCHIVE=ON"),
    ("-DCMAKE_REQUIRE_FIND_PACKAGE_CURL=ON", "-DDISABLE_CURL=ON"),
    ("find_dependency(CURL)\n", ""),
    ("find_dependency(LibArchive)\n", ""),
)
DROPPED_DEPENDENCIES = {"curl", "libarchive"}


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def checkout_vcpkg(root: Path) -> Path:
    if not (root / ".git").is_dir():
        run(["git", "init", "-q", str(root)])
    run(
        [
            "git",
            "-C",
            str(root),
            "fetch",
            "-q",
            "--depth",
            "1",
            VCPKG_REPO,
            VCPKG_COMMIT,
        ]
    )
    run(["git", "-C", str(root), "checkout", "-q", "--force", "FETCH_HEAD"])
    exe = root / "vcpkg.exe"
    if not exe.is_file():
        run(["cmd", "/c", str(root / "bootstrap-vcpkg.bat"), "-disableMetrics"])
    return exe


def overlay_port(root: Path, overlay: Path) -> None:
    """Copy vcpkg's tesseract port and turn curl and libarchive off."""
    port = overlay / "tesseract"
    if port.exists():
        shutil.rmtree(port)
    shutil.copytree(root / "ports" / "tesseract", port)
    portfile = port / "portfile.cmake"
    text = portfile.read_text(encoding="utf-8")
    for old, new in PORTFILE_EDITS:
        if text.count(old) != 1:
            sys.exit(f"vcpkg tesseract port changed: {old.strip()!r} not found once")
        text = text.replace(old, new)
    portfile.write_text(text, encoding="utf-8")
    manifest_path = port / "vcpkg.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = {d if isinstance(d, str) else d["name"] for d in manifest["dependencies"]}
    if not DROPPED_DEPENDENCIES <= names:
        sys.exit("vcpkg tesseract port changed: curl or libarchive no longer listed")
    manifest["dependencies"] = [
        d
        for d in manifest["dependencies"]
        if (d if isinstance(d, str) else d["name"]) not in DROPPED_DEPENDENCIES
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def fetch_tessdata(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(TESSDATA_URL, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != TESSDATA_SHA256:
        sys.exit(f"eng.traineddata checksum mismatch: {digest}")
    (target / "eng.traineddata").write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--vcpkg-root", type=Path, default=Path("build") / "vcpkg")
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("this script builds the Windows Tesseract")

    root = args.vcpkg_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    vcpkg = checkout_vcpkg(root)
    overlay = root.parent / "vcpkg-overlay"
    overlay_port(root, overlay)
    run(
        [
            str(vcpkg),
            "install",
            f"tesseract:{TRIPLET}",
            f"--overlay-ports={overlay}",
            "--clean-after-build",
            "--disable-metrics",
        ],
        cwd=root,
    )

    installed = root / "installed" / TRIPLET
    ports = sorted(p.parent.name for p in (installed / "share").glob("*/copyright"))
    unreviewed = [p for p in ports if p not in REVIEWED_PORTS]
    if unreviewed:
        sys.exit(f"ports without a reviewed license in the build: {unreviewed}")

    out = args.out_dir.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(
        installed / "tools" / "tesseract" / "tesseract.exe", out / "tesseract.exe"
    )
    for name in ports:
        (out / "licenses" / name).mkdir(parents=True)
        shutil.copy2(
            installed / "share" / name / "copyright",
            out / "licenses" / name / "copyright",
        )
    fetch_tessdata(out / "tessdata")
    print("ports linked into tesseract.exe:", *ports, sep="\n  ", flush=True)


if __name__ == "__main__":
    main()
