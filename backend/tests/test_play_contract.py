"""Cross-client contracts: selected media, two modes and navigation semantics."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import create_app
from app.models import Item, Library, MediaFile


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  data_dir: ./data\n")
    monkeypatch.setenv("STRMACTION_CONFIG", str(config))
    monkeypatch.setenv("STRMACTION_DISABLE_SCHEDULER", "1")
    app = create_app()
    with TestClient(app) as client:
        assert client.post("/api/auth/setup", json={"password": "Contract-only-password"}).status_code == 200
        with Session(app.state.app_state.engine) as session:
            lib = Library(name="contract", root_path=str(tmp_path), auto_scrape=False)
            session.add(lib)
            session.flush()
            movie = Item(library_id=lib.id, kind="movie", title="Versions")
            session.add(movie)
            series = Item(library_id=lib.id, kind="series", title="Series")
            session.add(series)
            folder = Item(library_id=lib.id, kind="folder", title="Course")
            session.add(folder)
            session.flush()
            season = Item(library_id=lib.id, parent_id=series.id, kind="season", title="Season", season_no=1)
            session.add(season)
            session.flush()
            def media(item, name, missing=False):
                path = tmp_path / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("https://example.com/" + name)
                row = MediaFile(item_id=item.id, library_id=lib.id, abs_path=str(path), rel_path=name, url="https://example.com/" + name, missing=missing)
                session.add(row)
                session.flush()
                return row.id
            versions = [media(movie, "a/1080.strm"), media(movie, "b/2160.strm")]
            (tmp_path / "b/2160.zh.srt").write_text("subtitle for selected version")
            episodes = []
            for n in range(1, 4):
                ep = Item(library_id=lib.id, parent_id=season.id, kind="episode", title=f"E{n}", season_no=1, episode_no=n)
                session.add(ep)
                session.flush()
                media(ep, f"e{n}.strm")
                episodes.append(ep.id)
            for n in (1, 2, 10):
                video = Item(library_id=lib.id, parent_id=folder.id, kind="video", title=f"[{n}] lesson")
                session.add(video)
                session.flush()
                media(video, f"course{n}.strm")
            ids = dict(movie=movie.id, folder=folder.id, episodes=episodes, versions=versions)
            session.commit()
        yield client, app, ids


@pytest.mark.parametrize("old", ["auto", "direct", "browser_intent", "external_mpv", "desktop_mpv", "web_intent"])
def test_legacy_requests_never_launch_external_apps(catalog, old):
    client, _, ids = catalog
    for headers, expected in (({}, "copy"), ({"X-StrmAction-Companion": "1"}, "builtin")):
        result = client.post(f"/api/play/{ids['movie']}", json={"mode": old}, headers=headers).json()
        assert result["mode"] == expected
        assert result["action"] is None
        assert result["requested_mode"] == "builtin"


def test_copy_preference_and_explicit_device_override(catalog):
    client, _, ids = catalog
    assert client.patch("/api/me/player", json={"mode": "copy"}).status_code == 200
    headers = {"X-StrmAction-Companion": "1"}
    assert client.post(f"/api/play/{ids['movie']}", json={}, headers=headers).json()["mode"] == "copy"
    assert client.post(f"/api/play/{ids['movie']}", json={"mode": "builtin"}, headers=headers).json()["mode"] == "builtin"
    prefs = client.get("/api/me/player", headers=headers).json()
    assert prefs["allowed_modes"] == ["builtin", "copy"]
    assert "fallback_on_error" not in prefs["effective"]


def test_missing_next_is_skipped_and_manual_next_keeps_watched(catalog):
    client, app, ids = catalog
    e1, e2, e3 = ids["episodes"]
    client.post(f"/api/items/{e2}/watched", json={"finished": True})
    data = client.post(f"/api/play/{e1}", json={}).json()
    assert data["next_item_id"] == e3
    assert data["manual_next_item_id"] == e2
    with Session(app.state.app_state.engine) as session:
        row = session.exec(select(MediaFile).where(MediaFile.item_id == e3)).one()
        row.missing = True
        session.add(row)
        session.commit()
    data = client.post(f"/api/play/{e1}", json={}).json()
    assert data["next_item_id"] is None
    assert [ep["id"] for ep in data["playlist"]] == [e1, e2]
    assert data["manual_next_item_id"] == e2


def test_course_navigation_matches_web_natural_order(catalog):
    client, _, ids = catalog
    detail = client.get(f"/api/items/{ids['folder']}").json()
    play = client.post(f"/api/play/{ids['folder']}", json={}).json()
    assert [x["title"] for x in play["playlist"]] == ["[1] lesson", "[2] lesson", "[10] lesson"]
    assert [x["id"] for x in play["playlist"]] == [x["id"] for x in detail["videos"]]
    assert play["next_item_id"] == play["manual_next_item_id"] == play["playlist"][1]["id"]


def test_selected_version_owns_subtitles_and_missing_version_is_rejected(catalog):
    client, app, ids = catalog
    selected = ids["versions"][1]
    data = client.post(f"/api/play/{ids['movie']}", json={"media_file_id": selected}).json()
    assert data["media_file_id"] == selected
    assert data["play_url"].endswith("b/2160.strm")
    assert client.get(data["subtitles"][0]["url"]).text == "subtitle for selected version"
    with Session(app.state.app_state.engine) as session:
        media = session.get(MediaFile, selected)
        media.missing = True
        session.add(media)
        session.commit()
    assert client.post(f"/api/play/{ids['movie']}", json={"media_file_id": selected}).status_code == 404
