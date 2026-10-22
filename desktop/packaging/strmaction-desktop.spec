# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the StrmAction desktop shell.

Build from the desktop/ directory:
    pyinstaller packaging/strmaction-desktop.spec --noconfirm --clean

The generated app name is StrmAction.  Playback uses libmpv, so the shared
library from src/strmaction_desktop/vendor/libmpv/<platform-arch>/ ships with
the package; mpv_loader resolves it at runtime and the app falls back to Qt
Multimedia when it is absent.
"""

import sys
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
desktop = spec_dir.parent
src = desktop / "src"
package = src / "strmaction_desktop"
assets = package / "assets"
vendor = package / "vendor"

datas = [(str(assets), "strmaction_desktop/assets")]
# Keep the vendor layout intact: mpv_loader resolves the library through a
# package-relative path, so it must not be flattened into the bundle root.
if vendor.is_dir():
    datas.append((str(vendor), "strmaction_desktop/vendor"))

hiddenimports = [
    "mpv",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
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
