from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import (
    ConfigManager,
    mask_config,
    mask_play_headers_json,
    strip_masked_keys,
)
from app.config_store import SettingsService
from app.db import Database
from app.images import ImageService
from app.main import create_app
from app.models import ImageTask, Item, Library, MediaFile, PlayToken, User
from app.scanner.sync import ScanSafetyError, ScannerService, missing_cleanup


def _app_env(tmp_path: Path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    monkeypatch.setenv("STRMACTION_CONFIG", str(config))
    monkeypatch.setenv("STRMACTION_DISABLE_SCHEDULER", "1")
    return create_app()


def test_concurrent_setup_only_creates_one_admin(tmp_path, monkeypatch):
    app = _app_env(tmp_path, monkeypatch)
    with TestClient(app, raise_server_exceptions=False) as client:
        def setup(name: str) -> int:
            return client.post(
                "/api/auth/setup",
                json={"username": name, "password": "good-password"},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(setup, ["firstadmin", "secondadmin"]))
        assert sorted(codes) == [200, 409]
        with Session(app.state.app_state.db.engine) as session:
            admins = session.exec(
                select(User).where(User.role == "admin")
            ).all()
            assert len(admins) == 1


def test_concurrent_admin_demotion_keeps_one_admin(tmp_path, monkeypatch):
    app = _app_env(tmp_path, monkeypatch)
    with TestClient(app, raise_server_exceptions=False) as c1:
        assert c1.post(
            "/api/auth/setup",
            json={"username": "admin1", "password": "good-password"},
        ).status_code == 200
        created = c1.post(
            "/api/users",
            json={"username": "admin2", "password": "good-password", "role": "admin"},
        )
        assert created.status_code == 201
        with Session(app.state.app_state.db.engine) as session:
            users = session.exec(select(User)).all()
            ids = {user.username: user.id for user in users}
        with TestClient(app) as c2:
            assert c2.post(
                "/api/auth/login",
                json={"username": "admin2", "password": "good-password"},
            ).status_code == 200

            def demote(client: TestClient, target: int) -> int:
                return client.patch(
                    f"/api/users/{target}", json={"role": "user"}
                ).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = [
                    pool.submit(demote, c1, ids["admin2"]).result(),
                    pool.submit(demote, c2, ids["admin1"]).result(),
                ]
            assert codes.count(200) == 1
            assert codes.count(200) + codes.count(400) + codes.count(401) + codes.count(403) == 2
        with Session(app.state.app_state.db.engine) as session:
            admins = session.exec(
                select(User).where(User.role == "admin", User.enabled == True)  # noqa: E712
            ).all()
            assert len(admins) == 1


def test_merge_item_removes_dependents_and_rejects_self(tmp_path, monkeypatch):
    app = _app_env(tmp_path, monkeypatch)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post(
            "/api/auth/setup", json={"password": "good-password"}
        ).status_code == 200
        media_dir = tmp_path / "media"
        media_dir.mkdir()
        with Session(app.state.app_state.db.engine) as session:
            library = Library(name="t", root_path=str(media_dir))
            session.add(library)
            session.commit()
            session.refresh(library)
            target = Item(library_id=library.id, title="A", kind="movie")
            source = Item(library_id=library.id, title="B", kind="movie")
            session.add_all([target, source])
            session.commit()
            session.refresh(target)
            session.refresh(source)
            session.add(MediaFile(item_id=source.id, library_id=library.id,
                                  rel_path="b.strm", abs_path=str(media_dir / "b.strm"),
                                  url="https://example.com/b"))
            session.add(ImageTask(item_id=source.id, kind="poster",
                                  remote_url="https://example.com/p"))
            session.add(PlayToken(token="pt_" + "x" * 40, user_id=1,
                                  item_id=source.id, expires_at="2099-01-01T00:00:00+00:00"))
            session.commit()
            target_id, source_id = target.id, source.id

        merged = client.post(f"/api/items/{target_id}/merge", json={"source_id": source_id})
        assert merged.status_code == 200, merged.text
        with Session(app.state.app_state.db.engine) as session:
            assert session.get(Item, source_id) is None
            assert session.exec(select(MediaFile).where(MediaFile.item_id == source_id)).all() == []
            assert session.exec(select(ImageTask).where(ImageTask.item_id == source_id)).all() == []
            assert session.exec(select(PlayToken).where(PlayToken.item_id == source_id)).all() == []

        self_merge = client.post(f"/api/items/{target_id}/merge", json={"source_id": target_id})
        assert self_merge.status_code == 400


def test_import_preserves_folder_video_tree(tmp_path, monkeypatch):
    app = _app_env(tmp_path, monkeypatch)
    media_dir = tmp_path / "home"
    media_dir.mkdir()
    data = {
        "version": 1,
        "libraries": [
            {"id": 1, "name": "home", "root_path": str(media_dir), "type": "home"}
        ],
        "items": [
            {"id": 1, "library_id": 1, "parent_id": None, "kind": "folder", "title": "课程"},
            {"id": 2, "library_id": 1, "parent_id": 1, "kind": "folder", "title": "第一章"},
            {"id": 3, "library_id": 1, "parent_id": 2, "kind": "video", "title": "第 1 课"},
        ],
        "progress": [],
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post(
            "/api/auth/setup", json={"password": "good-password"}
        ).status_code == 200
        response = client.post("/api/import", json={"data": data, "settings": False})
        assert response.status_code == 200, response.text
        with Session(app.state.app_state.db.engine) as session:
            items = session.exec(select(Item)).all()
            assert {item.title for item in items} == {"课程", "第一章", "第 1 课"}
            video = session.exec(select(Item).where(Item.title == "第 1 课")).one()
            folder = session.exec(select(Item).where(Item.title == "第一章")).one()
            assert video.parent_id == folder.id


def test_scan_empty_directory_aborts_before_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STRMACTION_DATA_DIR", str(tmp_path / "data"))
    config = ConfigManager(tmp_path / "config.yaml")
    config.config_path.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config.config_path)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    root = tmp_path / "media"
    root.mkdir()
    (root / "Film.strm").write_text("https://example.com/film\n", encoding="utf-8")
    with Session(db.engine) as session:
        library = Library(name="media", root_path=str(root))
        session.add(library)
        session.commit()
        library_id = library.id
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(library_id)
    (root / "Film.strm").unlink()
    with pytest.raises(ScanSafetyError):
        scanner.scan_library(library_id)
    with Session(db.engine) as session:
        media = session.exec(select(MediaFile)).one()
        assert media.missing is False


def test_sensitive_play_headers_are_masked_and_not_restored():
    masked = mask_config(
        {
            "player": {
                "play_headers": {
                    "Authorization": "Bearer secret-token",
                    "User-Agent": "pan.baidu.com",
                }
            }
        }
    )
    assert masked["player"]["play_headers"]["Authorization"] == "****"
    assert masked["player"]["play_headers"]["User-Agent"] == "pan.baidu.com"
    cleaned = strip_masked_keys(masked)
    assert "Authorization" not in cleaned["player"]["play_headers"]
    exported = mask_play_headers_json(
        '{"Authorization": "Bearer secret-token", "User-Agent": "x"}'
    )
    assert "secret-token" not in exported
    assert "User-Agent" in exported


def test_settings_reject_data_dir_and_invalid_scan_depth(tmp_path, monkeypatch):
    app = _app_env(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/setup", json={"password": "good-password"}
        ).status_code == 200
        assert client.patch(
            "/api/settings", json={"server": {"data_dir": "/tmp/elsewhere"}}
        ).status_code == 400
        assert client.patch(
            "/api/settings", json={"scanner": {"max_depth": 0}}
        ).status_code == 400
        assert client.patch(
            "/api/settings", json={"scanner": {"max_depth": 12}}
        ).status_code == 200


def test_disabled_library_is_not_visible_or_playable(tmp_path, monkeypatch):
    app = _app_env(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/setup", json={"password": "good-password"}
        ).status_code == 200
        with Session(app.state.app_state.db.engine) as session:
            library = Library(name="off", root_path=str(media_dir), enabled=False)
            session.add(library)
            session.commit()
            session.refresh(library)
            item = Item(library_id=library.id, title="hidden", kind="movie")
            session.add(item)
            session.commit()
            session.refresh(item)
            item_id = item.id
        assert client.get("/api/items").json()["total"] == 0
        assert client.post(f"/api/play/{item_id}").status_code == 403


def test_image_sources_reject_local_paths_outside_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("STRMACTION_DATA_DIR", str(tmp_path / "data"))
    config = ConfigManager(tmp_path / "config.yaml")
    config.config_path.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config.config_path)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    images = ImageService(settings)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not an image")
    assert asyncio.run(images.read_source(str(outside))) is None
    assert asyncio.run(images._remote_source_allowed("http://127.0.0.1/x.jpg")) is False
