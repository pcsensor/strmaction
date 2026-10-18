from __future__ import annotations

import asyncio

import pytest

from app.config import ConfigManager
from app.config_store import SettingsService
from app.db import Database
from app.scraper.tmdb import TmdbProvider


@pytest.fixture()
def provider(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
    config = ConfigManager(config_file)
    db = Database(config)
    settings = SettingsService(config, db.engine)
    settings.update({"scraper": {"tmdb": {"api_key": "test-key"}}})
    instance = TmdbProvider(settings)
    yield instance
    asyncio.run(instance.close())


def test_tmdb_resolve_imdb(monkeypatch, provider):
    async def fake_cached(path, params, *, tag, ttl_days):
        assert path == "/find/tt0133093"
        assert params["external_source"] == "imdb_id"
        return {"movie_results": [{"id": 603}], "tv_results": []}

    monkeypatch.setattr(provider, "_cached", fake_cached)
    resolved = asyncio.run(provider.resolve_external("tt0133093", "movie"))
    assert resolved == "603"


def test_tmdb_resolve_imdb_missing(monkeypatch, provider):
    async def fake_cached(path, params, *, tag, ttl_days):
        return {"movie_results": [], "tv_results": []}

    monkeypatch.setattr(provider, "_cached", fake_cached)
    assert asyncio.run(provider.resolve_external("tt0000000", "movie")) is None
