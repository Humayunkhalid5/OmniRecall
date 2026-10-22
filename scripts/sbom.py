"""Software bill of materials for a release (CycloneDX 1.5 JSON).

Usage: python scripts/sbom.py <output.json> [--tesseract-version 5.5.0]
Run with the engine's environment (uv run --project services/local-engine),
so Python package licenses can be read from the installed metadata.

Components, from the lock files:
- Python packages the engine needs at run time (uv.lock, walking the engine's
  dependencies, without development tools), with licenses from their metadata.
- Rust crates of the app shell and the audio decoder (Cargo.lock, every locked
  crate for any platform), with licenses from `cargo metadata` when cargo is
  available.
- npm packages bundled into the window (package-lock.json, without dev ones).
- CPython itself and, when given, the bundled Tesseract.
Models are not in the installers (licenses.md), so they are not listed.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import tomllib
import uuid
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "services/local-engine"
CARGO_PROJECTS = {
    "app-shell": ROOT / "apps/desktop/src-tauri",
    "audio-decoder": ROOT / "services/audio-decoder",
}
NPM_LOCK = ROOT / "apps/desktop/package-lock.json"


def python_components() -> list[dict[str, Any]]:
    lock = tomllib.loads((ENGINE / "uv.lock").read_text(encoding="utf-8"))
    packages = {p["name"]: p for p in lock["package"]}
    root = packages["omnirecall-engine"]
    seen: set[str] = set()

    def needed(deps: list[dict[str, Any]]) -> list[str]:
        # Edges only for browser builds of Python never reach a desktop install.
        return [
            d["name"] for d in deps if d.get("marker") != "sys_platform == 'emscripten'"
        ]

    pending = needed(root.get("dependencies", []))
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(needed(packages[name].get("dependencies", [])))
    components = []
    for name in sorted(seen):
        version = packages[name]["version"]
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "properties": [{"name": "omnirecall:part", "value": "engine"}],
        }
        license_ = python_license(name)
        if license_:
            component["licenses"] = [license_]
        components.append(component)
    return components


def python_license(name: str) -> dict[str, Any] | None:
    try:
        meta = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return None
    expression = meta.get("License-Expression")
    if expression:
        return {"expression": expression}
    classifiers = [
        c.split(" :: ")[-1]
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    text = classifiers[0] if classifiers else (meta.get("License") or "").strip()
    if text and len(text) < 100:
        return {"license": {"name": text}}
    return None


def cargo_licenses(project: Path) -> dict[tuple[str, str], str]:
    if not shutil.which("cargo"):
        return {}
    try:
        done = subprocess.run(
            ["cargo", "metadata", "--format-version", "1", "--locked"],
            cwd=project,
            capture_output=True,
            check=True,
            timeout=600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}
    data = json.loads(done.stdout)
    return {(p["name"], p["version"]): p.get("license") or "" for p in data["packages"]}


def rust_components() -> list[dict[str, Any]]:
    components: dict[tuple[str, str], dict[str, Any]] = {}
    for part, project in CARGO_PROJECTS.items():
        lock = tomllib.loads((project / "Cargo.lock").read_text(encoding="utf-8"))
        licenses = cargo_licenses(project)
        for package in lock["package"]:
            key = (package["name"], package["version"])
            if "source" not in package:  # this repository's own crates
                continue
            component = components.setdefault(
                key,
                {
                    "type": "library",
                    "name": key[0],
                    "version": key[1],
                    "purl": f"pkg:cargo/{key[0]}@{key[1]}",
                    "properties": [],
                },
            )
            component["properties"].append({"name": "omnirecall:part", "value": part})
            if licenses.get(key):
                component["licenses"] = [{"expression": licenses[key]}]
    return [components[k] for k in sorted(components)]


def npm_components() -> list[dict[str, Any]]:
    lock = json.loads(NPM_LOCK.read_text(encoding="utf-8"))
    components = []
    for path, package in sorted(lock["packages"].items()):
        if not path or package.get("dev") or package.get("link"):
            continue
        name = path.split("node_modules/")[-1]
        version = package["version"]
        scope, _, base = name.rpartition("/")
        purl_name = f"{scope.replace('@', '%40')}/{base}" if scope else base
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:npm/{purl_name}@{version}",
            "properties": [{"name": "omnirecall:part", "value": "window"}],
        }
        if package.get("license"):
            component["licenses"] = [{"expression": package["license"]}]
        components.append(component)
    return components


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--tesseract-version")
    args = parser.parse_args()
    version = tomllib.loads((ENGINE / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    components = python_components() + rust_components() + npm_components()
    components.append(
        {
            "type": "application",
            "name": "CPython",
            "version": platform.python_version(),
            "licenses": [{"expression": "PSF-2.0"}],
            "properties": [{"name": "omnirecall:part", "value": "engine"}],
        }
    )
    if args.tesseract_version:
        components.append(
            {
                "type": "application",
                "name": "tesseract",
                "version": args.tesseract_version,
                "licenses": [{"expression": "Apache-2.0"}],
                "properties": [
                    {
                        "name": "omnirecall:part",
                        "value": "engine (Windows and macOS installers)",
                    }
                ],
            }
        )
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {
                "type": "application",
                "name": "OmniRecall",
                "version": version,
            },
        },
        "components": components,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
    parts: dict[str, int] = {}
    for c in components:
        for p in c.get("properties", []):
            parts[p["value"]] = parts.get(p["value"], 0) + 1
    unlicensed = sum(1 for c in components if "licenses" not in c)
    print(
        json.dumps(
            {"components": len(components), "by_part": parts, "no_license": unlicensed}
        )
    )


if __name__ == "__main__":
    main()
