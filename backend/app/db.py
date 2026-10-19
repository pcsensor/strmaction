"""数据库 engine / session / 初始化。"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from .config import ConfigManager

_ENGINES: dict[str, object] = {}


def get_engine(config: ConfigManager):
    key = config.db_path.as_posix()
    if key not in _ENGINES:
        _ENGINES[key] = create_db_engine(config.db_path)
    return _ENGINES[key]


def create_db_engine(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):  # pragma: no cover - 驱动层
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_item_parent ON item(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_item_lib_kind ON item(library_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_item_title ON item(sort_title)",
    "CREATE INDEX IF NOT EXISTS idx_item_match_state ON item(library_id, match_state)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_abs ON media_file(abs_path)",
    "CREATE INDEX IF NOT EXISTS idx_media_item ON media_file(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_library ON media_file(library_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_started ON task_log(started_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_scrape_cache ON scrape_cache(provider, query_hash)",
    "CREATE INDEX IF NOT EXISTS idx_image_status ON image_task(status)",
    "CREATE INDEX IF NOT EXISTS idx_item_library ON item(library_id)",
    # v0.9 多用户体系索引
    "CREATE INDEX IF NOT EXISTS idx_user_username ON user(username)",
    "CREATE INDEX IF NOT EXISTS idx_user_role ON user(role)",
    "CREATE INDEX IF NOT EXISTS idx_user_lib_user ON user_library_access(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_lib_library ON user_library_access(library_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_lib ON user_library_access(user_id, library_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_progress_user_item ON play_progress(user_id, item_id)",
    "CREATE INDEX IF NOT EXISTS idx_play_token_user ON play_token(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_play_token_item ON play_token(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id)",
]

# 轻量迁移：SQLModel 的 create_all 不会给已存在的表补列。
# 新增字段时在这里登记即可，启动时按 PRAGMA 结果幂等补齐。
COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "library": [("play_headers", "TEXT")],
    "play_progress": [
        ("dismissed", "BOOLEAN DEFAULT 0"),
        ("user_id", "INTEGER"),  # v0.9 多用户
    ],
    "play_token": [("user_id", "INTEGER")],  # v0.9 多用户
    "session": [
        ("user_id", "INTEGER"),  # v0.9 多用户
        ("role", "TEXT DEFAULT 'user'"),  # v0.9 多用户
    ],
}


def migrate_columns(engine) -> None:
    with engine.begin() as conn:
        for table, columns in COLUMN_MIGRATIONS.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            if not rows:
                continue
            existing = {row[1] for row in rows}
            for name, ddl in columns:
                if name not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                    )
                    print(f"[db] 迁移：{table}.{name} 已添加")


def migrate_to_multiuser(engine) -> None:
    """v0.9 多用户体系迁移：创建默认管理员并迁移现有数据。"""
    import json
    import os
    from .models import User

    with Session(engine) as db:
        # 检查是否已迁移
        existing_users = db.exec(text("SELECT COUNT(*) FROM user")).first()
        if existing_users and existing_users[0] > 0:
            return  # 已迁移

        # 1. 从 setting 表读取原 app_settings 配置
        admin_username = "admin"
        admin_password_hash = ""

        row = db.exec(text("SELECT value FROM setting WHERE key = 'app_settings'")).first()
        if row and row[0]:
            try:
                val = json.loads(row[0])
                auth_cfg = val.get("auth", {})
                admin_username = auth_cfg.get("username") or "admin"
                admin_password_hash = auth_cfg.get("password_hash") or ""
            except Exception:
                pass

        if not admin_password_hash:
            admin_password_hash = os.environ.get("STRMACTION_ADMIN_PASSWORD_HASH", "")

        # 如果没有密码哈希，说明是全新安装，不提前创建空密码管理员（等待设置向导）
        if not admin_password_hash:
            return

        print(f"[db] 执行 v0.9 多用户迁移，迁移管理员 '{admin_username}'...")

        # 2. 创建默认管理员
        admin = User(
            username=admin_username,
            password_hash=admin_password_hash,
            role="admin",
            display_name="管理员",
            enabled=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        # 3. 迁移 play_progress：现有记录全部归属管理员
        db.exec(text(f"UPDATE play_progress SET user_id = {admin.id} WHERE user_id IS NULL"))

        # 4. 迁移 session：现有会话全部设为管理员
        db.exec(text(f"UPDATE session SET user_id = {admin.id}, role = 'admin' WHERE user_id IS NULL"))

        # 5. 迁移 play_token：现有 token 归属管理员
        db.exec(text(f"UPDATE play_token SET user_id = {admin.id} WHERE user_id IS NULL"))

        db.commit()
        print(f"[db] v0.9 迁移完成：管理员账号 '{admin_username}' (id={admin.id})")


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    migrate_columns(engine)
    migrate_to_multiuser(engine)  # v0.9 多用户迁移
    with engine.begin() as conn:
        for stmt in INDEXES:
            conn.execute(text(stmt))


def session_scope(engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


class Database:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.engine = get_engine(config)
        init_db(self.engine)
        self._session_factory = lambda: Session(self.engine)

    def session(self) -> Session:
        return self._session_factory()
