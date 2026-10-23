from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="strmaction-test-"))
CONFIG = ROOT / "config.yaml"
CONFIG.write_text("server:\n  data_dir: ./data\n", encoding="utf-8")
os.environ["STRMACTION_CONFIG"] = str(CONFIG)
os.environ["STRMACTION_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

MEDIA = ROOT / "media"


def make(rel: str, url: str = "https://example.com/video.m3u8") -> None:
    path = MEDIA / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url + "\n", encoding="utf-8")


make("电影/流浪地球2 (2023)/流浪地球2 (2023).strm")
make("电影/沙丘2 (2024)/沙丘2 (2024) - 2160p.strm")
make("电影/沙丘2 (2024)/沙丘2 (2024) - 1080p.strm")
make("剧集/三体 (2023)/Season 01/三体 - S01E01.strm")
make("剧集/三体 (2023)/Season 01/三体 - S01E02.strm")
make("剧集/坏文件/坏文件.strm", "")  # 内容为空 → invalid


def wait_task(client: TestClient, task_id: int, timeout: float = 20) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] != "running":
            return task
        time.sleep(0.2)
    raise AssertionError(f"task {task_id} still running")


def test_full_flow():
    app = create_app()
    with TestClient(app) as client:
        # 未登录保护
        state = client.get("/api/auth/state")
        assert state.status_code == 200
        assert state.json()["needs_setup"] is True
        assert state.json()["authenticated"] is False
        unauthorized = client.get("/api/items")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "SETUP_REQUIRED"
        assert client.get("/api/health").json()["ok"] is True

        # 密码强度
        weak = client.post("/api/auth/setup", json={"password": "123"})
        assert weak.status_code == 400

        setup = client.post("/api/auth/setup", json={"password": "S3cure-passphrase"})
        assert setup.status_code == 200, setup.text
        assert client.get("/api/auth/state").json()["authenticated"] is True

        # 媒体库
        movie_root = MEDIA / "电影"
        tv_root = MEDIA / "剧集"
        created = client.post(
            "/api/libraries",
            json={"name": "电影", "root_path": str(movie_root), "type": "movie"},
        )
        assert created.status_code == 201, created.text
        movie_lib = created.json()["id"]
        tv_created = client.post(
            "/api/libraries",
            json={"name": "剧集", "root_path": str(tv_root), "type": "tv"},
        )
        assert tv_created.status_code == 201
        tv_lib = tv_created.json()["id"]
        duplicate = client.post(
            "/api/libraries",
            json={"name": "重复", "root_path": str(tv_root), "type": "tv"},
        )
        assert duplicate.status_code == 409

        # 扫描电影
        scan = client.post(f"/api/libraries/{movie_lib}/scan")
        assert scan.status_code == 200
        task = wait_task(client, scan.json()["task_id"])
        assert task["status"] == "success", task
        assert task["stats"]["scanned"] == 3

        movies = client.get("/api/items", params={"library_id": movie_lib})
        assert movies.status_code == 200, movies.text
        movie_items = movies.json()["items"]
        titles = {i["title"] for i in movie_items}
        assert titles == {"流浪地球2", "沙丘2"}
        dune = next(i for i in movie_items if i["title"] == "沙丘2")

        # 详情 + 多版本
        detail = client.get(f"/api/items/{dune['id']}").json()
        assert len(detail["media_files"]) == 2
        assert {m["version"] for m in detail["media_files"]} == {"2160p", "1080p"}
        assert "url" not in json.dumps(detail)

        # 扫描剧集
        tv_scan = client.post(f"/api/libraries/{tv_lib}/scan")
        tv_task = wait_task(client, tv_scan.json()["task_id"])
        assert tv_task["status"] == "success", tv_task
        assert tv_task["stats"]["invalid"] == 1

        series_list = client.get("/api/items", params={"library_id": tv_lib}).json()["items"]
        series = next(i for i in series_list if i["title"] == "三体")
        series_detail = client.get(f"/api/items/{series['id']}").json()
        assert series_detail["seasons"][0]["episode_count"] == 2
        episode_id = series_detail["seasons"][0]["episodes"][0]["id"]
        episode2_id = series_detail["seasons"][0]["episodes"][1]["id"]
        assert series_detail["item"]["play_target_id"] == episode_id

        # 剧集详情页：播放目标必须是当前这一集，而不是整部剧的第一集
        episode2_detail = client.get(f"/api/items/{episode2_id}").json()
        assert episode2_detail["item"]["play_target_id"] == episode2_id
        assert episode2_detail["prev_episode_id"] == episode_id
        assert episode2_detail["next_episode_id"] is None

        # 季详情页：播放目标应为该季第一集
        season_detail = client.get(
            f"/api/items/{series_detail['seasons'][0]['id']}"
        ).json()
        assert season_detail["item"]["play_target_id"] == episode_id

        # 首页 / 搜索
        home = client.get("/api/home").json()
        assert home["stats"]["movies"] == 2
        assert home["stats"]["episodes"] == 2
        assert any(row["key"] == "recent" for row in home["rows"])
        search = client.get("/api/search", params={"q": "三体"}).json()
        assert search["total"] == 1

        # 播放 + 进度回传 + 续播
        play = client.post(f"/api/play/{series['id']}", json={})
        assert play.status_code == 200, play.text
        play_data = play.json()
        assert play_data["play_url"].startswith("http")
        assert play_data["item_id"] == episode_id
        assert play_data["resume_ms"] == 0
        # 播放器「选集」：同一部剧的全部剧集
        assert play_data["series_title"] == "三体"
        assert [entry["code"] for entry in play_data["playlist"]] == [
            "S01E01",
            "S01E02",
        ]
        assert play_data["current_index"] == 0
        assert play_data["playlist"][0]["current"] is True

        progress = client.post(
            f"/api/items/{episode_id}/progress",
            json={"position_ms": 60000, "duration_ms": 120000, "finished": False},
        )
        assert progress.status_code == 200, progress.text
        assert progress.json()["position_ms"] == 60000

        play_again = client.post(f"/api/play/{series['id']}", json={}).json()
        assert play_again["resume_ms"] == 60000

        # 幂等
        dup = client.post(
            f"/api/items/{episode_id}/progress",
            json={
                "position_ms": 60000,
                "duration_ms": 120000,
                "client_key": "k1",
            },
        ).json()
        assert dup["position_ms"] == 60000
        duplicate_key = client.post(
            f"/api/items/{episode_id}/progress",
            json={
                "position_ms": 61000,
                "duration_ms": 120000,
                "client_key": "k1",
            },
        ).json()
        assert duplicate_key.get("duplicate") is True
        assert duplicate_key["position_ms"] == 60000

        # 回退/快退实时记录：拉回较早位置应实时更新（不记录最大位置）
        regression = client.post(
            f"/api/items/{episode_id}/progress",
            json={"position_ms": 1000, "duration_ms": 120000},
        ).json()
        assert regression["position_ms"] == 1000
        assert regression.get("ignored") is not True
        play_regressed = client.post(f"/api/play/{series['id']}", json={}).json()
        assert play_regressed["resume_ms"] == 1000

        # 90% 自动已看
        finished = client.post(
            f"/api/items/{episode_id}/progress",
            json={"position_ms": 115000, "duration_ms": 120000},
        ).json()
        assert finished["finished"] is True
        assert finished["position_ms"] == 0

        # 手动已看 / 未看
        watched = client.post(
            f"/api/items/{series['id']}/watched", json={"finished": True}
        ).json()
        assert watched["count"] == 2
        unwatched = client.post(
            f"/api/items/{series['id']}/watched", json={"finished": False}
        ).json()
        assert unwatched["count"] == 2

        # 字段编辑 + 锁定
        preview = client.patch(
            f"/api/items/{dune['id']}",
            json={"title": "沙丘 第二部", "overview": "手动简介"},
        )
        assert preview.status_code == 200
        assert set(preview.json()["locked_fields"]) == {"title", "overview"}
        assert preview.json()["title"] == "沙丘 第二部"
        unlocked = client.post(f"/api/items/{dune['id']}/unlock")
        assert unlocked.status_code == 200
        assert unlocked.json()["locked_fields"] == []

        # 设置
        settings = client.get("/api/settings").json()
        assert settings["settings"]["scraper"]["tmdb"]["api_key"] == ""
        patched = client.patch(
            "/api/settings", json={"scraper": {"language": "zh-CN"}}
        )
        assert patched.status_code == 200
        cache_setting = client.patch(
            "/api/settings", json={"player": {"cache_limit_mb": 64}}
        )
        assert cache_setting.status_code == 200
        assert cache_setting.json()["settings"]["player"]["cache_limit_mb"] == 64
        cache_play = client.post(f"/api/play/{series['id']}", json={})
        assert cache_play.status_code == 200
        assert cache_play.json()["cache_limit_mb"] == 64
        cache_clamped = client.patch(
            "/api/settings", json={"player": {"cache_limit_mb": 99999}}
        )
        assert cache_clamped.json()["settings"]["player"]["cache_limit_mb"] == 2048
        client.patch("/api/settings", json={"player": {"cache_limit_mb": 128}})
        test = client.post(
            "/api/settings/provider-test", json={"provider": "tmdb"}
        ).json()
        assert test["ok"] is False

        # 导出不含播放地址
        exported = client.get("/api/export").json()
        dumped = json.dumps(exported, ensure_ascii=False)
        assert "https://example.com" not in dumped
        assert exported["version"] == 1
        assert len(exported["items"]) >= 3

        imported = client.post("/api/import", json={"data": exported, "settings": False})
        assert imported.status_code == 200, imported.text
        assert imported.json()["ok"] is True
        assert imported.json()["imported"]["scan_required"] is True

        # 任务
        tasks = client.get("/api/tasks").json()["tasks"]
        assert tasks and tasks[0]["kind"] in {"scan", "scrape"}

        # 登出
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/items").status_code == 401

        # 登录
        bad = client.post(
            "/api/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert bad.status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        assert login.status_code == 200, login.text


def test_play_token_headers_and_subtitles():
    """v0.8：库级请求头、play_token Bearer 鉴权、外挂字幕、连播跳过已看。"""
    from app.models import PlayToken, utcnow

    app = create_app()
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        assert login.status_code == 200, login.text

        libraries = client.get("/api/libraries").json()["libraries"]
        tv = next(lib for lib in libraries if lib["type"] == "tv")
        patched = client.patch(
            f"/api/libraries/{tv['id']}",
            json={
                "play_headers": {
                    "User-Agent": "pan.baidu.com",
                    "Referer": "https://pan.baidu.com/",
                }
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["play_headers"]["User-Agent"] == "pan.baidu.com"

        # 非法头（CRLF 注入 / 非法名字）必须被清洗掉
        dirty = client.patch(
            f"/api/libraries/{tv['id']}",
            json={"play_headers": {"Bad Header": "x", "X-Test": "a\r\nInjected: 1"}},
        )
        assert dirty.status_code == 200
        assert dirty.json()["play_headers"] == {}
        client.patch(
            f"/api/libraries/{tv['id']}",
            json={"play_headers": {"User-Agent": "pan.baidu.com"}},
        )

        # 外挂字幕（SmartStrm 复制到同目录的 .srt）
        srt = MEDIA / "剧集" / "三体 (2023)" / "Season 01" / "三体 - S01E01.chs.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n你好\n",
            encoding="utf-8",
        )

        items = client.get("/api/items", params={"library_id": tv["id"]}).json()["items"]
        series = next(i for i in items if i["title"] == "三体")
        play = client.post(f"/api/play/{series['id']}", json={})
        assert play.status_code == 200, play.text
        data = play.json()
        assert data["headers"]["User-Agent"] == "pan.baidu.com"
        assert "Referer" not in data["headers"]
        assert data["headers_hint"].startswith("User-Agent: pan.baidu.com")
        assert data["play_token"].startswith("pt_")
        assert data["play_token_expires_at"]
        assert data["progress_interval_ms"] == 5000
        assert data["cache_limit_mb"] == 128
        assert data["next_item_id"] is not None  # 第二集
        assert len(data["subtitles"]) == 1
        assert data["subtitles"][0]["lang"] == "zh"

        # Cookie 方式可取字幕
        sub = client.get(data["subtitles"][0]["url"])
        assert sub.status_code == 200
        assert "你好" in sub.text

        item_id = data["item_id"]
        token = data["play_token"]
        detail = client.get(f"/api/items/{series['id']}").json()
        episodes = detail["seasons"][0]["episodes"]
        other_id = next(ep["id"] for ep in episodes if ep["id"] != item_id)

        # 清掉 Cookie，仅用 play_token 写进度
        client.cookies.clear()
        bearer = {"Authorization": f"Bearer {token}"}
        ok = client.post(
            f"/api/items/{item_id}/progress",
            json={"position_ms": 30000, "duration_ms": 120000, "finished": False},
            headers=bearer,
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["position_ms"] == 30000

        # 字幕同样可用 ?pt= 取（原生播放器无法自定义头）
        token_sub = client.get(data["subtitles"][0]["url"])
        assert token_sub.status_code == 200
        assert "你好" in token_sub.text

        # token 绑定单个条目
        mismatch = client.post(
            f"/api/items/{other_id}/progress",
            json={"position_ms": 1000, "duration_ms": 120000},
            headers=bearer,
        )
        assert mismatch.status_code == 403
        assert mismatch.json()["error"]["code"] == "PLAY_TOKEN_MISMATCH"

        # 无凭证 → 401
        client.cookies.clear()
        assert (
            client.post(
                f"/api/items/{item_id}/progress",
                json={"position_ms": 1000, "duration_ms": 120000},
            ).status_code
            == 401
        )

        # 过期 token → 明确的错误码
        state = app.state.app_state
        with __import__("sqlmodel").Session(state.engine) as session:
            session.add(
                PlayToken(
                    token="pt_expired",
                    item_id=item_id,
                    created_at=utcnow(),
                    expires_at="2020-01-01T00:00:00+00:00",
                )
            )
            session.commit()
        expired = client.post(
            f"/api/items/{item_id}/progress",
            json={"position_ms": 1000, "duration_ms": 120000},
            headers={"Authorization": "Bearer pt_expired"},
        )
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "PLAY_TOKEN_EXPIRED"

        # 未登录访问 /api/play 仍必须 401（play_token 不能换播放地址）
        assert client.post(f"/api/play/{series['id']}", json={}).status_code == 401

        # 连播跳过已看：看完第一集后，从第二集起播且没有下一集
        relogin = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        assert relogin.status_code == 200
        watched = client.post(
            f"/api/items/{episodes[0]['id']}/watched", json={"finished": True}
        )
        assert watched.status_code == 200
        after = client.post(f"/api/play/{series['id']}", json={}).json()
        assert after["item_id"] == other_id
        assert after["next_item_id"] is None


def test_dismiss_continue_watching():
    """从「继续观看」移除后首页不再出现，但媒体库及详情中仍展示播放进度。"""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        libraries = client.get("/api/libraries").json()["libraries"]
        tv = next(lib for lib in libraries if lib["type"] == "tv")
        items = client.get("/api/items", params={"library_id": tv["id"]}).json()["items"]
        series = next(i for i in items if i["title"] == "三体")
        detail = client.get(f"/api/items/{series['id']}").json()
        ep0 = detail["seasons"][0]["episodes"][0]

        # 1. 产生播放进度（在看 30 秒 / 120 秒）
        progress_res = client.post(
            f"/api/items/{ep0['id']}/progress",
            json={"position_ms": 30000, "duration_ms": 120000},
        )
        assert progress_res.status_code == 200

        # 2. 首页「继续观看」中应存在三体
        home1 = client.get("/api/home").json()
        continue_ids = [c["continue_item_id"] for c in home1["continue"]]
        assert ep0["id"] in continue_ids

        # 3. 从继续观看中移除（传 series ID 或 episode ID 均可）
        dismiss = client.delete(f"/api/items/{series['id']}/continue")
        assert dismiss.status_code == 200

        # 4. 再次获取首页：继续观看中已被移除
        home2 = client.get("/api/home").json()
        continue_ids2 = [c["continue_item_id"] for c in home2["continue"]]
        assert ep0["id"] not in continue_ids2

        # 5. 但从媒体库/详情进入：进度依然保留且正确展示
        detail_after = client.get(f"/api/items/{series['id']}").json()
        ep0_after = detail_after["seasons"][0]["episodes"][0]
        assert ep0_after["progress"] is not None
        assert ep0_after["progress"]["position_ms"] == 30000
        assert ep0_after["progress"]["duration_ms"] == 120000

        # 6. 用户再次观看并上报新进度：自动重新出现在「继续观看」
        client.post(
            f"/api/items/{ep0['id']}/progress",
            json={"position_ms": 45000, "duration_ms": 120000},
        )
        home3 = client.get("/api/home").json()
        continue_ids3 = [c["continue_item_id"] for c in home3["continue"]]
        assert ep0["id"] in continue_ids3


def test_continue_watching_grouped_by_playlist():
    """同一播放列表（剧集/文件夹）在「继续观看」里只出一张卡，且是最后一次播放的那条。"""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        libraries = client.get("/api/libraries").json()["libraries"]
        tv = next(lib for lib in libraries if lib["type"] == "tv")
        items = client.get("/api/items", params={"library_id": tv["id"]}).json()["items"]
        series = next(i for i in items if i["title"] == "三体")
        detail = client.get(f"/api/items/{series['id']}").json()
        episodes = detail["seasons"][0]["episodes"]
        assert len(episodes) >= 2
        ep0, ep1 = episodes[0], episodes[1]
        episode_ids = {ep0["id"], ep1["id"]}

        # 1. 两集都产生进度（ep1 后写，是「最后一次播放」）
        for episode in (ep0, ep1):
            res = client.post(
                f"/api/items/{episode['id']}/progress",
                json={"position_ms": 30000, "duration_ms": 120000},
            )
            assert res.status_code == 200

        # 2. 首页只出现一张卡，且指向最后一次播放的那集
        home = client.get("/api/home").json()
        shown = [
            c for c in home["continue"] if c["continue_item_id"] in episode_ids
        ]
        assert len(shown) == 1
        assert shown[0]["continue_item_id"] == ep1["id"]

        # 3. 移除最新一集 → 整个播放列表消失（旧集不会顶上来）
        assert client.delete(f"/api/items/{ep1['id']}/continue").status_code == 200
        home2 = client.get("/api/home").json()
        assert not [
            c for c in home2["continue"] if c["continue_item_id"] in episode_ids
        ]

        # 4. 详情页里两集的进度依然保留
        detail_after = client.get(f"/api/items/{series['id']}").json()
        eps_after = detail_after["seasons"][0]["episodes"]
        assert eps_after[0]["progress"]["position_ms"] == 30000
        assert eps_after[1]["progress"]["position_ms"] == 30000


def test_multiuser_and_permissions():
    """v0.9：多用户增删改查、媒体库授权隔离、播放进度隔离及管理权限拦截。"""
    app = create_app()
    with TestClient(app) as admin_client:
        admin_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        libs = admin_client.get("/api/libraries").json()["libraries"]
        movie_lib = next(l for l in libs if l["type"] == "movie")
        tv_lib = next(l for l in libs if l["type"] == "tv")

        # 1. 管理员创建普通用户（仅授权电影库）
        create_res = admin_client.post(
            "/api/users",
            json={
                "username": "viewer1",
                "password": "Password-123",
                "display_name": "观众1",
                "role": "user",
                "library_ids": [movie_lib["id"]],
            },
        )
        assert create_res.status_code == 201, create_res.text
        user_id = create_res.json()["id"]

        # 2. 普通用户登录
        with TestClient(app) as user_client:
            login_res = user_client.post(
                "/api/auth/login",
                json={"username": "viewer1", "password": "Password-123"},
            )
            assert login_res.status_code == 200, login_res.text

            # 3. 普通用户只能看到电影库，看不到剧集库
            user_libs = user_client.get("/api/libraries").json()["libraries"]
            user_lib_ids = [l["id"] for l in user_libs]
            assert movie_lib["id"] in user_lib_ids
            assert tv_lib["id"] not in user_lib_ids

            # 3.1 普通用户拿到的是精简库信息，不暴露服务器路径/请求头
            user_movie_lib = next(l for l in user_libs if l["id"] == movie_lib["id"])
            assert user_movie_lib["root_path"] == ""
            assert user_movie_lib["play_headers"] == {}
            admin_movie_lib = next(l for l in libs if l["id"] == movie_lib["id"])
            assert admin_movie_lib["root_path"]

            # 4. 普通用户无法访问管理端接口（settings / tasks / users / export / import）
            assert user_client.get("/api/settings").status_code == 403
            assert user_client.get("/api/tasks").status_code == 403
            assert user_client.get("/api/users").status_code == 403
            assert user_client.get("/api/export").status_code == 403
            assert user_client.post(
                "/api/import",
                json={"data": {"libraries": []}, "settings": True},
            ).status_code == 403

            # 4.1 关于信息：所有用户可见，但不向普通用户泄露数据目录
            about = user_client.get("/api/about")
            assert about.status_code == 200
            assert about.json()["version"]
            assert about.json()["data_dir"] is None
            assert admin_client.get("/api/about").json()["data_dir"]

            # 4.2 个人播放偏好：普通用户可读写自己的 mode / fallback
            pref = user_client.get("/api/me/player")
            assert pref.status_code == 200
            assert pref.json()["overrides"] == {"mode": None, "fallback_on_error": None}
            # v1.3：服务端 mpv / 外部 mpv 已下线，所有人可选模式一致
            assert pref.json()["allowed_modes"] == [
                "auto", "builtin", "browser_intent", "copy"
            ]
            assert pref.json()["client"]["is_browser"] is True
            assert pref.json()["available_modes"] == ["auto", "copy"]
            assert pref.json()["resolved_mode"] == "copy"  # 桌面浏览器默认 builtin → copy
            admin_pref = admin_client.get("/api/me/player").json()
            assert admin_pref["allowed_modes"] == pref.json()["allowed_modes"]
            assert admin_pref["available_modes"] == ["auto", "copy"]

            patched = user_client.patch(
                "/api/me/player",
                json={"mode": "builtin", "fallback_on_error": False},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["effective"]["mode"] == "builtin"
            assert patched.json()["effective"]["fallback_on_error"] is False
            assert patched.json()["resolved_mode"] == "copy"  # 桌面浏览器没有原生播放器
            # 白名单之外的字段 / 已下线的 mpv 相关字段必须拒绝
            assert user_client.patch(
                "/api/me/player", json={"mode": "nope"}
            ).status_code == 422
            assert user_client.patch(
                "/api/me/player", json={"mpv_path": "/tmp/evil"}
            ).status_code == 422
            assert user_client.patch(
                "/api/me/player", json={"mode": "desktop_mpv"}
            ).status_code == 422

            # 5. 普通用户不能访问剧集库的条目
            tv_items = admin_client.get("/api/items", params={"library_id": tv_lib["id"]}).json()["items"]
            tv_item = tv_items[0]
            assert user_client.get(f"/api/items/{tv_item['id']}").status_code == 403
            assert user_client.post(f"/api/items/{tv_item['id']}/match", json={"provider": "tmdb", "provider_id": "1"}).status_code == 403
            assert user_client.post(f"/api/play/{tv_item['id']}").status_code == 403

            # 6. 普通用户播放进度隔离测试
            movie_items = user_client.get("/api/items", params={"library_id": movie_lib["id"]}).json()["items"]
            movie_item = movie_items[0]

            # 6.0 管理端写接口必须拦截普通用户（unlock / poster）
            assert user_client.post(f"/api/items/{movie_item['id']}/unlock").status_code == 403
            assert user_client.post(
                f"/api/items/{movie_item['id']}/poster",
                files={"file": ("x.png", b"not-an-image", "image/png")},
                data={"kind": "poster"},
            ).status_code == 403
            assert admin_client.post(f"/api/items/{movie_item['id']}/unlock").status_code == 200

            # 6.1 桌面端 direct：返回 URL/headers/token，不触发服务端播放器
            direct_play = user_client.post(
                f"/api/play/{movie_item['id']}", json={"mode": "direct"}
            )
            assert direct_play.status_code == 200, direct_play.text
            assert direct_play.json()["mode"] == "direct"
            assert direct_play.json()["play_url"]
            assert direct_play.json()["play_token"]
            assert direct_play.json()["downgraded"] is False

            # 6.2 内置播放器在桌面浏览器明确降级为 copy，并带降级原因
            external_play = user_client.post(f"/api/play/{movie_item['id']}", json={})
            assert external_play.status_code == 200, external_play.text
            assert external_play.json()["mode"] == "copy"
            assert external_play.json()["requested_mode"] == "builtin"
            assert external_play.json()["downgraded"] is True
            assert external_play.json()["downgrade_reason"] == "requires_companion"
            assert external_play.json()["fallback_on_error"] is False

            # 6.1.1 browser_intent 在桌面浏览器同样降级
            user_client.patch("/api/me/player", json={"mode": "browser_intent"})
            intent_play = user_client.post(f"/api/play/{movie_item['id']}", json={})
            assert intent_play.status_code == 200, intent_play.text
            assert intent_play.json()["mode"] == "copy"
            assert intent_play.json()["downgrade_reason"] == "requires_android"

            # 6.1.2 个人偏好 copy 生效；管理员默认 builtin 在 Android 浏览器走 intent
            user_client.patch("/api/me/player", json={"mode": "copy"})
            android_ua = {"user-agent": "Mozilla/5.0 (Linux; Android 14)"}
            user_android = user_client.post(
                f"/api/play/{movie_item['id']}", json={}, headers=android_ua
            )
            assert user_android.status_code == 200, user_android.text
            assert user_android.json()["mode"] == "copy"
            admin_android = admin_client.post(
                f"/api/play/{movie_item['id']}", json={}, headers=android_ua
            )
            assert admin_android.status_code == 200, admin_android.text
            assert admin_android.json()["mode"] == "browser_intent"

            # 6.2 显式 null 清除个人覆盖，回落到全局默认
            cleared = user_client.patch("/api/me/player", json={"mode": None})
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["overrides"]["mode"] is None
            assert cleared.json()["effective"]["mode"] == "builtin"
            assert cleared.json()["resolved_mode"] == "copy"

            # 6.3 已下线的 mpv 模式不能再写进全局默认
            rejected = admin_client.patch(
                "/api/settings", json={"player": {"mode": "desktop_mpv"}}
            )
            assert rejected.status_code == 400, rejected.text
            assert admin_client.get("/api/settings").json()["settings"]["player"]["mode"] == "builtin"
            # 旧客户端写回 mpv 字段也会被丢弃
            admin_client.patch(
                "/api/settings", json={"player": {"mpv_path": "/usr/bin/mpv"}}
            )
            player_cfg = admin_client.get("/api/settings").json()["settings"]["player"]
            assert "mpv_path" not in player_cfg
            assert "mpv_extra_args" not in player_cfg
            assert "mpv_package" not in player_cfg
            assert "enable_progress" not in player_cfg

            # 普通用户上报进度 50000ms
            p_res = user_client.post(
                f"/api/items/{movie_item['id']}/progress",
                json={"position_ms": 50000, "duration_ms": 120000},
            )
            assert p_res.status_code == 200

            # 普通用户详情中显示 50000ms
            u_detail = user_client.get(f"/api/items/{movie_item['id']}").json()
            assert u_detail["progress"]["position_ms"] == 50000
            assert u_detail["library"]["root_path"] == ""
            assert u_detail["library"]["play_headers"] == {}

            # 管理员详情中不受影响（仍然无进度）
            a_detail = admin_client.get(f"/api/items/{movie_item['id']}").json()
            assert a_detail["progress"] is None
            assert a_detail["library"]["root_path"]

            # 6.4 导出/导入按 user_id 恢复进度，不能覆盖其他用户
            exported = admin_client.get("/api/export").json()
            assert any(row.get("user_id") == user_id for row in exported["progress"])
            for row in exported["progress"]:
                if row.get("user_id") == user_id:
                    row["position_ms"] = 60000
            imported = admin_client.post(
                "/api/import", json={"data": exported, "settings": False}
            )
            assert imported.status_code == 200, imported.text
            restored = user_client.get(f"/api/items/{movie_item['id']}").json()
            assert restored["progress"]["position_ms"] == 60000

            # 6.5 改密会注销该用户全部旧会话
            revoked_client = TestClient(app)
            assert revoked_client.post(
                "/api/auth/login",
                json={"username": "viewer1", "password": "Password-123"},
            ).status_code == 200
            changed = user_client.post(
                "/api/auth/password",
                json={
                    "current_password": "Password-123",
                    "new_password": "New-Password-456",
                },
            )
            assert changed.status_code == 200, changed.text
            assert revoked_client.get("/api/home").status_code == 401
            assert user_client.post(
                "/api/auth/login",
                json={"username": "viewer1", "password": "New-Password-456"},
            ).status_code == 200

            # 6.6 管理员重置密码同样注销目标用户会话
            reset = admin_client.patch(
                f"/api/users/{user_id}", json={"password": "Another-Pass-789"}
            )
            assert reset.status_code == 200, reset.text
            assert user_client.get("/api/home").status_code == 401
            assert user_client.post(
                "/api/auth/login",
                json={"username": "viewer1", "password": "Another-Pass-789"},
            ).status_code == 200

        # 7. 管理员更新用户媒体库授权（追加剧集库）
        update_lib = admin_client.put(
            f"/api/users/{user_id}/libraries",
            json={"library_ids": [movie_lib["id"], tv_lib["id"]]},
        )
        assert update_lib.status_code == 200

        # 8. 管理员删除用户
        del_res = admin_client.delete(f"/api/users/{user_id}")
        assert del_res.status_code == 204

        # 9. 删除“创建过其他用户”的账号：created_by 引用应先置空
        creator_res = admin_client.post(
            "/api/users",
            json={
                "username": "creator",
                "password": "Creator-Pass-123",
                "role": "admin",
            },
        )
        assert creator_res.status_code == 201, creator_res.text
        creator_id = creator_res.json()["id"]

        creator_client = TestClient(app)
        assert creator_client.post(
            "/api/auth/login",
            json={"username": "creator", "password": "Creator-Pass-123"},
        ).status_code == 200
        child_res = creator_client.post(
            "/api/users",
            json={
                "username": "admin-two",
                "password": "Admin2-Pass-123",
                "role": "admin",
            },
        )
        assert child_res.status_code == 201, child_res.text
        child_id = child_res.json()["id"]

        child_client = TestClient(app)
        assert child_client.post(
            "/api/auth/login",
            json={"username": "admin-two", "password": "Admin2-Pass-123"},
        ).status_code == 200
        # admin-two 的 created_by 指向 creator；删除 creator 不能触发 FK 失败
        assert child_client.delete(f"/api/users/{creator_id}").status_code == 204
        assert admin_client.delete(f"/api/users/{child_id}").status_code == 204


def test_search_genre_filter():
    from sqlmodel import Session, select
    from app.models import Item, Library, MediaFile

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "S3cure-passphrase"})
        if login.status_code != 200:
            client.post("/api/auth/setup", json={"password": "S3cure-passphrase"})

        engine = app.state.app_state.engine
        with Session(engine) as session:
            lib = Library(name="测试库", root_path=str(MEDIA / "电影"), type="movie")
            session.add(lib)
            session.commit()
            session.refresh(lib)

            item1 = Item(
                library_id=lib.id,
                kind="movie",
                title="剧情电影A",
                genres=json.dumps(["剧情", "动作"]),
                rating=8.5,
            )
            item2 = Item(
                library_id=lib.id,
                kind="movie",
                title="科幻电影B",
                genres=json.dumps(["科幻", "冒险"]),
                rating=9.0,
            )
            item3 = Item(
                library_id=lib.id,
                kind="movie",
                title="悬疑剧情片C",
                genres=json.dumps(["剧情", "悬疑"]),
                rating=7.8,
            )
            session.add_all([item1, item2, item3])
            session.commit()
            session.refresh(item1)
            session.refresh(item2)
            session.refresh(item3)

            mf1 = MediaFile(
                item_id=item1.id,
                library_id=lib.id,
                rel_path="a.strm",
                abs_path=str(MEDIA / "a.strm"),
                url="http://test/1",
            )
            mf2 = MediaFile(
                item_id=item2.id,
                library_id=lib.id,
                rel_path="b.strm",
                abs_path=str(MEDIA / "b.strm"),
                url="http://test/2",
            )
            mf3 = MediaFile(
                item_id=item3.id,
                library_id=lib.id,
                rel_path="c.strm",
                abs_path=str(MEDIA / "c.strm"),
                url="http://test/3",
            )
            session.add_all([mf1, mf2, mf3])
            session.commit()

        # 1. 无搜索词，纯按 genre 筛选 "剧情"
        res = client.get("/api/search", params={"genre": "剧情"}).json()
        assert res["total"] == 2
        titles = {i["title"] for i in res["items"]}
        assert titles == {"剧情电影A", "悬疑剧情片C"}

        # 2. 无搜索词，纯按 genre 筛选 "科幻"
        res = client.get("/api/search", params={"genre": "科幻"}).json()
        assert res["total"] == 1
        assert res["items"][0]["title"] == "科幻电影B"

        # 3. 无搜索词，无 genre 筛选（返回全部条目，大于等于 3）
        res = client.get("/api/search").json()
        assert res["total"] >= 3

        # 4. 组合筛选：关键词 "悬疑" + genre "剧情"
        res = client.get("/api/search", params={"q": "悬疑", "genre": "剧情"}).json()
        assert res["total"] == 1
        assert res["items"][0]["title"] == "悬疑剧情片C"

        # 5. 组合筛选：关键词 "悬疑" + 不匹配的 genre "科幻"
        res = client.get("/api/search", params={"q": "悬疑", "genre": "科幻"}).json()
        assert res["total"] == 0


def test_missing_media_hidden_from_items_home_and_search():
    from sqlmodel import Session, select
    from app.models import Item, Library, MediaFile

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "S3cure-passphrase"})
        if login.status_code != 200:
            client.post("/api/auth/setup", json={"password": "S3cure-passphrase"})

        engine = app.state.app_state.engine
        with Session(engine) as session:
            lib = Library(name="缺失测试库", root_path=str(MEDIA / "缺失测试"), type="movie")
            session.add(lib)
            session.commit()
            session.refresh(lib)

            item = Item(
                library_id=lib.id,
                kind="movie",
                title="已删除文件影片",
                rating=8.0,
            )
            session.add(item)
            session.commit()
            session.refresh(item)

            mf = MediaFile(
                item_id=item.id,
                library_id=lib.id,
                rel_path="deleted.strm",
                abs_path=str(MEDIA / "deleted.strm"),
                url="http://test/deleted",
                missing=True,
                missing_count=1,
            )
            session.add(mf)
            session.commit()
            item_id = item.id
            lib_id = lib.id

        # 1. 媒体库列表：不显示该影片
        res = client.get(f"/api/items?library_id={lib_id}").json()
        item_ids = [i["id"] for i in res["items"]]
        assert item_id not in item_ids

        # 2. 媒体库信息统计：排除缺失文件和未就绪条目
        lib_data = next(l for l in client.get("/api/libraries").json()["libraries"] if l["id"] == lib_id)
        assert lib_data["counts"]["files"] == 0
        assert lib_data["counts"].get("movie", 0) == 0

        # 3. 搜索：不显示该影片
        res = client.get("/api/search", params={"q": "已删除文件"}).json()
        assert res["total"] == 0

        # 4. 详情接口：media_files 为空
        res = client.get(f"/api/items/{item_id}").json()
        assert res["media_files"] == []

        # 5. 恢复 missing=False 后立即重新显示且 counts 更新
        with Session(engine) as session:
            mf_db = session.exec(select(MediaFile).where(MediaFile.item_id == item_id)).one()
            mf_db.missing = False
            session.add(mf_db)
            session.commit()

        res = client.get(f"/api/items?library_id={lib_id}").json()
        item_ids = [i["id"] for i in res["items"]]
        assert item_id in item_ids

        lib_data = next(l for l in client.get("/api/libraries").json()["libraries"] if l["id"] == lib_id)
        assert lib_data["counts"]["files"] == 1
        assert lib_data["counts"]["movie"] == 1


