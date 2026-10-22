"""Locate and preload the libmpv shared library.

The player does not require libmpv to be present: when nothing can be found
the desktop shell falls back to Qt Multimedia.  This module only answers the
question "can libmpv be loaded, and where is it", never imports mpv itself
except for the final availability probe.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from pathlib import Path

# Kept alive on purpose: os.add_dll_directory() objects are invalidated when
# they are garbage collected, which would silently break later DL loads.
_dll_directories: list = []

_LIB_NAMES: dict[str, tuple[str, ...]] = {
    "win32": ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll"),
    "darwin": ("libmpv.2.dylib", "libmpv.dylib"),
}
_DEFAULT_NAMES = ("libmpv.so.2", "libmpv.so.1", "libmpv.so")


def library_names() -> tuple[str, ...]:
    return _LIB_NAMES.get(sys.platform, _DEFAULT_NAMES)


def _platform_dir() -> str:
    """e.g. ``windows-x64`` / ``macos-arm64`` / ``linux-x64``."""
    system = {
        "win32": "windows",
        "darwin": "macos",
    }.get(sys.platform, "linux")
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine or "unknown"
    return f"{system}-{arch}"


def _frozen_dir() -> Path | None:
    """Directory next to the packaged executable (PyInstaller onefile/dir)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return executable.parent
    return None


def _package_vendor_dirs() -> list[Path]:
    """``<package>/vendor/libmpv/<platform-arch>/``, from source or a bundle.

    Inside a PyInstaller bundle the module lives in a PYZ archive: ``__file__``
    may be missing, and when present it points at a path that does not exist on
    disk.  The directory layout is still real (the vendor tree is collected as
    data), so derive it from ``sys._MEIPASS`` as well and never let a missing
    ``__file__`` abort the search.
    """
    bases: list[Path] = []
    module_file = globals().get("__file__")
    if module_file:
        bases.append(Path(module_file).resolve().parent.parent)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass) / "strmaction_desktop")
    return [base / "vendor" / "libmpv" / _platform_dir() for base in bases]


def candidate_dirs() -> list[Path]:
    """Directories searched for a usable libmpv, most specific first."""
    dirs: list[Path] = []

    env_dir = os.environ.get("STRMACTION_LIBMPV_DIR")
    if env_dir:
        dirs.append(Path(env_dir))

    dirs.extend(_package_vendor_dirs())

    # Per-user data directory, the place an installer can drop the library
    # without touching the application bundle (also survives updates).
    try:
        from ..config import app_data_dir

        dirs.append(app_data_dir() / "libmpv")
    except Exception:  # pragma: no cover - config import is always safe
        pass

    frozen = _frozen_dir()
    if frozen is not None:
        dirs.append(frozen / "libmpv")
        dirs.append(frozen)

    return dirs


def find_library() -> Path | None:
    """Return the first existing libmpv file, or None.

    ``STRMACTION_LIBMPV`` may point at the file itself, which always wins.
    """
    override = os.environ.get("STRMACTION_LIBMPV")
    if override:
        target = Path(override)
        if target.is_file():
            return target

    for directory in candidate_dirs():
        if not directory.is_dir():
            continue
        for name in library_names():
            target = directory / name
            if target.is_file():
                return target
        # A macOS XCFramework keeps the binary at Mpv.framework/libmpv.
        framework = directory / "Mpv.framework" / "libmpv"
        if framework.is_file():
            return framework
    return None


def prime_environment() -> Path | None:
    """Make libmpv discoverable by ctypes; returns the file used, if any.

    On Windows Python 3.8+ the DLL search path no longer follows %PATH%, so
    the directory must be registered explicitly with add_dll_directory().
    """
    found = find_library()
    if found is None:
        return None

    directory = str(found.parent.resolve())
    if sys.platform == "win32":
        if hasattr(os, "add_dll_directory"):
            try:
                _dll_directories.append(os.add_dll_directory(directory))
            except (OSError, ValueError):
                pass
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
    elif sys.platform == "darwin":
        # dyld does not use PATH; add_dll_directory is a no-op there, so point
        # ctypes at the file directly through the explicit path below.
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
            directory
            + os.pathsep
            + os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        )
    else:
        os.environ["LD_LIBRARY_PATH"] = (
            directory + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
        )
    return found


_availability: bool | None = None


def _disabled() -> bool:
    """Escape hatch: STRMACTION_DISABLE_MPV forces the Qt fallback.

    Tests and troubleshooting do not want a real mpv instance (audio devices,
    GPU, decode threads), so they can opt out without moving the library.
    """
    value = os.environ.get("STRMACTION_DISABLE_MPV", "").strip().lower()
    return value in ("1", "true", "yes", "on")


def is_available() -> bool:
    """True when ``import mpv`` succeeds after priming the search path.

    The result is cached: a failed probe costs a full DL search and the answer
    cannot change while the process lives.
    """
    global _availability
    if _availability is not None:
        return _availability

    if _disabled():
        _availability = False
        return False

    if prime_environment() is None and not _has_system_library():
        _availability = False
        return False
    try:
        import mpv  # noqa: F401  (importing is the probe)
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        _availability = False
    else:
        _availability = True
    return _availability


def _has_system_library() -> bool:
    """Fall back to the platform loader for a system-installed libmpv."""
    for name in library_names():
        try:
            ctypes.CDLL(name)
        except OSError:
            continue
        return True
    return False


def describe() -> str:
    """Human readable summary for logs and the settings dialog."""
    found = prime_environment()
    if found is None:
        return "libmpv：未找到"
    return f"libmpv：{found}"


def reset_cache() -> None:
    """Forget the cached availability result (tests only)."""
    global _availability
    _availability = None
