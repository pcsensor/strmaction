"""桌面 mpv spawn + JSON IPC 进度回传（§12.3）。

仅在 StrmAction 与 mpv 同机时启用；不可用时自动降级为复制链接。
"""

from __future__ import annotations

import json
import os
import select
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from sqlmodel import Session

from ..config_store import SettingsService
from ..models import Item, MediaFile, PlayProgress, utcnow
from .base import PlayContext, mask_url


def write_progress(
    engine,
    item_id: int,
    position_ms: int,
    duration_ms: int | None,
    *,
    finished: bool = False,
) -> None:
    position_ms = max(0, int(position_ms or 0))
    if duration_ms and duration_ms > 0:
        position_ms = min(position_ms, int(duration_ms))
        if position_ms / duration_ms > 0.9:
            finished = True
    if finished:
        position_ms = 0
    with Session(engine) as session:
        from sqlmodel import select

        row = session.exec(
            select(PlayProgress).where(PlayProgress.item_id == item_id)
        ).first()
        if row is None:
            row = PlayProgress(
                item_id=item_id,
                position_ms=position_ms,
                duration_ms=duration_ms,
                finished=finished,
                updated_at=utcnow(),
            )
        else:
            if (
                not finished
                and row.position_ms - position_ms > 5000
                and not row.finished
            ):
                return
            row.position_ms = position_ms
            row.duration_ms = duration_ms or row.duration_ms
            row.finished = finished
            row.updated_at = utcnow()
        session.add(row)
        session.commit()


class MpvMonitor(threading.Thread):
    def __init__(self, engine, item_id: int, pipe_path: str, process: subprocess.Popen):
        super().__init__(daemon=True)
        self.engine = engine
        self.item_id = item_id
        self.pipe_path = pipe_path
        self.process = process
        self.position = 0.0
        self.duration: float | None = None
        self._last_write = 0.0

    def _connect(self):
        if os.name == "nt":
            for _ in range(50):
                try:
                    return open(self.pipe_path, "r+b", buffering=0)  # type: ignore[return-value]
                except OSError:
                    time.sleep(0.2)
            return None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.connect(self.pipe_path)
                return sock
            except OSError:
                time.sleep(0.2)
        return None

    def _send(self, connection, payload: dict) -> None:
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        if isinstance(connection, socket.socket):
            connection.sendall(raw)
        else:
            connection.write(raw)
            connection.flush()

    def run(self) -> None:  # pragma: no cover - 依赖本机 mpv
        connection = self._connect()
        if connection is None:
            self.process.wait()
            return
        try:
            self._send(connection, {"command": ["observe_property", 1, "time-pos"]})
            self._send(connection, {"command": ["observe_property", 2, "duration"]})
            buffer = b""
            while True:
                if isinstance(connection, socket.socket):
                    ready, _, _ = select.select([connection], [], [], 1.0)
                    if not ready:
                        if self.process.poll() is not None:
                            break
                        self._flush()
                        continue
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
                else:
                    chunk = connection.read(4096)
                    if not chunk:
                        break
                    buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    name = event.get("name")
                    data = event.get("data")
                    if name == "time-pos" and data is not None:
                        self.position = float(data)
                        self._flush()
                    elif name == "duration" and data is not None:
                        self.duration = float(data)
                    elif event.get("event") == "end-file":
                        break
        except Exception:
            pass
        finally:
            try:
                self._flush(force=True)
            finally:
                try:
                    connection.close()
                except OSError:
                    pass
                self.process.wait()

    def _flush(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < 5:
            return
        duration_ms = int(self.duration * 1000) if self.duration else None
        position_ms = int(self.position * 1000)
        finished = False
        if self.process.poll() is not None:
            if duration_ms and position_ms / max(duration_ms, 1) > 0.9:
                finished = True
            elif duration_ms is None and position_ms == 0:
                finished = False
        try:
            write_progress(self.engine, self.item_id, position_ms, duration_ms, finished=finished)
            self._last_write = now
        except Exception:
            pass


class MpvIpcAdapter:
    name = "mpv_ipc"

    def __init__(self, settings: SettingsService, engine):
        self.settings = settings
        self.engine = engine

    def _mpv_path(self) -> str | None:
        configured = (self.settings.player().get("mpv_path") or "mpv").strip()
        if os.sep in configured or "/" in configured:
            return configured if Path(configured).exists() else None
        return shutil.which(configured)

    def available(self, context: PlayContext) -> bool:
        if context.is_android:
            return False
        if self.settings.player().get("mode") in {"copy", "builtin", "external_mpv"}:
            return False
        return self._mpv_path() is not None

    async def build(
        self,
        *,
        item: Item,
        media: MediaFile,
        title: str,
        resume_ms: int,
        context: PlayContext,
    ) -> dict:
        mpv = self._mpv_path()
        if not mpv:
            return {
                "mode": "copy",
                "target": "copy",
                "action": None,
                "fallback_url": media.url,
                "tip": "未找到 mpv，已提供复制链接",
            }
        if os.name == "nt":
            pipe_path = rf"\\.\pipe\strmaction-{uuid.uuid4().hex}"
        else:
            pipe_path = str(
                Path(tempfile.gettempdir()) / f"strmaction-{uuid.uuid4().hex}.sock"
            )
        args = [
            mpv,
            "--no-terminal",
            "--force-window",
            f"--input-ipc-server={pipe_path}",
        ]
        if resume_ms and resume_ms > 3000:
            args.append(f"--start={max(0, resume_ms / 1000):.1f}")
        for extra in self.settings.player().get("mpv_extra_args") or []:
            args.append(str(extra))
        if context.headers:
            joined = ",".join(f"{key}: {value}" for key, value in context.headers.items())
            args.append(f"--http-header-fields={joined}")
        args.append(media.url)
        try:
            creationflags = 0x08000000 if os.name == "nt" else 0
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            return {
                "mode": "copy",
                "target": "copy",
                "action": None,
                "fallback_url": media.url,
                "tip": f"启动 mpv 失败：{exc}",
            }
        if self.settings.player().get("enable_progress", True):
            MpvMonitor(self.engine, item.id, pipe_path, process).start()
        print(f"[play] 启动 mpv，媒体={mask_url(media.url)}")
        return {
            "mode": "backend",
            "target": "mpv",
            "action": None,
            "fallback_url": media.url,
            "tip": "已在桌面启动 mpv",
            "pid": process.pid,
        }
