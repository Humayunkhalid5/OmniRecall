"""Checks around installing, upgrading, and uninstalling OmniRecall (Phase 6).

The release workflow installs the package it just built, then runs:

    python scripts/install_check.py installed --app <app executable> --engine <engine>
    (reinstall the same package over itself, or install the newer one)
    python scripts/install_check.py upgraded --engine <engine>
    (uninstall)
    python scripts/install_check.py uninstalled --app <app executable> --engine <engine>

`installed` runs the packaged engine's smoke test, starts the app on a fresh
user profile until it has created its data folder and database, closes it, and
saves a marker item in that profile. `upgraded` checks that the marker is still
there and the installed engine opens the data. `uninstalled` checks that the
program is gone and the user's data is still there: uninstalling never deletes
it (docs/troubleshooting.md says how to remove it).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_engine import Engine

IDENTIFIER = "app.omnirecall.desktop"
MARKER = "Install check marker: the red kite nests by the reservoir"


def data_dir() -> Path:
    """Where Tauri's app_data_dir() puts the data for this identifier."""
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / IDENTIFIER
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / IDENTIFIER
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / IDENTIFIER


def db_path() -> Path:
    return data_dir() / "db" / "omnirecall.sqlite"


def fail(message: str) -> None:
    print(f"FAIL {message}")
    sys.exit(1)


def ok(message: str) -> None:
    print(f"ok   {message}")


def stop_tree(proc: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            check=False,
            capture_output=True,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=30)


def marker_count() -> int:
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        sql = "SELECT COUNT(*) FROM items WHERE source_label = 'install-check'"
        return int(conn.execute(sql).fetchone()[0])
    finally:
        conn.close()


def installed(app: Path, engine: Path) -> None:
    if data_dir().exists():
        fail(f"the profile is not fresh: {data_dir()} exists")
    smoke = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("smoke_engine.py")),
            str(engine),
            "--require-ocr",
        ],
        check=False,
    )
    if smoke.returncode:
        fail("packaged engine smoke test")
    ok("packaged engine smoke test")

    proc = subprocess.Popen([str(app)])
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                fail(f"the app exited with code {proc.returncode}")
            if db_path().is_file():
                break
            time.sleep(1)
        else:
            fail(f"the app did not create {db_path()} within 120 s")
        time.sleep(5)  # let the engine finish its start-up writes
    finally:
        stop_tree(proc)
    time.sleep(3)  # the engine exits when the app's end of its stdin closes
    ok(f"the app started its engine and created {db_path()}")

    engine_proc = Engine(engine, data_dir(), None)
    engine_proc.call("items.import_text", {"text": MARKER, "label": "install-check"})
    engine_proc.stop()
    if marker_count() != 1:
        fail("marker item was not saved")
    ok("marker item saved in the user's data")


def upgraded(engine: Path) -> None:
    if marker_count() != 1:
        fail("the marker item did not survive the upgrade")
    proc = Engine(engine, data_dir(), None)
    status = proc.call("status")
    proc.stop()
    if status["engine"] == "recovery":
        fail(f"the upgraded engine reported the data as damaged: {json.dumps(status)}")
    ok("data kept across the upgrade and opened by the installed engine")


def uninstalled(app: Path, engine: Path) -> None:
    for path in (app, engine):
        if path.exists():
            fail(f"{path} is still installed")
    ok("program files removed")
    if marker_count() != 1:
        fail("uninstalling removed the user's data")
    ok(f"user data kept at {data_dir()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("installed", "upgraded", "uninstalled"))
    parser.add_argument("--app", type=Path)
    parser.add_argument("--engine", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "installed":
        installed(args.app, args.engine)
    elif args.phase == "upgraded":
        upgraded(args.engine)
    else:
        uninstalled(args.app, args.engine)


if __name__ == "__main__":
    main()