def test_tree_folder_course_api():
    app = create_app()
    with TestClient(app) as client:
        # 登录
        login = client.post("/api/auth/login", json={"username": "admin", "password": "S3cure-passphrase"})
        assert login.status_code == 200

        course_dir = MEDIA / "Baidu_Course"
        make("Baidu_Course/09.2027Kira/01.高等数学/01.导学课/[1]--开班仪式.strm")
        make("Baidu_Course/09.2027Kira/01.高等数学/01.导学课/[2]--班会.strm")

        lib_res = client.post(
            "/api/libraries",
            json={"name": "我的课程", "type": "course", "root_path": str(course_dir)},
        )
        assert lib_res.status_code == 201
        lib_id = lib_res.json()["id"]

        scan = client.post(f"/api/libraries/{lib_id}/scan")
        assert scan.status_code == 200
        wait_task(client, scan.json()["task_id"])

        # 根目录：只看到 09.2027Kira 文件夹
        root_items = client.get(f"/api/items?library_id={lib_id}&parent_id=root").json()
        assert len(root_items["items"]) == 1
        kira = root_items["items"][0]
        assert kira["kind"] == "folder"
        assert kira["title"] == "09.2027Kira"

        # 详情获取 09.2027Kira
        kira_detail = client.get(f"/api/items/{kira['id']}").json()
        assert len(kira_detail["folders"]) == 1
        math_folder = kira_detail["folders"][0]
        assert math_folder["title"] == "01.高等数学"

        # 详情获取 01.高等数学
        math_detail = client.get(f"/api/items/{math_folder['id']}").json()
        assert len(math_detail["folders"]) == 1
        intro_folder = math_detail["folders"][0]
        assert intro_folder["title"] == "01.导学课"

        # 详情获取 01.导学课
        intro_detail = client.get(f"/api/items/{intro_folder['id']}").json()
        assert len(intro_detail["folders"]) == 0
        assert len(intro_detail["videos"]) == 2
        assert intro_detail["videos"][0]["title"] == "[1]--开班仪式"
        assert intro_detail["videos"][1]["title"] == "[2]--班会"
        assert intro_detail["videos"][0]["episode_no"] is None
        assert len(intro_detail["ancestors"]) == 2
        assert intro_detail["ancestors"][0]["title"] == "09.2027Kira"
        assert intro_detail["ancestors"][1]["title"] == "01.高等数学"

        # 播放文件夹 intro_folder，自动定位到第 1 集并生成包含同目录下视频的播放列表
        play_res = client.post(f"/api/play/{intro_folder['id']}", json={"mode": "auto"}).json()
        assert play_res["item_id"] == intro_detail["videos"][0]["id"]
        assert len(play_res["playlist"]) == 2
        assert play_res["playlist"][0]["title"] == "[1]--开班仪式"
        assert play_res["playlist"][1]["title"] == "[2]--班会"
        assert play_res["next_item_id"] == intro_detail["videos"][1]["id"]

        # 删除带有层级目录与视频的课程媒体库，验证外键约束不会报错
        del_res = client.delete(f"/api/libraries/{lib_id}")
        assert del_res.status_code == 204
        assert client.get(f"/api/libraries/{lib_id}").status_code == 404


