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
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_progress_item ON play_progress(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_started ON task_log(started_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_scrape_cache ON scrape_cache(provider, query_hash)",
    "CREATE INDEX IF NOT EXISTS idx_image_status ON image_task(status)",
    "CREATE INDEX IF NOT EXISTS idx_item_library ON item(library_id)",
    "CREATE INDEX IF NOT EXISTS idx_play_token_item ON play_token(item_id)",
]

# 轻量迁移：SQLModel 的 create_all 不会给已存在的表补列。
# 新增字段时在这里登记即可，启动时按 PRAGMA 结果幂等补齐。
COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "library": [("play_headers", "TEXT")],
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


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    migrate_columns(engine)
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
