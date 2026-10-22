# PyInstaller spec for the engine sidecar (one-dir build, D-037).
# Build: uv run --frozen pyinstaller --noconfirm --clean packaging/omnirecall-engine.spec
# Output: dist/omnirecall-engine/ (the executable and its _internal folder).
# scripts/package_engine.py adds the audio decoder and, where bundled, Tesseract.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = collect_data_files("omnirecall")  # SQL migrations and model manifests
datas += collect_data_files("lancedb")
binaries = collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("pywhispercpp")
hiddenimports = collect_submodules("omnirecall") + ["_pywhispercpp"]

a = Analysis(
    ["engine_entry.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Not used at runtime; keeps the bundle smaller.
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="omnirecall-engine",
    console=True,  # stdio is the RPC channel; the shell hides the window on Windows
    strip=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="omnirecall-engine")