def test_poster_play_target_selection():
    """测试海报图点击播放的目标决策：
    1. 优先续播处于「继续播放」中最后播放的一集（即便跳集观看）；
    2. 从「继续观看」移除后，再次点击海报播放，重新从第 1 集从头播放（resume_ms=0）；
    3. 全剧所有集数均已看完后，再次点击海报播放，重新从第 1 集播放（而不是停在最后一集）。
    """
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "S3cure-passphrase"},
        )
        libs = client.get("/api/libraries").json()["libraries"]
        tv_lib = next(l for l in libs if l["type"] == "tv")
        items = client.get("/api/items", params={"library_id": tv_lib["id"]}).json()["items"]
        series = next(i for i in items if i["title"] == "三体")
        detail = client.get(f"/api/items/{series['id']}").json()
        episodes = detail["seasons"][0]["episodes"]
        assert len(episodes) >= 2
        ep0, ep1 = episodes[0], episodes[1]

        # 1. 模拟跳集观看：第 1 集未看，第 2 集看了一半（产生有效继续播放进度）
        client.post(f"/api/items/{ep0['id']}/watched", json={"finished": False})
        res1 = client.post(
            f"/api/items/{ep1['id']}/progress",
            json={"position_ms": 45000, "duration_ms": 120000, "finished": False},
        )
        assert res1.status_code == 200

        # 点击剧集海报播放，必须精准返回正在继续播放的 ep1，且 resume_ms 为 45000
        play1 = client.post(f"/api/play/{series['id']}", json={}).json()
        assert play1["item_id"] == ep1["id"]
        assert play1["resume_ms"] == 45000

        # 详情页下发的 play_target_id 同样应精准指向 ep1
        detail1 = client.get(f"/api/items/{series['id']}").json()
        assert detail1["item"]["play_target_id"] == ep1["id"]

        # 2. 从「继续观看」移除（dismiss）
        dismiss = client.delete(f"/api/items/{ep1['id']}/continue")
        assert dismiss.status_code == 200

        # 移除后，再次点击海报播放，因为没有处于「继续播放」的有效记录，必须从第一集从头播放
        play2 = client.post(f"/api/play/{series['id']}", json={}).json()
        assert play2["item_id"] == ep0["id"]
        assert play2["resume_ms"] == 0

        # 3. 全剧看完全部集数（ep0 和 ep1 均已看完）
        client.post(f"/api/items/{ep0['id']}/watched", json={"finished": True})
        client.post(f"/api/items/{ep1['id']}/watched", json={"finished": True})

        # 全剧看完后，点击海报播放，必须从第 1 集重新播放（而不是旧逻辑的最后一集）
        play3 = client.post(f"/api/play/{series['id']}", json={}).json()
        assert play3["item_id"] == ep0["id"]
        assert play3["resume_ms"] == 0






