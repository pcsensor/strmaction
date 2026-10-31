"""设置服务：数据库覆盖 > config.yaml > 默认值。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from .config import ConfigManager, deep_merge, mask_config, strip_masked_keys
from .models import Setting, utcnow

SETTINGS_KEY = "app_settings"


class SettingsService:
    def __init__(self, config: ConfigManager, engine):
        self.config = config
        self.engine = engine
        self._load()

    # -- 基础 -------------------------------------------------------------
    def _load(self) -> None:
        override: dict[str, Any] = {}
        with Session(self.engine) as session:
            row = session.get(Setting, SETTINGS_KEY)
            if row and row.value:
                try:
                    parsed = json.loads(row.value)
                    if isinstance(parsed, dict):
                        override = parsed
                except json.JSONDecodeError:
                    override = {}
        self.config.set_db_override(override)

    def effective(self) -> dict[str, Any]:
        return self.config.effective()

    def public(self) -> dict[str, Any]:
        """返回给前端的脱敏配置。"""
        return mask_config(self.effective())

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        clean = strip_masked_keys(patch or {})
        if not clean:
            return self.effective()
        with Session(self.engine) as session:
            # 把读取/合并/写入串行化，避免两个管理员同时 PATCH 时后写覆盖先写。
            session.exec(text("BEGIN IMMEDIATE"))
            row = session.get(Setting, SETTINGS_KEY)
            raw = {}
            if row and row.value:
                try:
                    raw = json.loads(row.value)
                except json.JSONDecodeError:
                    raw = {}
            merged = deep_merge(raw, clean)
            if row is None:
                row = Setting(key=SETTINGS_KEY, value="", updated_at=utcnow())
            row.value = json.dumps(merged, ensure_ascii=False)
            row.updated_at = utcnow()
            session.add(row)
            session.commit()
        self.config.set_db_override(merged)
        return self.effective()

    # -- 便捷读取 ---------------------------------------------------------
    @property
    def data_dir(self):
        return self.config.data_dir

    @property
    def image_dir(self):
        return self.config.image_dir

    def server(self) -> dict[str, Any]:
        return self.effective()["server"]

    def auth(self) -> dict[str, Any]:
        return self.effective()["auth"]

    def scraper(self) -> dict[str, Any]:
        return self.effective()["scraper"]

    def player(self) -> dict[str, Any]:
        return self.effective()["player"]

    def scanner(self) -> dict[str, Any]:
        return self.effective()["scanner"]

    def ui(self) -> dict[str, Any]:
        return self.effective()["ui"]

    def password_hash(self) -> str:
        return self.auth().get("password_hash") or ""

    def username(self) -> str:
        return self.auth().get("username") or "admin"

    def set_password_hash(self, password_hash: str) -> None:
        self.update({"auth": {"password_hash": password_hash}})

    def provider_config(self, provider: str) -> dict[str, Any]:
        return self.scraper().get(provider) or {}

    def priority_for_type(self, library_type: str) -> list[str]:
        priority = self.scraper().get("provider_priority") or {}
        return list(priority.get(library_type) or [])

    def priority_for_library(self, library) -> list[str]:
        if getattr(library, "provider_priority", None):
            try:
                value = json.loads(library.provider_priority)
                if isinstance(value, list):
                    return [str(v) for v in value]
            except (json.JSONDecodeError, TypeError):
                pass
        return self.priority_for_type(library.type)

    def tvdb_season_type(self, library) -> str:
        if getattr(library, "tvdb_season_type", None):
            return library.tvdb_season_type
        return self.provider_config("tvdb").get("season_type") or "default"

    def match_threshold(self) -> float:
        try:
            return float(self.scraper().get("match_threshold") or 0.75)
        except (TypeError, ValueError):
            return 0.75

    def language(self) -> str:
        return self.scraper().get("language") or "zh-CN"
