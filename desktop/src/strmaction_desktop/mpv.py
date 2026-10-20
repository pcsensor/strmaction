"""Find and control a local mpv process over its JSON IPC interface.

The desktop client launches mpv as a separate process (the web UI stays in the
WebView).  Request headers are installed through IPC instead of command-line
arguments so cookies/tokens do not leak through the process list.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Sequence

from .config import DEFAULT_CACHE_LIMIT_MB, normalize_cache_limit
from .security import PlaybackPayload


class MpvError(RuntimeError):
    """mpv is missing, failed to start, or failed to play."""


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    if system.startswith("win"):
        return f"windows-{arch}"
    if system == "darwin":
        return f"macos-{arch}"
    return f"linux-{arch}"


def bundle_root() -> Path:
    """Root used to locate bundled assets, both in source and PyInstaller."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def mpv_candidates(
    configured: str = "",
    base_dir: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    system_value = (system or sys.platform).lower()
    key = platform_key(system_value, machine)
    root = base_dir or bundle_root()
    exe = "mpv.exe" if system_value.startswith("win") else "mpv"
    candidates: list[str] = []

    if configured:
        candidates.append(configured.strip())

    bundled = root / "vendor" / "mpv" / key
    candidates.append(str(bundled / exe))
    if system_value == "darwin":
        candidates.append(str(bundled / "mpv.app" / "Contents" / "MacOS" / "mpv"))
        candidates.append("/Applications/mpv.app/Contents/MacOS/mpv")
        candidates.append("/opt/homebrew/bin/mpv")
        candidates.append("/usr/local/bin/mpv")
    elif system_value.startswith("win"):
        candidates.append(r"C:\Program Files\mpv\mpv.exe")
        candidates.append(r"C:\Program Files (x86)\mpv\mpv.exe")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(str(Path(local) / "Programs" / "mpv" / "mpv.exe"))
    else:
        candidates.append("/usr/bin/mpv")
        candidates.append("/usr/local/bin/mpv")

    on_path = which("mpv")
    if on_path:
        candidates.append(on_path)

    # Preserve order while removing duplicates/empty values.
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        value = (candidate or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return path.suffix.lower() == ".exe"
    return os.access(path, os.X_OK)


def find_mpv(
    configured: str = "",
    base_dir: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    for candidate in mpv_candidates(configured, base_dir, system, machine, which):
        path = Path(candidate).expanduser()
        if _is_executable(path):
            return str(path)
    return None


def headers_to_mpv(headers: dict[str, str]) -> list[str]:
    """Convert a header map to mpv's http-header-fields list."""
    return [f"{key}: {value}" for key, value in headers.items() if key and value]


def cache_args(limit_mb: int) -> list[str]:
    """Build mpv demuxer-cache arguments for the configured MB budget.

    ``0`` disables the demuxer cache entirely.  Other values cap both the
    forward and back cache so a low-bitrate episode cannot fill the whole
    buffer with one download.
    """
    try:
        limit = int(limit_mb)
    except (TypeError, ValueError):
        limit = DEFAULT_CACHE_LIMIT_MB
    limit = normalize_cache_limit(limit)
    if limit <= 0:
        return ["--cache=no", "--cache-on-disk=no"]
    back = max(8, limit // 4)
    return [
        "--cache=yes",
        f"--demuxer-max-bytes={limit}MiB",
        f"--demuxer-max-back-bytes={back}MiB",
        "--cache-on-disk=no",
    ]


class MpvController:
    """One mpv process controlled via JSON IPC."""

    def __init__(
        self,
        executable: str,
        *,
        cache_limit_mb: int = DEFAULT_CACHE_LIMIT_MB,
        on_position: Callable[[float], None] | None = None,
        on_duration: Callable[[float | None], None] | None = None,
        on_paused: Callable[[bool], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_exited: Callable[[], None] | None = None,
        logger=None,
    ):
        self.executable = executable
        self.cache_limit_mb = cache_limit_mb
        self._on_position = on_position
        self._on_duration = on_duration
        self._on_paused = on_paused
        self._on_finished = on_finished
        self._on_error = on_error
        self._on_exited = on_exited
        self._logger = logger
        self._process: subprocess.Popen | None = None
        self._conn = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._ipc_path = ""
        self._temp_dir: str | None = None
        self._subtitles: Sequence = ()
        self._finished_sent = False
        self.duration: float | None = None
        self.position: float = 0.0

    # -- lifecycle -----------------------------------------------------
    def play(self, payload: PlaybackPayload) -> None:
        if self._process is not None:
            raise MpvError("播放器已在运行")
        self._subtitles = payload.subtitles
        self._start_process(payload)
        try:
            self._connect()
            self._reader = threading.Thread(
                target=self._read_loop, name="mpv-ipc", daemon=True
            )
            self._reader.start()
            self._configure(payload)
        except Exception:
            self.stop()
            raise

    def _start_process(self, payload: PlaybackPayload) -> None:
        ipc_path = self._make_ipc_path()
        args = [
            self.executable,
            "--no-terminal",
            "--force-window=yes",
            "--idle=yes",
            "--keep-open=no",
            "--save-position-on-quit=no",
            "--title=StrmAction",
            f"--input-ipc-server={ipc_path}",
        ]
        if payload.resume_ms > 3000:
            args.append(f"--start={payload.resume_ms / 1000:.1f}")
        args.extend(cache_args(self.cache_limit_mb))
        creationflags = 0x08000000 if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._cleanup_ipc()
            raise MpvError(f"无法启动 mpv：{exc}") from exc
        self._ipc_path = ipc_path
        if self._logger:
            self._logger.info("mpv 已启动 pid=%s", self._process.pid)

    def _make_ipc_path(self) -> str:
        if os.name == "nt":
            return rf"\\.\pipe\strmaction-{uuid.uuid4().hex}"
        self._temp_dir = tempfile.mkdtemp(prefix="strmaction-mpv-")
        os.chmod(self._temp_dir, 0o700)
        return str(Path(self._temp_dir) / "mpv.sock")

    def _connect(self) -> None:
        deadline = time.time() + 12
        last_error: OSError | None = None
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise MpvError("mpv 启动后立即退出，请检查 mpv 路径/参数")
            try:
                if os.name == "nt":
                    self._conn = open(self._ipc_path, "r+b", buffering=0)
                else:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    sock.connect(self._ipc_path)
                    sock.settimeout(None)
                    self._conn = sock
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        raise MpvError(f"无法连接 mpv IPC：{last_error}")

    def _configure(self, payload: PlaybackPayload) -> None:
        headers = headers_to_mpv(payload.headers)
        if headers:
            self._command(["set_property", "http-header-fields", headers])
        for prop_id, name in (
            (1, "time-pos"),
            (2, "duration"),
            (3, "pause"),
            (4, "eof-reached"),
        ):
            self._command(["observe_property", prop_id, name])
        if payload.resume_ms > 3000:
            self._command(
                ["set_property", "start", f"{payload.resume_ms / 1000:.1f}"]
            )
        self._command(["loadfile", payload.play_url])

    # -- IPC -----------------------------------------------------------
    def _command(self, command: list) -> None:
        if self._conn is None:
            return
        data = (json.dumps({"command": command}, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        with self._send_lock:
            conn = self._conn
            if conn is None:
                return
            try:
                if isinstance(conn, socket.socket):
                    conn.sendall(data)
                else:
                    conn.write(data)
                    conn.flush()
            except OSError:
                self._safe_error("mpv IPC 写入失败")

    def _read_loop(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            conn = self._conn
            if conn is None:
                break
            try:
                chunk = conn.recv(4096) if isinstance(conn, socket.socket) else conn.read(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    event = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                self._handle_event(event)
        if not self._stop.is_set():
            self._safe_exited()

    def _handle_event(self, event: dict) -> None:
        if event.get("event") != "property-change":
            if event.get("event") == "file-loaded":
                self._add_subtitles()
            elif event.get("event") == "end-file" and event.get("reason") == "eof":
                self._mark_finished()
            return
        name = event.get("name")
        data = event.get("data")
        try:
            if name == "time-pos" and data is not None:
                self.position = float(data)
                if self._on_position:
                    self._on_position(self.position)
            elif name == "duration" and data is not None:
                self.duration = float(data)
                if self._on_duration:
                    self._on_duration(self.duration)
            elif name == "pause":
                if self._on_paused:
                    self._on_paused(bool(data))
            elif name == "eof-reached" and data:
                self._mark_finished()
        except (TypeError, ValueError):
            return

    def _mark_finished(self) -> None:
        if self._finished_sent:
            return
        self._finished_sent = True
        self._safe_finished()
        # The window is launched with --idle=yes so it can accept loadfile;
        # close it now that playback has ended.
        self._command(["quit"])

    def _add_subtitles(self) -> None:
        for index, subtitle in enumerate(self._subtitles):
            self._command(
                ["sub-add", subtitle.url, "select" if index == 0 else "auto"]
            )

    # -- callbacks -----------------------------------------------------
    def _safe_finished(self) -> None:
        if self._on_finished:
            try:
                self._on_finished()
            except Exception:
                pass

    def _safe_error(self, message: str) -> None:
        if self._logger:
            self._logger.warning("mpv: %s", message)
        if self._on_error:
            try:
                self._on_error(message)
            except Exception:
                pass

    def _safe_exited(self) -> None:
        if self._on_exited:
            try:
                self._on_exited()
            except Exception:
                pass

    # -- teardown ------------------------------------------------------
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        self._stop.set()
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                data = json.dumps({"command": ["quit"]}).encode() + b"\n"
                if isinstance(conn, socket.socket):
                    conn.sendall(data)
                else:
                    conn.write(data)
                    conn.flush()
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        process = self._process
        self._process = None
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        if self._reader is not None:
            self._reader.join(timeout=2)
            self._reader = None
        self._cleanup_ipc()

    def _cleanup_ipc(self) -> None:
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
        self._ipc_path = ""
