# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the StrmAction desktop shell.

Build from the desktop/ directory:
    pyinstaller packaging/strmaction-desktop.spec --noconfirm --clean

The generated app name is StrmAction.  Bundled mpv is expected at
desktop/vendor/mpv/<platform>/ (see scripts/prepare_mpv.py).
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

spec_dir = Path(SPECPATH).resolve()
desktop = spec_dir.parent
src = desktop / "src"
assets = src / "strmaction_desktop" / "assets"

datas = [(str(assets), "strmaction_desktop/assets")]
vendor = desktop / "vendor" / "mpv"
if vendor.is_dir():
    datas.append((str(vendor), "vendor/mpv"))

hiddenimports = [
    module
    for module in collect_submodules("webview")
    if not module.endswith(".android")
]

a = Analysis(
    [str(desktop / "run_desktop.py")],
    pathex=[str(src)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = assets / ("icon.ico" if sys.platform == "win32" else "icon.icns")
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StrmAction",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StrmAction",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="StrmAction.app",
        icon=str(icon) if icon.is_file() else None,
        bundle_identifier="com.strmaction.desktop",
        info_plist={
            "CFBundleDisplayName": "StrmAction",
            "CFBundleName": "StrmAction",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
