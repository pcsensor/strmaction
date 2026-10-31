"""新增单集、缓存刷新、图片补齐及详情图片协议的回归测试。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PIL import Image
from sqlmodel import Session, select

from app.api.items import get_item
from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database
from app.images import ImageService
from app.jobs import TaskManager
from app.models import ImageTask, Item, Library, TaskLog, utcnow
from app.scanner.sync import ScannerService
from app.schemas import CurrentUser
from app.scraper.base import CanonicalMeta, EpisodeMeta, SeasonDetail, SeasonSummary
from app.scraper.cache import bypass_cache, cache_load, cache_store
from app.scraper.service import ScrapeService
from app.scraper.tmdb import TmdbProvider
from app.scraper.tvdb import TvdbProvider


@dataclass
class ArtworkProvider:
    image: str
    name: str = "tmdb"
    enabled: bool = True
    detail_calls: list[str] = field(default_factory=list)

    async def search(self, **kwargs):
        raise AssertionError("已绑定的剧目不应重新搜索")

    async def fetch(self, provider_id, *, kind, season_type=None):
        self.detail_calls.append(provider_id)
        return CanonicalMeta(
            provider=self.name, provider_id=provider_id, kind=kind,
            title="三体", overview="整剧简介", year=2023,
            external_ids={self.name: provider_id},
            seasons=[SeasonSummary(1, episode_count=3)],
        )

    async def fetch_season(self, provider_id, season_no, season_type=None):
        return SeasonDetail(season_no, [
            EpisodeMeta(n, title=f"单集 {n}", still_url=self.image)
            for n in (1, 2, 3)
        ])


class Registry:
    def __init__(self, provider):
        self.provider = provider

    def get(self, name):
        return self.provider if name == self.provider.name else None

    async def close(self):
        pass


async def test_root_image_source_is_preserved_for_recovery(media):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    meta = await provider.fetch("100", kind="tv")
    meta.poster_url = provider.image
    await service._persist(series_id, meta, state="auto", score=1, filled=[], season_type="default", force=True)
    await images.process_pending()
    with Session(db.engine) as session:
        task = session.exec(select(ImageTask).where(
            ImageTask.item_id == series_id, ImageTask.kind == "poster"
        )).one()
        assert task.status == "done" and task.remote_url == provider.image
        sha = task.sha
    (images.image_dir / f"{sha}_342.webp").unlink()
    images.start_worker()
    with Session(db.engine) as session:
        task = session.exec(select(ImageTask).where(
            ImageTask.item_id == series_id, ImageTask.kind == "poster"
        )).one()
        assert task.status == "pending"
    await images.process_pending()
    assert images.variants_exist(sha, "poster")


@pytest.fixture()
def media(tmp_path, monkeypatch):
    monkeypatch.setenv("STRMACTION_DATA_DIR", str(tmp_path / "data"))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_path)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    settings.update({"scraper": {"tmdb": {"api_key": "test-placeholder"}}})
    images = ImageService(settings)
    image = settings.data_dir / "still.png"
    Image.new("RGB", (800, 450), "blue").save(image)
    root = tmp_path / "media"

    def add(number):
        path = root / "三体 (2023) {tmdb-100}" / "Season 01" / f"三体 - S01E{number:02d}.strm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"https://example.invalid/{number}\n", encoding="utf-8")

    add(1)
    with Session(db.engine) as session:
        library = Library(name="剧集", root_path=str(root), type="tv")
        session.add(library)
        session.commit()
        library_id = library.id
    scanner = ScannerService(db.engine, settings)
    scanner.scan_library(library_id)
    with Session(db.engine) as session:
        series_id = session.exec(select(Item.id).where(Item.kind == "series")).one()
    provider = ArtworkProvider(str(image))
    service = ScrapeService(db.engine, settings, images, registry=Registry(provider))
    yield db, settings, images, provider, service, scanner, library_id, series_id, add
    asyncio.run(images.close())
    db.engine.dispose()


@pytest.mark.parametrize("action", ["scan", "scrape"])
@pytest.mark.parametrize("state", ["auto", "manual"])
async def test_new_episode_is_scraped_without_changing_series_binding(media, monkeypatch, action, state):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    assert (await service.scrape_item(series_id))["status"] == "ok"
    await images.process_pending()
    with Session(db.engine) as session:
        series = session.get(Item, series_id)
        series.match_state = state
        series.title = "保留的整剧标题"
        series.set_locked_fields(["title"])
        session.add(series)
        session.commit()
    add(2)
    manager = TaskManager(db.engine, settings, images)
    monkeypatch.setattr("app.jobs.ScrapeService", lambda *args, **kwargs: service)
    task_id = manager._create_task(action, library_id)
    if action == "scan":
        await manager._run_scan(task_id, library_id, "test")
    else:
        scanner.scan_library(library_id)
        await manager._run_scrape(task_id, library_id, "pending", "test")
    await images.process_pending()
    with Session(db.engine) as session:
        episode = session.exec(select(Item).where(Item.kind == "episode", Item.episode_no == 2)).one()
        series = session.get(Item, series_id)
        assert episode.title == "单集 2"
        assert episode.still_path
        assert series.title == "保留的整剧标题"
        assert series.match_state == state
        assert (series.provider, series.provider_id) == ("tmdb", "100")
        assert session.get(TaskLog, task_id).status == "success"
    assert provider.detail_calls == ["100"]


@pytest.mark.parametrize("missing", ["field", "file", "broken"])
async def test_refresh_repairs_existing_image_task(media, missing):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    await service.scrape_item(series_id)
    await images.process_pending()
    with Session(db.engine) as session:
        episode = session.exec(select(Item).where(Item.kind == "episode")).one()
        task = session.exec(select(ImageTask).where(ImageTask.kind == "still")).one()
        episode_id, task_id = episode.id, task.id
        if missing == "field":
            episode.still_path = None
        elif missing == "file":
            (images.image_dir / f"{episode.still_path}_780.webp").unlink()
        else:
            episode.still_path = None
            task.status = "broken"
            task.retry = 3
            session.add(task)
        session.add(episode)
        session.commit()
    # 直接走相同 payload 的持久化，确保未变化的 meta_hash 不阻止补图。
    meta = await provider.fetch("100", kind="tv")
    result = await service._persist(
        series_id, meta, state="auto", score=1.0, filled=[], season_type="default", force=False,
    )
    assert result["unchanged"] is True
    await images.process_pending()
    with Session(db.engine) as session:
        episode = session.get(Item, episode_id)
        task = session.get(ImageTask, task_id)
        assert episode.still_path
        assert images.variants_exist(episode.still_path, "still")
        assert task.status == "done"
        assert len(session.exec(select(ImageTask).where(ImageTask.kind == "still")).all()) == 1


async def test_detail_exposes_episode_still_and_download_status(media):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    await service.scrape_item(series_id)
    user = CurrentUser(id=1, username="admin", role="admin", display_name=None)
    before = get_item(series_id, user=user, engine=db.engine)
    assert before["image_status"] == {"pending": 1, "failed": 0}
    await images.process_pending()
    episode_id = before["seasons"][0]["episodes"][0]["id"]
    after = get_item(episode_id, user=user, engine=db.engine)
    assert after["item"]["still"].endswith("_300.webp")
    assert after["item"]["still_large"].endswith("_780.webp")
    assert after["item"]["still"] == after["seasons"][0]["episodes"][0]["still"]
    assert after["image_status"] == {"pending": 0, "failed": 0}


async def test_force_refresh_bypasses_tmdb_detail_and_season_cache(media, monkeypatch):
    db, settings, images, _, _, scanner, library_id, series_id, add = media
    provider = TmdbProvider(settings)
    calls = []
    version = 1

    async def request(method, path, **kwargs):
        calls.append(path)
        if "/season/" in path:
            return {"episodes": [{"episode_number": 1, "name": f"版本 {version}", "still_path": f"/v{version}.jpg"}]}
        return {"name": f"整剧 {version}", "overview": "简介", "seasons": [{"season_number": 1}]}

    monkeypatch.setattr(provider.http, "request", request)

    async def read(source):
        return Path(media[3].image).read_bytes()

    monkeypatch.setattr(images, "read_source", read)
    service = ScrapeService(db.engine, settings, images, registry=Registry(provider))
    await service.scrape_item(series_id)
    await images.process_pending()
    assert calls == ["/tv/100", "/tv/100/season/1"]
    version = 2
    with Session(db.engine) as session:
        series = session.get(Item, series_id)
        series.match_state = "manual"
        session.add(series)
        session.commit()
    result = await service.scrape_item(series_id, force=True)
    assert result["match_state"] == "manual"
    assert calls == ["/tv/100", "/tv/100/season/1"] * 2
    with Session(db.engine) as session:
        assert session.get(Item, series_id).title == "整剧 2"
        assert session.exec(select(Item).where(Item.kind == "episode")).one().title == "版本 2"
        # 手工绑定的 ID 优先于文件名里的旧 ID。
        series = session.get(Item, series_id)
        series.provider_id = "200"
        session.add(series)
        session.commit()
    assert (await service.scrape_item(series_id, force=True))["match_state"] == "manual"
    assert calls[-2:] == ["/tv/200", "/tv/200/season/1"]
    await provider.close()


async def test_incremental_episode_refresh_bypasses_stale_season_cache(media, monkeypatch):
    db, settings, images, _, _, scanner, library_id, series_id, add = media
    provider = TmdbProvider(settings)
    numbers = [1]
    season_calls = 0

    async def request(method, path, **kwargs):
        nonlocal season_calls
        if "/season/" in path:
            season_calls += 1
            return {"episodes": [
                {"episode_number": n, "name": f"单集 {n}", "still_path": f"/ep{n}.jpg"}
                for n in numbers
            ]}
        return {"name": "三体", "overview": "简介", "seasons": [{"season_number": 1}]}

    monkeypatch.setattr(provider.http, "request", request)

    async def read(source):
        return Path(media[3].image).read_bytes()

    monkeypatch.setattr(images, "read_source", read)
    service = ScrapeService(db.engine, settings, images, registry=Registry(provider))
    await service.scrape_item(series_id)
    await images.process_pending()
    add(2)
    scanner.scan_library(library_id)
    numbers.append(2)
    result = await service.scrape_item(series_id)
    await images.process_pending()
    assert result["episodes_only"] is True
    assert season_calls == 2
    with Session(db.engine) as session:
        episode = session.exec(select(Item).where(Item.kind == "episode", Item.episode_no == 2)).one()
        assert episode.still_path and episode.title == "单集 2"
    await provider.close()


async def test_tvdb_cache_can_be_bypassed_without_affecting_other_tasks(media, monkeypatch):
    db, settings, images, *_ = media
    settings.update({"scraper": {"tvdb": {"api_key": "test-placeholder"}}})
    provider = TvdbProvider(settings)
    calls = 0

    async def token():
        return "test-token"

    async def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"data": [{"number": 1, "name": f"版本 {calls}"}]}

    monkeypatch.setattr(provider, "_ensure_token", token)
    monkeypatch.setattr(provider.http, "request", request)
    assert (await provider.fetch_season("100", 1)).episodes[0].title == "版本 1"
    assert (await provider.fetch_season("100", 1)).episodes[0].title == "版本 1"
    with bypass_cache():
        assert (await provider.fetch_season("100", 1)).episodes[0].title == "版本 2"
    assert calls == 2

    cache_store(db.engine, "test", "isolation", {"old": True}, 30)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fresh():
        with bypass_cache():
            entered.set()
            await release.wait()
            assert cache_load(db.engine, "test", "isolation") is None

    async def cached():
        await entered.wait()
        assert cache_load(db.engine, "test", "isolation") == {"old": True}
        release.set()

    await asyncio.gather(fresh(), cached())
    assert cache_load(db.engine, "test", "isolation") == {"old": True}
    await provider.close()


async def test_absolute_episode_numbers_with_gaps_are_not_shifted(media):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    add(3)
    scanner.scan_library(library_id)
    with Session(db.engine) as session:
        root = session.get(Item, series_id)
        episodes, _ = service._children(session, root)
        service._apply_episodes(session, episodes, {}, [
            EpisodeMeta(n, title=f"绝对集号 {n}") for n in (1, 2, 3)
        ], [])
        session.commit()
        assert [(e.episode_no, e.title) for e in episodes] == [(1, "绝对集号 1"), (3, "绝对集号 3")]


async def test_deleted_episode_does_not_trigger_incremental_scrape(media):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    await service.scrape_item(series_id)
    await images.process_pending()
    add(2)
    scanner.scan_library(library_id)
    with Session(db.engine) as session:
        episode = session.exec(select(Item).where(Item.kind == "episode", Item.episode_no == 2)).one()
        episode.deleted_at = utcnow()
        session.add(episode)
        session.commit()
        assert TaskManager(db.engine, settings, images)._pending_item_ids(session, library_id) == []


async def test_pending_download_respects_locked_episode_image(media):
    db, settings, images, provider, service, scanner, library_id, series_id, add = media
    await service.scrape_item(series_id)
    with Session(db.engine) as session:
        episode = session.exec(select(Item).where(Item.kind == "episode")).one()
        episode.still_path = "manual-image"
        episode.set_locked_fields(["still_path"])
        session.add(episode)
        session.commit()
    await images.process_pending()
    with Session(db.engine) as session:
        assert session.exec(select(Item).where(Item.kind == "episode")).one().still_path == "manual-image"
