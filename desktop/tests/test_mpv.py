from __future__ import annotations

from strmaction_desktop.mpv import (
    find_mpv,
    headers_to_mpv,
    mpv_candidates,
    platform_key,
)


def test_platform_key():
    assert platform_key("win32", "AMD64") == "windows-x64"
    assert platform_key("win32", "ARM64") == "windows-arm64"
    assert platform_key("darwin", "arm64") == "macos-arm64"
    assert platform_key("linux", "x86_64") == "linux-x64"


def test_candidate_order_prefers_configured_and_bundled(tmp_path):
    bundled = tmp_path / "vendor" / "mpv" / "windows-x64" / "mpv.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"")
    candidates = mpv_candidates(
        r"C:\custom\mpv.exe",
        base_dir=tmp_path,
        system="win32",
        machine="AMD64",
        which=lambda _: r"C:\path\mpv.exe",
    )
    assert candidates[0] == r"C:\custom\mpv.exe"
    assert candidates[1] == str(bundled)
    assert candidates[-1] == r"C:\path\mpv.exe"


def test_find_mpv_bundled(tmp_path):
    bundled = tmp_path / "vendor" / "mpv" / "windows-x64" / "mpv.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"")
    bundled.chmod(0o755)
    found = find_mpv(
        "",
        base_dir=tmp_path,
        system="win32",
        machine="AMD64",
        which=lambda _: None,
    )
    assert found == str(bundled)


def test_find_mpv_configured_wins(tmp_path):
    configured = tmp_path / "my-mpv.exe"
    configured.write_bytes(b"")
    configured.chmod(0o755)
    found = find_mpv(
        str(configured),
        base_dir=tmp_path,
        system="win32",
        machine="AMD64",
        which=lambda _: None,
    )
    assert found == str(configured)


def test_headers_to_mpv():
    assert headers_to_mpv(
        {"User-Agent": "pan.baidu.com", "Referer": "https://pan.baidu.com/"}
    ) == [
        "User-Agent: pan.baidu.com",
        "Referer: https://pan.baidu.com/",
    ]
    assert headers_to_mpv({}) == []


def test_missing_mpv_returns_none(tmp_path):
    assert (
        find_mpv(
            "",
            base_dir=tmp_path,
            system="win32",
            machine="AMD64",
            which=lambda _: None,
        )
        is None
    )
