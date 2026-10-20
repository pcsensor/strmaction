from __future__ import annotations

from urllib.parse import quote

from sqlmodel import Session, select

from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database
from app.api.play import resolve_mode
from app.models import Item, Library, PlayProgress, User
from app.players import PlayContext, select_adapter
from app.players.base import mask_url
from app.players.mpv_ipc import write_progress
from app.players.web_intent import build_mpv_intent


def test_intent_encoding_handles_query_and_fragment():
    url = "https://cdn.example.com/path/a b.m3u8?x=1&y=%23&t=中文#frag"
    intent = build_mpv_intent(url, "三体 S01E01 & 第 1 集", 61_000)
    assert intent.startswith("intent://cdn.example.com/path/a%20b.m3u8?x=1&y=%23&t=")
    assert "package=is.xyz.mpv" in intent
    assert "type=video/any" in intent
    assert "i.position=61000" in intent
    assert "S.title=" + quote("三体 S01E01 & 第 1 集", safe="") in intent
    assert "%23frag" in intent
    assert intent.endswith(";end")


def test_mask_url_does_not_leak_path():
    url = "https://pan.baidu.com/s/very-secret-token-1234567890"
    masked = mask_url(url)
    assert "very-secret-token" not in masked
    assert masked.startswith("https://pan.baidu.com/")


def test_adapter_selection(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)

    context = PlayContext(user_agent="Mozilla/5.0 (Linux; Android 14)", is_android=True)
    adapter = select_adapter("auto", context, settings, db.engine)
    assert adapter.name == "web_intent"

    adapter = select_adapter("copy", context, settings, db.engine)
    assert adapter.name == "clipboard"


def test_mpv_progress_is_user_scoped(tmp_path):
    """桌面 mpv 的进度回写必须按 user_id 隔离，不能覆盖别人的记录。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    db = Database(ConfigManager(config_file))

    with Session(db.engine) as session:
        library = Library(name="测试库", root_path=str(tmp_path), type="movie")
        session.add(library)
        session.commit()
        session.refresh(library)

        item = Item(library_id=library.id, kind="movie", title="进度隔离")
        session.add(item)
        session.commit()
        session.refresh(item)

        first = User(username="u1", password_hash="x", role="user")
        second = User(username="u2", password_hash="x", role="user")
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(second)

        first_id, second_id, item_id = first.id, second.id, item.id

    write_progress(db.engine, item_id, 1_000, 10_000, user_id=first_id)
    write_progress(db.engine, item_id, 2_000, 10_000, user_id=second_id)
    write_progress(db.engine, item_id, 3_000, 10_000, user_id=first_id)

    with Session(db.engine) as session:
        rows = session.exec(
            select(PlayProgress).where(PlayProgress.item_id == item_id)
        ).all()
        by_user = {row.user_id: row.position_ms for row in rows}
        assert by_user == {first_id: 3_000, second_id: 2_000}


def test_server_mpv_is_admin_only(tmp_path):
    """普通用户即使偏好/全局默认是 desktop_mpv，也不能在服务端起 mpv。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)

    desktop = PlayContext(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    android = PlayContext(user_agent="Mozilla/5.0 (Linux; Android 14)", is_android=True)
    companion = PlayContext(user_agent="StrmActionCompanion", is_companion=True)

    assert (
        resolve_mode(
            "desktop_mpv", desktop, settings, db.engine, allow_server_mpv=False
        )
        == "copy"
    )
    assert (
        resolve_mode(
            "desktop_mpv", android, settings, db.engine, allow_server_mpv=False
        )
        == "browser_intent"
    )
    assert (
        resolve_mode(
            "desktop_mpv", companion, settings, db.engine, allow_server_mpv=False
        )
        == "builtin"
    )
    assert (
        resolve_mode("auto", desktop, settings, db.engine, allow_server_mpv=False)
        == "copy"
    )
    assert (
        resolve_mode("auto", android, settings, db.engine, allow_server_mpv=False)
        == "browser_intent"
    )
    assert (
        resolve_mode(
            "browser_intent", desktop, settings, db.engine, allow_server_mpv=False
        )
        == "copy"
    )
    assert (
        resolve_mode("auto", companion, settings, db.engine, allow_server_mpv=False)
        == "builtin"
    )
