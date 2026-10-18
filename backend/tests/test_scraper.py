from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PIL import Image
from sqlmodel import Session, select

from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database
from app.images import ImageService, contrast_ratio, extract_color
from app.models import Item, Library, MediaFile
from app.scanner.sync import ScannerService
from app.scraper.base import (
    Candidate,
    CanonicalMeta,
    EpisodeMeta,
    ProviderHealth,
    SeasonDetail,
    SeasonSummary,
)
from app.scraper.matcher import classify, rank_candidates, score_candidate
from app.scraper.nfo import parse_nfo
from app.scraper.service import ScrapeService
from app.scraper.tmdb import map_meta
from app.scraper.tvdb import TvdbProvider, pick_artwork


def make_file(root: Path, rel: str, url: str = "https://example.com/v.m3u8") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url + "\n", encoding="utf-8")


@pytest.fixture()
def env(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    images = ImageService(settings)
    yield config, db, settings, images
    asyncio.run(images.close())


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------


def test_scoring_and_thresholds():
    candidates = [
        Candidate("tmdb", "1", "三体", "Three-Body", 2023, "tv"),
        Candidate("tmdb", "2", "三体 第二季", "Three-Body II", 2024, "tv"),
        Candidate("tmdb", "3", "三休", None, 2023, "tv"),
    ]
    ranked = rank_candidates("三体", 2023, candidates)
    assert ranked[0][1].provider_id == "1"
    assert ranked[0][0] >= 0.9
    assert classify(0.8) == "auto"
    assert classify(0.65) == "pending"
    assert classify(0.4) == "failed"

    exact = Candidate("tmdb", "4", "流浪地球2", "The Wandering Earth II", 2023, "movie")
    score = score_candidate("流浪地球2", 2023, exact, 0, 1)
    assert score >= 0.9


# ---------------------------------------------------------------------------
# TMDB 映射（golden JSON，不联网）
# ---------------------------------------------------------------------------


def test_tmdb_mapping():
    golden = {
        "title": "流浪地球2",
        "original_title": "The Wandering Earth II",
        "overview": "太阳危机。",
        "tagline": "命运之战",
        "release_date": "2023-01-22",
        "vote_average": 7.9,
        "runtime": 173,
        "status": "Released",
        "genres": [{"id": 878, "name": "科幻"}, {"id": 28, "name": "动作"}],
        "belongs_to_collection": {"id": 1, "name": "流浪地球系列"},
        "images": {
            "posters": [
                {"file_path": "/en.jpg", "iso_639_1": "en", "vote_average": 9, "vote_count": 10},
                {"file_path": "/zh.jpg", "iso_639_1": "zh", "vote_average": 7, "vote_count": 10},
            ],
            "backdrops": [
                {"file_path": "/wide.jpg", "iso_639_1": "zh", "vote_average": 8, "vote_count": 5, "aspect_ratio": 1.78},
                {"file_path": "/tall.jpg", "iso_639_1": "zh", "vote_average": 9, "vote_count": 5, "aspect_ratio": 2.5},
            ],
            "logos": [],
        },
        "credits": {
            "cast": [{"name": "吴京", "character": "刘培强", "profile_path": "/actor.jpg"}],
            "crew": [{"name": "郭帆", "job": "Director", "profile_path": "/dir.jpg"}],
        },
        "videos": {
            "results": [
                {"site": "YouTube", "type": "Teaser", "key": "teaser", "official": True},
                {"site": "YouTube", "type": "Trailer", "key": "trailer", "official": True},
            ]
        },
        "external_ids": {"imdb_id": "tt1234567", "tvdb_id": 9876},
        "alternative_titles": {"titles": [{"title": "流球2"}]},
        "release_dates": {
            "results": [
                {"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]},
                {"iso_3166_1": "CN", "release_dates": [{"certification": ""}]},
            ]
        },
    }
    meta = map_meta(golden, "movie", "603")
    assert meta.title == "流浪地球2"
    assert meta.year == 2023
    assert meta.runtime_min == 173
    assert meta.certification == "PG-13"
    assert meta.trailer_key == "trailer"
    assert meta.poster_url.endswith("/zh.jpg")
    assert meta.backdrop_url.endswith("/wide.jpg")
    assert meta.external_ids == {"tmdb": "603", "imdb": "tt1234567", "tvdb": "9876"}
    assert meta.collection == {"id": 1, "name": "流浪地球系列"}
    assert any(c.name == "郭帆" and c.kind == "director" for c in meta.cast)
    assert meta.genres == ["科幻", "动作"]
    assert "流球2" in meta.aliases


def test_tvdb_mapping(monkeypatch, env):
    config, db, settings, images = env
    settings.update({"scraper": {"tvdb": {"api_key": "test-key"}}})
    provider = TvdbProvider(settings)

    async def fake_translations(provider_id, kind):
        return {"name": "进击的巨人", "overview": "人类与巨人。"}

    async def fake_artworks(provider_id, kind):
        return [
            {"type": "poster", "image": "https://art/p.jpg", "language": "zho", "score": 10},
            {"type": "background", "image": "https://art/b.jpg", "language": "zho", "score": 8},
            {"type": "clearlogo", "image": "https://art/l.png", "language": "eng", "score": 5},
        ]

    async def fake_request(method, path, params=None, *, tag="", ttl_days=0):
        assert "extended" in path
        return {
            "data": {
                "name": "Shingeki no Kyojin",
                "year": "2013",
                "overview": "English overview",
                "score": 8.5,
                "averageRuntime": 24,
                "status": {"name": "Ended"},
                "genres": [{"name": "Anime"}],
                "contentRatings": [{"name": "TV-MA", "country": "USA"}],
                "remoteIds": [
                    {"sourceName": "TheMovieDB.com", "id": "1429"},
                    {"sourceName": "IMDB", "id": "tt2560140"},
                ],
                "aliases": [{"name": "巨人"}],
                "seasons": [
                    {"number": 1, "name": "Season 1", "type": {"type": "official"}, "episodes": [{"id": 1}, {"id": 2}]},
                    {"number": 2, "name": "Season 2", "type": {"type": "official"}, "episodes": [{"id": 3}]},
                ],
            }
        }

    monkeypatch.setattr(provider, "_translations", fake_translations)
    monkeypatch.setattr(provider, "_artworks", fake_artworks)
    monkeypatch.setattr(provider, "_request", fake_request)
    meta = asyncio.run(provider.fetch("1", kind="tv"))
    asyncio.run(provider.close())
    assert meta.title == "进击的巨人"
    assert meta.year == 2013
    assert meta.external_ids["tmdb"] == "1429"
    assert meta.external_ids["imdb"] == "tt2560140"
    assert meta.poster_url == "https://art/p.jpg"
    assert meta.backdrop_url == "https://art/b.jpg"
    assert meta.logo_url == "https://art/l.png"
    assert [s.episode_count for s in meta.seasons] == [2, 1]
    assert meta.certification == "TV-MA"


def test_pick_artwork_language():
    works = [
        {"type": "poster", "image": "en", "language": "eng", "score": 9},
        {"type": "poster", "image": "zh", "language": "zho", "score": 1},
    ]
    assert pick_artwork(works, "poster", "zho") == "zh"


# ---------------------------------------------------------------------------
# 图片与主题色
# ---------------------------------------------------------------------------


def test_image_variants_and_color(env, tmp_path):
    config, db, settings, images = env
    source = tmp_path / "src.jpg"
    image = Image.new("RGB", (1200, 675), (18, 52, 186))
    image.save(source, "JPEG")

    sha = asyncio.run(images.ensure(str(source), "backdrop"))
    assert sha
    assert (settings.image_dir / f"{sha}_780.webp").is_file()
    assert (settings.image_dir / f"{sha}_1280.webp").is_file()
    color = asyncio.run(images.color_for(str(source), sha))
    assert color and color.startswith("#")
    rgb = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
    assert contrast_ratio(rgb, (7, 8, 10)) >= 4.5


# ---------------------------------------------------------------------------
# NFO
# ---------------------------------------------------------------------------


def test_nfo_parse(tmp_path):
    nfo = tmp_path / "movie.nfo"
    nfo.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>测试电影</title>
  <originaltitle>Test Movie</originaltitle>
  <year>2022</year>
  <plot>剧情简介</plot>
  <runtime>120</runtime>
  <genre>剧情</genre>
  <mpaa>PG-13</mpaa>
  <uniqueid type="tmdb">123</uniqueid>
  <uniqueid type="imdb">tt999</uniqueid>
  <director>某导演</director>
  <actor><name>演员甲</name><role>主角</role><thumb>actor.jpg</thumb></actor>
  <thumb>poster.jpg</thumb>
  <fanart><thumb>backdrop.jpg</thumb></fanart>
  <trailer>https://www.youtube.com/watch?v=abc123</trailer>
</movie>""",
        encoding="utf-8",
    )
    data = parse_nfo(nfo)
    assert data["title"] == "测试电影"
    assert data["year"] == 2022
    assert data["runtime_min"] == 120
    assert data["certification"] == "PG-13"
    assert data["external_ids"] == {"tmdb": "123", "imdb": "tt999"}
    assert data["poster"].endswith("poster.jpg")
    assert data["backdrop"].endswith("backdrop.jpg")
    assert data["trailer_key"] == "abc123"
    assert any(c["role"] == "导演" for c in data["cast"])


# ---------------------------------------------------------------------------
# ScrapeService 集成（Fake Provider）
# ---------------------------------------------------------------------------


@dataclass
class FakeProvider:
    name: str
    enabled: bool = True
    supports: set = field(default_factory=lambda: {"movie", "tv"})
    season_type: str = "default"
    overview: str | None = "简介"
    extra: dict = field(default_factory=dict)

    async def search(self, *, title, year, kind):
        return [
            Candidate(
                provider=self.name,
                provider_id="100",
                title=title,
                original_title=title,
                year=year,
                kind=kind,
                popularity=1.0,
            )
        ]

    async def fetch(self, provider_id, *, kind):
        if kind == "movie":
            return CanonicalMeta(
                provider=self.name,
                provider_id=str(provider_id),
                kind="movie",
                title="流浪地球2",
                original_title="The Wandering Earth II",
                year=2023,
                overview=self.overview,
                tagline="命运之战",
                rating=8.2,
                runtime_min=173,
                genres=["科幻"],
                certification="PG-13",
                status="Released",
                external_ids=self.extra or {"tmdb": "603"},
            )
        return CanonicalMeta(
            provider=self.name,
            provider_id=str(provider_id),
            kind="tv",
            title="三体",
            original_title="Three-Body",
            year=2023,
            overview=self.overview,
            rating=8.7,
            genres=["科幻"],
            certification="TV-14",
            external_ids=self.extra or {"tmdb": "100"},
            seasons=[SeasonSummary(season_no=1, name="第 1 季", episode_count=2)],
        )

    async def fetch_season(self, provider_id, season_no):
        return SeasonDetail(
            season_no=season_no,
            episodes=[
                EpisodeMeta(episode_no=1, title="第 1 集", overview="第一集", runtime_min=45),
                EpisodeMeta(episode_no=2, title="第 2 集", overview="第二集", runtime_min=46),
            ],
        )

    async def health(self):
        return ProviderHealth(True, "ok", "ok")


class StubRegistry:
    def __init__(self, providers):
        self.providers = {p.name: p for p in providers}

    def get(self, name):
        return self.providers.get(name)

    async def close(self):
        return None


def _setup(env, tmp_path, type_="movie"):
    config, db, settings, images = env
    root = tmp_path / "lib"
    if type_ == "movie":
        make_file(root, "流浪地球2 (2023)/流浪地球2 (2023).strm")
    else:
        make_file(root, "三体 (2023)/Season 01/三体 - S01E01.strm")
        make_file(root, "三体 (2023)/Season 01/三体 - S01E02.strm")
    with Session(db.engine) as session:
        library = Library(name="lib", root_path=str(root), type=type_)
        session.add(library)
        session.commit()
        library_id = library.id
    ScannerService(db.engine, settings).scan_library(library_id)
    return db, settings, images, library_id


def test_scrape_movie_with_fake_provider(env, tmp_path):
    db, settings, images, library_id = _setup(env, tmp_path, "movie")
    provider = FakeProvider("tmdb")
    service = ScrapeService(
        db.engine, settings, images, registry=StubRegistry([provider])
    )
    with Session(db.engine) as session:
        item = session.exec(select(Item).where(Item.kind == "movie")).one()
        item_id = item.id
    result = asyncio.run(service.scrape_item(item_id))
    asyncio.run(service.close())
    assert result["status"] == "ok"
    assert result["match_state"] == "auto"
    with Session(db.engine) as session:
        item = session.get(Item, item_id)
        assert item.title == "流浪地球2"
        assert item.provider == "tmdb"
        assert item.provider_id == "100"
        assert item.rating == 8.2
        assert item.match_state == "auto"
        assert json.loads(item.genres) == ["科幻"]
        assert item.meta_hash

    # 第二次：hash 未变，标记 unchanged
    provider2 = FakeProvider("tmdb")
    service = ScrapeService(
        db.engine, settings, images, registry=StubRegistry([provider2])
    )
    result2 = asyncio.run(service.scrape_item(item_id, force=True))
    asyncio.run(service.close())
    assert result2["status"] == "ok"


def test_scrape_series_and_episodes(env, tmp_path):
    db, settings, images, library_id = _setup(env, tmp_path, "tv")
    provider = FakeProvider("tmdb")
    service = ScrapeService(
        db.engine, settings, images, registry=StubRegistry([provider])
    )
    with Session(db.engine) as session:
        series = session.exec(select(Item).where(Item.kind == "series")).one()
        series_id = series.id
    result = asyncio.run(service.scrape_item(series_id))
    asyncio.run(service.close())
    assert result["status"] == "ok"
    with Session(db.engine) as session:
        episodes = session.exec(
            select(Item).where(Item.kind == "episode").order_by(Item.episode_no)
        ).all()
        assert [e.title for e in episodes] == ["第 1 集", "第 2 集"]
        assert episodes[0].overview == "第一集"
        assert episodes[0].match_state == "auto"


def test_locked_fields_and_cross_source_fill(env, tmp_path):
    db, settings, images, library_id = _setup(env, tmp_path, "movie")
    tmdb = FakeProvider("tmdb", overview=None, extra={"tmdb": "603", "tvdb": "77"})
    tvdb = FakeProvider("tvdb", overview="来自 TVDB 的简介", extra={"tvdb": "77"})
    service = ScrapeService(
        db.engine, settings, images, registry=StubRegistry([tmdb, tvdb])
    )
    with Session(db.engine) as session:
        item = session.exec(select(Item).where(Item.kind == "movie")).one()
        item_id = item.id
        item.locked_fields = json.dumps(["title"])
        item.title = "手动标题"
        session.add(item)
        session.commit()
    result = asyncio.run(service.scrape_item(item_id))
    asyncio.run(service.close())
    assert result["status"] == "ok"
    with Session(db.engine) as session:
        item = session.get(Item, item_id)
        assert item.title == "手动标题"  # 锁定字段不被覆盖
        assert item.overview == "来自 TVDB 的简介"  # 跨源补空
