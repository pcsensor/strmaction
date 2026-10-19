from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database
from app.models import (
    ImageTask,
    Item,
    Library,
    MediaFile,
    PlayProgress,
    PlayToken,
    Setting,
)
from app.scanner.sync import ScannerService


def make_file(root: Path, rel: str, url: str = "https://example.com/video.m3u8") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def env(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    return config, db, settings


def _library(db, root: Path, type_: str, template: str | None = None) -> int:
    with Session(db.engine) as session:
        lib = Library(name=root.name, root_path=str(root), type=type_, template=template)
        session.add(lib)
        session.commit()
        return lib.id


def test_movie_scan_versions_and_incremental(env, tmp_path):
    config, db, settings = env
    root = tmp_path / "movies"
    make_file(root, "流浪地球2 (2023)/流浪地球2 (2023).strm")
    make_file(root, "沙丘2 (2024)/沙丘2 (2024) - 2160p.strm")
    make_file(root, "沙丘2 (2024)/沙丘2 (2024) - 1080p.strm")
    make_file(root, "无名/无名.strm")
    make_file(root, "空文件/坏文件.strm", "")

    lib_id = _library(db, root, "movie")
    scanner = ScannerService(db.engine, settings)
    stats = scanner.scan_library(lib_id)
    assert stats["scanned"] == 5
    assert stats["invalid"] == 1

    with Session(db.engine) as session:
        movies = session.exec(select(Item).where(Item.kind == "movie")).all()
        titles = {m.title: m for m in movies}
        assert "流浪地球2" in titles
        assert "沙丘2" in titles
        assert "无名" in titles
        dune = titles["沙丘2"]
        files = session.exec(select(MediaFile).where(MediaFile.item_id == dune.id)).all()
        assert len(files) == 2
        assert {f.version for f in files} == {"2160p", "1080p"}
        assert dune.year == 2024

    # 二次扫描：全部增量跳过
    stats2 = scanner.scan_library(lib_id)
    assert stats2["parsed"] == 0
    assert stats2["skipped"] == 4  # 坏文件不会入库，因此只跳过 4 个有效文件
    with Session(db.engine) as session:
        assert len(session.exec(select(Item).where(Item.kind == "movie")).all()) == 3
        assert len(session.exec(select(MediaFile)).all()) == 4


def test_tv_scan_structure(env, tmp_path):
    config, db, settings = env
    root = tmp_path / "tv"
    make_file(root, "三体 (2023)/Season 01/三体 - S01E01.strm")
    make_file(root, "三体 (2023)/Season 01/三体 - S01E02.strm")
    make_file(root, "漫长的季节 (2023)/S01/漫长的季节.01.strm")
    make_file(root, "狂飙/第一季/第12集.strm")
    make_file(root, "Some.Show.2020/Season 02/Some.Show.S02E03.1080p.strm")

    lib_id = _library(db, root, "tv")
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(lib_id)

    with Session(db.engine) as session:
        series = {
            s.title: s for s in session.exec(select(Item).where(Item.kind == "series")).all()
        }
        assert set(series) == {"三体", "漫长的季节", "狂飙", "Some Show"}
        santi = series["三体"]
        seasons = session.exec(
            select(Item).where(Item.parent_id == santi.id, Item.kind == "season")
        ).all()
        assert [s.season_no for s in seasons] == [1]
        episodes = session.exec(
            select(Item).where(Item.parent_id == seasons[0].id, Item.kind == "episode")
        ).all()
        assert sorted(e.episode_no for e in episodes) == [1, 2]

        # 再次扫描不应重复创建
        scanner.scan_library(lib_id)

    with Session(db.engine) as session:
        assert len(session.exec(select(Item).where(Item.kind == "series")).all()) == 4
        assert len(session.exec(select(Item).where(Item.kind == "episode")).all()) == 5


def test_missing_mark_and_move(env, tmp_path):
    config, db, settings = env
    root = tmp_path / "tv"
    rel = "三体 (2023)/Season 01/三体 - S01E01.strm"
    file = make_file(root, rel)
    lib_id = _library(db, root, "tv")
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(lib_id)

    with Session(db.engine) as session:
        media = session.exec(select(MediaFile)).one()
        item_id = media.item_id

    # 移动文件（内容 URL 相同）→ 应归并到同一条目，而不是新建
    new_rel = "三体 (2023)/Season 01/三体 - S01E01 修复版.strm"
    new_path = root / new_rel
    file.rename(new_path)

    stats = scanner.scan_library(lib_id)
    assert stats["moved_files"] == 1
    with Session(db.engine) as session:
        media = session.exec(select(MediaFile)).one()
        assert media.item_id == item_id
        assert media.rel_path == new_rel
        assert media.missing is False
        assert len(session.exec(select(Item).where(Item.kind == "episode")).all()) == 1

    # 删除文件 → missing=1
    new_path.unlink()
    scanner.scan_library(lib_id)
    with Session(db.engine) as session:
        media = session.exec(select(MediaFile)).one()
        assert media.missing is True
        assert media.missing_count == 1


def test_movie_library_with_tv_structure(env, tmp_path):
    """电影库里的电视剧：按剧名/季/集入库，多个剧并列互不干扰。"""
    config, db, settings = env
    root = tmp_path / "mixed"
    make_file(root, "卿卿日常 2022/Season 01/S01E01-S01E40/S01E01.strm", "https://example.com/q1.m3u8")
    make_file(root, "卿卿日常 2022/Season 01/S01E01-S01E40/S01E02.strm", "https://example.com/q2.m3u8")
    make_file(root, "狂飙/S01E01.strm", "https://example.com/k1.m3u8")
    make_file(root, "狂飙/第2集.strm", "https://example.com/k2.m3u8")
    make_file(root, "流浪地球2 (2023)/流浪地球2 (2023).strm")

    lib_id = _library(db, root, "movie")
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(lib_id)

    with Session(db.engine) as session:
        series = {
            s.title: s
            for s in session.exec(select(Item).where(Item.kind == "series")).all()
        }
        assert set(series) == {"卿卿日常", "狂飙"}
        assert series["卿卿日常"].year == 2022

        seasons = session.exec(
            select(Item).where(
                Item.parent_id == series["卿卿日常"].id, Item.kind == "season"
            )
        ).all()
        assert [s.season_no for s in seasons] == [1]
        episodes = session.exec(
            select(Item).where(
                Item.parent_id == seasons[0].id, Item.kind == "episode"
            )
        ).all()
        assert sorted(e.episode_no for e in episodes) == [1, 2]
        assert {e.title for e in episodes} == {"第1集", "第2集"}

        # 电影仍然是电影，没有被剧集规则吞掉
        movie = session.exec(
            select(Item).where(Item.kind == "movie")
        ).one()
        assert movie.title == "流浪地球2"


def test_movie_library_becomes_tv_when_only_episodes(env, tmp_path):
    config, db, settings = env
    root = tmp_path / "only_tv"
    make_file(root, "卿卿日常 2022/Season 01/S01E01.strm")
    make_file(root, "卿卿日常 2022/Season 01/S01E02.strm")
    lib_id = _library(db, root, "movie")
    ScannerService(db.engine, settings).scan_library(lib_id)
    with Session(db.engine) as session:
        assert session.get(Library, lib_id).type == "tv"


def test_existing_library_is_reparsed_after_parser_upgrade(env, tmp_path):
    """升级后首次扫描必须重解析旧文件，把「一部 Season 01 电影」拆回剧集。"""
    config, db, settings = env
    root = tmp_path / "legacy"
    make_file(root, "卿卿日常 2022/Season 01/S01E01.strm")
    make_file(root, "卿卿日常 2022/Season 01/S01E02.strm")
    lib_id = _library(db, root, "movie")
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(lib_id)

    # 模拟 v1 的入库结果：整季被当成一部标题为 Season 01 的电影，多个版本
    with Session(db.engine) as session:
        legacy = Item(
            library_id=lib_id,
            kind="movie",
            title="Season 01",
            match_state="pending",
        )
        session.add(legacy)
        session.flush()
        for media in session.exec(select(MediaFile)).all():
            media.item_id = legacy.id
            session.add(media)
        # 旧条目上残留的进度 / 凭证 / 图片任务：清理时必须一并删除，
        # 否则 SQLite 外键会让扫描在 _prune_orphans 里失败。
        session.add(
            PlayProgress(
                item_id=legacy.id,
                position_ms=60_000,
                duration_ms=120_000,
            )
        )
        session.add(
            PlayToken(
                token="legacy-play-token",
                item_id=legacy.id,
                expires_at="2099-01-01T00:00:00+00:00",
            )
        )
        session.add(
            ImageTask(
                item_id=legacy.id,
                kind="poster",
                remote_url="https://example.com/poster.jpg",
            )
        )
        for kind in ("episode", "season", "series"):
            for item in session.exec(select(Item).where(Item.kind == kind)).all():
                session.delete(item)
        setting = session.get(Setting, f"scanner:parser_version:{lib_id}")
        if setting is not None:
            session.delete(setting)
        session.commit()

    stats = scanner.scan_library(lib_id)
    assert stats["parsed"] == 2
    assert stats["skipped"] == 0

    with Session(db.engine) as session:
        series = session.exec(select(Item).where(Item.kind == "series")).one()
        assert series.title == "卿卿日常"
        assert session.exec(select(Item).where(Item.kind == "movie")).all() == []
        episodes = session.exec(select(Item).where(Item.kind == "episode")).all()
        assert sorted(e.episode_no for e in episodes) == [1, 2]
        assert session.exec(select(PlayProgress)).all() == []
        assert session.exec(select(PlayToken)).all() == []
        assert session.exec(select(ImageTask)).all() == []

    # 解析版本已记录，下一次扫描恢复增量跳过
    stats2 = scanner.scan_library(lib_id)
    assert stats2["skipped"] == 2


def test_home_and_course(env, tmp_path):
    config, db, settings = env
    home_root = tmp_path / "home"
    course_root = tmp_path / "course"
    make_file(home_root, "2024-06-01 生日/VID_20240601.mp4.strm")
    make_file(course_root, "Rust 实战/01 所有权/01 所有权.strm")
    make_file(course_root, "Rust 实战/01 所有权/02 借用.strm")

    home_id = _library(db, home_root, "home")
    course_id = _library(db, course_root, "course")
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(home_id)
    scanner.scan_library(course_id)

    with Session(db.engine) as session:
        groups = session.exec(
            select(Item).where(Item.kind == "series", Item.library_id == home_id)
        ).all()
        assert [g.title for g in groups] == ["2024-06-01 生日"]
        videos = session.exec(
            select(Item).where(Item.kind == "video", Item.library_id == home_id)
        ).all()
        assert [v.title for v in videos] == ["VID 20240601"]

        course = session.exec(
            select(Item).where(Item.kind == "series", Item.library_id == course_id)
        ).one()
        assert course.title == "Rust 实战"
        chapter = session.exec(
            select(Item).where(Item.kind == "season", Item.parent_id == course.id)
        ).one()
        assert chapter.title == "所有权"
        eps = session.exec(
            select(Item).where(Item.kind == "episode", Item.parent_id == chapter.id)
        ).all()
        assert sorted(e.episode_no for e in eps) == [1, 2]
