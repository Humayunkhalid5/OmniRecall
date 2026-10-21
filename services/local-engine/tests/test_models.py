import io
import os
import tarfile
from pathlib import Path

import pytest

from omnirecall.errors import EngineError
from omnirecall.models import ModelManager

ARCHIVE = os.environ.get("OMNIRECALL_TEST_MINILM_ARCHIVE")


def test_manifests_are_pinned(tmp_path):
    manager = ModelManager(tmp_path)
    minilm = manager.manifest("all-minilm-l6-v2")
    assert minilm.license == "Apache-2.0" and len(minilm.download["sha256"]) == 64
    assert minilm.download["url"].startswith("https://")
    assert all(len(d) == 64 for d in minilm.files.values())
    whisper = manager.manifest("whisper-base")
    assert len(whisper.download["sha1"]) == 40
    listed = {m["id"]: m for m in manager.describe()}
    assert listed["all-minilm-l6-v2"]["installed"] is False
    assert listed["all-minilm-l6-v2"]["size_bytes"] > 50_000_000


def test_checksum_mismatch_is_refused(tmp_path):
    manager = ModelManager(tmp_path / "models")
    bogus = tmp_path / "onnx.tar.gz"
    bogus.write_bytes(b"not the model")
    with pytest.raises(EngineError) as info:
        manager.install_from_file("all-minilm-l6-v2", bogus)
    assert info.value.code == "checksum_mismatch"
    assert not manager.is_installed("all-minilm-l6-v2")
    assert not (tmp_path / "models" / "all-minilm-l6-v2").exists()


def test_tar_extraction_ignores_traversal_and_unexpected_files(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in [
            ("onnx/../../escape.txt", b"x"),
            ("onnx/model.onnx", b"m"),
            ("onnx/run.sh", b"rm"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    manager = ModelManager(tmp_path / "models")
    out = tmp_path / "out"
    out.mkdir()
    manager._extract_tar(archive, out, manager.manifest("all-minilm-l6-v2"))
    assert sorted(p.name for p in out.iterdir()) == ["model.onnx"]
    assert not (tmp_path / "escape.txt").exists()


def test_download_requires_https(tmp_path, monkeypatch):
    manager = ModelManager(tmp_path)
    manifest = manager.manifest("all-minilm-l6-v2")
    monkeypatch.setitem(manifest.download, "url", "http://example.invalid/model.tgz")
    with pytest.raises(EngineError) as info:
        manager.download("all-minilm-l6-v2")
    assert info.value.code == "insecure_url"


@pytest.mark.skipif(not ARCHIVE, reason="set OMNIRECALL_TEST_MINILM_ARCHIVE to the model archive")
def test_real_archive_installs(tmp_path):
    manager = ModelManager(tmp_path / "models")
    manager.install_from_file("all-minilm-l6-v2", Path(ARCHIVE))
    assert manager.is_installed("all-minilm-l6-v2")
