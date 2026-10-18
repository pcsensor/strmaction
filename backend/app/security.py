"""鉴权：argon2 密码、签名 Cookie 会话、登录限流。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlmodel import Session

from .config_store import SettingsService
from .models import PlayToken
from .models import Session as SessionRow
from .models import utcnow

SESSION_COOKIE = "st_sess"
SESSION_TTL_DAYS = 30
MAX_FAILURES = 5
LOCK_SECONDS = 300


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


class AuthService:
    def __init__(self, settings: SettingsService, engine):
        self.settings = settings
        self.engine = engine
        self._hasher = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=2)
        self._secret = self._load_secret()
        self._failures: dict[str, list[float]] = {}
        self._lock: dict[str, float] = {}

    # -- secret -----------------------------------------------------------
    def _load_secret(self) -> bytes:
        data_dir: Path = self.settings.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        secret_path = data_dir / ".session_secret"
        if secret_path.exists():
            raw = secret_path.read_bytes().strip()
            if raw:
                return raw
        raw = os.environ.get("STRMACTION_SECRET", "").encode() or secrets.token_bytes(48)
        try:
            secret_path.write_bytes(raw)
            if os.name != "nt":
                os.chmod(secret_path, 0o600)
        except OSError:
            pass
        return raw

    # -- 密码 -------------------------------------------------------------
    def needs_setup(self) -> bool:
        return not bool(self.settings.password_hash())

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password: str) -> bool:
        stored = self.settings.password_hash()
        if not stored:
            return False
        if not stored.startswith("$argon2"):
            # 兼容 config.yaml 里填写明文密码的初始化方式
            return hmac.compare_digest(stored, password)
        try:
            return self._hasher.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def set_password(self, password: str) -> None:
        self.settings.set_password_hash(self.hash_password(password))

    def check_password_strength(self, password: str) -> str | None:
        if len(password or "") < 8:
            return "密码至少需要 8 位"
        if password.isdigit():
            return "密码不能是纯数字"
        if password.lower() in {"password", "12345678", "admin123"}:
            return "密码过于常见"
        return None

    # -- 登录限流 ---------------------------------------------------------
    def is_locked(self, key: str) -> bool:
        until = self._lock.get(key, 0)
        if until and until > time.time():
            return True
        if until:
            self._lock.pop(key, None)
        return False

    def _record_failure(self, key: str) -> None:
        now = time.time()
        window = [t for t in self._failures.get(key, []) if now - t < LOCK_SECONDS]
        window.append(now)
        self._failures[key] = window
        if len(window) >= MAX_FAILURES:
            self._lock[key] = now + LOCK_SECONDS
            self._failures[key] = []

    def reset_failures(self, key: str) -> None:
        self._failures.pop(key, None)
        self._lock.pop(key, None)

    # -- 会话 -------------------------------------------------------------
    def _sign(self, payload: str) -> str:
        digest = hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()
        return _b64e(digest)

    def create_session(self, username: str) -> tuple[str, datetime]:
        jti = secrets.token_urlsafe(24)
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
        with Session(self.engine) as session:
            session.add(
                SessionRow(
                    jti=jti,
                    username=username,
                    created_at=utcnow(),
                    expires_at=expires.isoformat(timespec="seconds"),
                )
            )
            session.commit()
        payload = _b64e(
            json.dumps(
                {
                    "jti": jti,
                    "u": username,
                    "exp": int(expires.timestamp()),
                },
                separators=(",", ":"),
            ).encode()
        )
        return f"{payload}.{self._sign(payload)}", expires

    def validate_session(self, token: str | None) -> str | None:
        if not token or "." not in token:
            return None
        payload, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(payload), signature):
            return None
        try:
            data = json.loads(_b64d(payload))
        except (ValueError, json.JSONDecodeError):
            return None
        jti = data.get("jti")
        exp = int(data.get("exp") or 0)
        if not jti or exp < int(time.time()):
            return None
        with Session(self.engine) as session:
            row = session.get(SessionRow, jti)
            if row is None:
                return None
            try:
                row_exp = datetime.fromisoformat(row.expires_at)
            except ValueError:
                return None
            if row_exp < datetime.now(timezone.utc):
                return None
            return row.username

    def revoke_session(self, token: str | None) -> None:
        if not token or "." not in token:
            return
        payload, _ = token.rsplit(".", 1)
        try:
            data = json.loads(_b64d(payload))
        except (ValueError, json.JSONDecodeError):
            return
        jti = data.get("jti")
        if not jti:
            return
        with Session(self.engine) as session:
            row = session.get(SessionRow, jti)
            if row is not None:
                session.delete(row)
                session.commit()

    def purge_expired_sessions(self) -> None:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session:
            from sqlmodel import select

            for row in session.exec(select(SessionRow)).all():
                try:
                    if datetime.fromisoformat(row.expires_at) < now:
                        session.delete(row)
                except ValueError:
                    continue
            for row in session.exec(select(PlayToken)).all():
                try:
                    if datetime.fromisoformat(row.expires_at) < now:
                        session.delete(row)
                except ValueError:
                    continue
            session.commit()

    # -- 播放凭证（v0.8） -------------------------------------------------
    def play_token_ttl_hours(self) -> int:
        try:
            value = int(self.settings.player().get("play_token_ttl_hours") or 12)
        except (TypeError, ValueError):
            value = 12
        return min(max(value, 1), 72)

    def create_play_token(self, item_id: int) -> tuple[str, str]:
        token = "pt_" + secrets.token_urlsafe(32)
        hours = self.play_token_ttl_hours()
        expires = datetime.now(timezone.utc) + timedelta(hours=hours)
        with Session(self.engine) as session:
            session.add(
                PlayToken(
                    token=token,
                    item_id=item_id,
                    created_at=utcnow(),
                    expires_at=expires.isoformat(timespec="seconds"),
                    revoked=False,
                )
            )
            session.commit()
        return token, expires.isoformat(timespec="seconds")

    def validate_play_token(self, token: str | None, item_id: int) -> str:
        """返回 ok / expired / mismatch / invalid。"""
        if not token or not token.startswith("pt_"):
            return "invalid"
        with Session(self.engine) as session:
            row = session.get(PlayToken, token)
            if row is None:
                return "invalid"
            if row.revoked:
                return "invalid"
            if row.item_id != item_id:
                return "mismatch"
            try:
                expires = datetime.fromisoformat(row.expires_at)
            except ValueError:
                return "invalid"
            if expires < datetime.now(timezone.utc):
                return "expired"
            return "ok"
