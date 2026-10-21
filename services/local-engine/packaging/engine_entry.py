"""PyInstaller entry point for the bundled engine sidecar."""

from omnirecall.api.server import main

if __name__ == "__main__":
    raise SystemExit(main())
