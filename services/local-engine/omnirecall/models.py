"""Local model manifests, verification, and user-initiated installation.

Model weights are never downloaded implicitly (PRD §7 Processing). The user
starts a download (size and license shown first) or picks a local archive.
Every file is checked against the pinned manifest checksum before use.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from omnirecall import logs
from omnirecall.errors import EngineError, NotFoundError
from omnirecall.ids import utc_now

MARKER = ".verified.json"
Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class Manifest:
    id: str
    kind: str
    display_name: str
    version: str
    license: str
    license_url: str
    upstream: str
    download: dict[str, Any]
    files: dict[str, str]
    raw: dict[str, Any]

    @property
    def size_bytes(self) -> int:
        return int(self.download.get("size_bytes") or self.download.get("size_bytes_approx") or 0)


def load_manifests() -> dict[str, Manifest]:
    found: dict[str, Manifest] = {}
    for entry in (resources.files("omnirecall") / "model_manifests").iterdir():
        if not entry.name.endswith(".json"):
            continue
        data = json.loads(entry.read_text(encoding="utf-8"))
        found[data["id"]] = Manifest(
            id=data["id"],
            kind=data["kind"],
            display_name=data["display_name"],
            version=data["version"],
            license=data["license"],
            license_url=data["license_url"],
            upstream=data["upstream"],
            download=data["download"],
            files=data.get("files", {}),
            raw=data,
        )
    return found


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


class ModelManager:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self.manifests = load_manifests()
        self._lock = threading.Lock()
        self._installing: dict[str, dict[str, Any]] = {}
        self._cancel: dict[str, threading.Event] = {}

    def model_dir(self, model_id: str) -> Path:
        return self.models_dir / model_id

    def manifest(self, model_id: str) -> Manifest:
        manifest = self.manifests.get(model_id)
        if manifest is None:
            raise NotFoundError("Model")
        return manifest

    def is_installed(self, model_id: str) -> bool:
        manifest = self.manifest(model_id)
        directory = self.model_dir(model_id)
        marker = directory / MARKER
        if not marker.is_file():
            return False
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if recorded.get("version") != manifest.version:
            return False
        names = list(manifest.files) or [manifest.download.get("filename", "")]
        return all((directory / name).is_file() for name in names if name)

    def describe(self) -> list[dict[str, Any]]:
        with self._lock:
            installing = {k: dict(v) for k, v in self._installing.items()}
        return [
            {
                "id": m.id,
                "kind": m.kind,
                "name": m.display_name,
                "version": m.version,
                "license": m.license,
                "license_url": m.license_url,
                "upstream": m.upstream,
                "download_url": m.download.get("url"),
                "size_bytes": m.size_bytes,
                "installed": self.is_installed(m.id),
                "install": installing.get(m.id),
            }
            for m in self.manifests.values()
        ]

    # ---- installation ------------------------------------------------------

    def _set_progress(self, model_id: str, **state: Any) -> None:
        with self._lock:
            self._installing.setdefault(model_id, {}).update(state)

    def cancel(self, model_id: str) -> None:
        event = self._cancel.get(model_id)
        if event:
            event.set()

    def download(self, model_id: str, progress: Progress | None = None) -> None:
        """Download, verify, and install. Runs only on explicit user request."""
        manifest = self.manifest(model_id)
        url = manifest.download["url"]
        if not url.startswith("https://"):
            raise EngineError("insecure_url", "Model downloads must use HTTPS")
        cancel = self._cancel.setdefault(model_id, threading.Event())
        cancel.clear()
        self._set_progress(model_id, state="downloading", received=0, total=manifest.size_bytes)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.models_dir, prefix=".download-") as tmp:
            target = Path(tmp) / "download"
            try:
                # The scheme is checked to be https above.
                request = urllib.request.Request(  # noqa: S310
                    url, headers={"User-Agent": "OmniRecall-model-setup"}
                )
                with (
                    urllib.request.urlopen(request, timeout=60) as response,  # noqa: S310
                    open(target, "wb") as out,
                ):
                    total = int(response.headers.get("Content-Length") or manifest.size_bytes or 0)
                    received = 0
                    while block := response.read(1 << 20):
                        if cancel.is_set():
                            raise EngineError("cancelled", "Model download cancelled")
                        out.write(block)
                        received += len(block)
                        self._set_progress(model_id, received=received, total=total)
                        if progress:
                            progress(received, total)
            except EngineError:
                self._set_progress(model_id, state="cancelled")
                raise
            except OSError as exc:
                self._set_progress(model_id, state="failed", error_code="download_failed")
                raise EngineError(
                    "download_failed", "The model download failed; check your connection"
                ) from exc
            self._install_archive(manifest, target)

    def install_from_file(self, model_id: str, path: Path) -> None:
        """Install from a file the user selected (offline setup)."""
        manifest = self.manifest(model_id)
        if not path.is_file():
            raise NotFoundError("File")
        self._set_progress(model_id, state="verifying")
        self._install_archive(manifest, path)

    def _install_archive(self, manifest: Manifest, source: Path) -> None:
        self._set_progress(manifest.id, state="verifying")
        expected_sha256 = manifest.download.get("sha256")
        expected_sha1 = manifest.download.get("sha1")
        if expected_sha256 and _digest(source, "sha256") != expected_sha256:
            self._set_progress(manifest.id, state="failed", error_code="checksum_mismatch")
            raise EngineError(
                "checksum_mismatch", "The model file did not match its published checksum"
            )
        if expected_sha1 and not expected_sha256 and _digest(source, "sha1") != expected_sha1:
            self._set_progress(manifest.id, state="failed", error_code="checksum_mismatch")
            raise EngineError(
                "checksum_mismatch", "The model file did not match its published checksum"
            )
        final = self.model_dir(manifest.id)
        staging = final.with_name(final.name + ".staging")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            if manifest.download["format"] == "tar.gz":
                self._extract_tar(source, staging, manifest)
            else:
                shutil.copyfile(source, staging / manifest.download["filename"])
            for name, digest in manifest.files.items():
                file_path = staging / name
                if not file_path.is_file() or _digest(file_path, "sha256") != digest:
                    raise EngineError(
                        "checksum_mismatch", "A model file did not match its checksum"
                    )
            (staging / MARKER).write_text(
                json.dumps({"version": manifest.version, "installed_at": utc_now()}),
                encoding="utf-8",
            )
            shutil.rmtree(final, ignore_errors=True)
            staging.rename(final)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            self._set_progress(manifest.id, state="failed", error_code="install_failed")
            raise
        with self._lock:
            self._installing.pop(manifest.id, None)
        logs.info("model_installed", model=manifest.id, version=manifest.version)

    @staticmethod
    def _extract_tar(source: Path, destination: Path, manifest: Manifest) -> None:
        prefix = manifest.download.get("strip_prefix", "")
        wanted = set(manifest.files) | {
            "config.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.txt",
        }
        with tarfile.open(source, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = member.name[len(prefix) :] if member.name.startswith(prefix) else member.name
                # Only flat, expected file names: no traversal, no links.
                if "/" in name or "\\" in name or name.startswith(".") or name not in wanted:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                with extracted, open(destination / name, "wb") as out:
                    shutil.copyfileobj(extracted, out)
