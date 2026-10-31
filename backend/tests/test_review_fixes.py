from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.home import home
from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database, create_db_engine, migrate_columns
from app.images import ImageService
from app.main import create_app
from app.models import ImageTask, Item, Library, MediaFile, PlayProgress, User, UserLibraryAccess
from app.scanner.sync import ScannerService, missing_cleanup
from app.schemas import CurrentUser


@pytest.fixture
def catalog(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("server:\n  data_dir: ./data\n")
    config = ConfigManager(config_path)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    root = tmp_path / "media"
    root.mkdir()
    (root / "Film.strm").write_text("https://example.com/film\n")
    with Session(db.engine) as session:
        library = Library(name="media", root_path=str(root))
        session.add(library)
        session.commit()
        library_id = library.id
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(library_id)
    return db, settings, root, library_id, scanner


def test_offline_root_does_not_mark_files_missing(catalog):
    db, _, root, _, scanner = catalog
    root.rename(root.with_name("offline"))
    with pytest.raises(OSError):
        scanner.scan_library(1)
    with Session(db.engine) as session:
        media = session.exec(select(MediaFile)).one()
        assert not media.missing and media.missing_count == 0


def test_unreadable_subdirectory_aborts_scan(catalog, monkeypatch):
    db, _, root, library_id, scanner = catalog
    import app.scanner.walker as walker
    (root / "hidden").mkdir()
    scan = walker.os.scandir
    def guarded(path):
        if os.fspath(path).endswith("hidden"):
            raise PermissionError("unreadable")
        return scan(path)
    monkeypatch.setattr(walker.os, "scandir", guarded)
    with pytest.raises(OSError, match="unreadable"):
        scanner.scan_library(library_id)
    with Session(db.engine) as session:
        assert session.exec(select(MediaFile)).one().missing is False


def test_existing_progress_schema_receives_version_defaults(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE play_progress (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO play_progress (id) VALUES (1)")
    engine = create_db_engine(path)
    try:
        migrate_columns(engine)
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT revision, client_session, client_sequence FROM play_progress WHERE id=1"
            ).one()
            assert tuple(row) == (0, None, 0)
    finally:
        engine.dispose()


def test_cleanup_deletes_missing_item_and_dependencies(catalog):
    db, settings, root, library_id, scanner = catalog
    (root / "Film.strm").unlink()
    for _ in range(3):
        scanner.scan_library(library_id)
    with Session(db.engine) as session:
        item = session.exec(select(Item)).one()
        item.deleted_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        session.add(PlayProgress(item_id=item.id, position_ms=5))
        session.add(item)
        session.commit()
    with Session(db.engine) as session:
        assert missing_cleanup(session, settings) == 1
    with Session(db.engine) as session:
        assert session.exec(select(Item)).all() == []
        assert session.exec(select(MediaFile)).all() == []
        assert session.exec(select(PlayProgress)).all() == []


def test_revoked_library_is_absent_from_continue(catalog, tmp_path):
    db, _, _, library_id, _ = catalog
    with Session(db.engine) as session:
        item = session.exec(select(Item)).one()
        user = User(username="viewer", password_hash="hash", role="user")
        other = Library(name="other", root_path=str(tmp_path / "other"))
        session.add_all([user, other])
        session.commit()
        session.add(UserLibraryAccess(user_id=user.id, library_id=other.id))
        session.add(PlayProgress(user_id=user.id, item_id=item.id, position_ms=5))
        session.commit()
        current = CurrentUser(id=user.id, username=user.username, role=user.role, display_name=None)
    assert home(current, db.engine)["continue"] == []


def test_referenced_old_image_is_not_purged(catalog):
    db, settings, _, _, _ = catalog
    images = ImageService(settings)
    kept = images.image_dir / ("a" * 40 + "_342.webp")
    unused = images.image_dir / ("b" * 40 + "_342.webp")
    kept.write_bytes(b"image")
    unused.write_bytes(b"image")
    old = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
    os.utime(kept, (old, old))
    os.utime(unused, (old, old))
    with Session(db.engine) as session:
        item = session.exec(select(Item)).one()
        item.poster_path = "a" * 40
        session.add(item)
        session.commit()
    assert images.purge_older_than(90) == 1
    assert kept.exists() and not unused.exists()


def test_reselected_image_source_gets_latest_task(catalog):
    db, settings, _, _, _ = catalog
    images = ImageService(settings)
    with Session(db.engine) as session:
        item_id = session.exec(select(Item.id)).one()
    images.enqueue(item_id, "poster", "https://example.com/first", "poster_path")
    images.enqueue(item_id, "poster", "https://example.com/second", "poster_path")
    images.enqueue(item_id, "poster", "https://example.com/first", "poster_path")
    with Session(db.engine) as session:
        tasks = session.exec(select(ImageTask).order_by(ImageTask.id)).all()
        assert [task.remote_url for task in tasks] == [
            "https://example.com/first", "https://example.com/second", "https://example.com/first"
        ]
        images._apply_task(session, tasks[0], "a" * 40)
        assert session.get(Item, item_id).poster_path is None
        images._apply_task(session, tasks[-1], "b" * 40)
        assert session.get(Item, item_id).poster_path == "b" * 40


async def test_interrupted_and_missing_image_tasks_are_requeued(catalog):
    db, settings, _, _, _ = catalog
    with Session(db.engine) as session:
        item = session.exec(select(Item)).one()
        session.add_all([
            ImageTask(item_id=item.id, kind="still", remote_url="https://example.com/a", status="downloading"),
            ImageTask(item_id=item.id, kind="still", remote_url="https://example.com/b", status="done", sha="b" * 40),
        ])
        session.commit()
    images = ImageService(settings)
    images.start_worker()
    with Session(db.engine) as session:
        assert [row.status for row in session.exec(select(ImageTask).order_by(ImageTask.id)).all()] == ["pending", "pending"]
    await images.close()


def test_progress_rejects_stale_sessions_and_allows_seek(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  data_dir: ./data\n")
    monkeypatch.setenv("STRMACTION_CONFIG", str(config))
    monkeypatch.setenv("STRMACTION_DISABLE_SCHEDULER", "1")
    app = create_app()
    with TestClient(app) as client:
        assert client.post("/api/auth/setup", json={"password": "good-password"}).status_code == 200
        engine = app.state.app_state.db.engine
        with Session(engine) as session:
            library = Library(name="test", root_path=str(tmp_path))
            session.add(library)
            session.commit()
            item = Item(library_id=library.id, title="test", kind="movie")
            session.add(item)
            session.commit()
            item_id = item.id
        url = f"/api/items/{item_id}/progress"
        def send(owner, seq, base, position):
            return client.post(url, json={"client_session": owner, "client_sequence": seq,
                "base_revision": base, "position_ms": position, "duration_ms": 100000})
        assert send("a", 1, 0, 50000).json()["revision"] == 1
        assert send("a", 2, 0, 10000).json()["position_ms"] == 10000
        assert send("a", 1, 0, 50000).json()["duplicate"] is True
        assert send("b", 1, 0, 30000).status_code == 409
        assert send("b", 1, 2, 30000).status_code == 200
        assert send("a", 3, 0, 60000).status_code == 409


def test_concurrent_login_attempts_obey_limit(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  data_dir: ./data\n")
    monkeypatch.setenv("STRMACTION_CONFIG", str(config))
    monkeypatch.setenv("STRMACTION_DISABLE_SCHEDULER", "1")
    with TestClient(create_app()) as client:
        assert client.post("/api/auth/setup", json={"password": "good-password"}).status_code == 200
        with ThreadPoolExecutor(max_workers=6) as pool:
            codes = list(pool.map(lambda _: client.post(
                "/api/auth/login", json={"username": "admin", "password": "bad-password"}
            ).status_code, range(6)))
        assert sorted(codes) == [401, 401, 401, 401, 401, 429]
