from __future__ import annotations

import pytest

from app.parser import parse_path
from app.text import normalize_title


@pytest.mark.parametrize(
    "rel,title,year,season,episode,version",
    [
        ("流浪地球2 (2023)/流浪地球2 (2023).strm", "流浪地球2", 2023, None, None, None),
        ("沙丘2 (2024)/沙丘2 (2024) - 2160p.strm", "沙丘2", 2024, None, None, "2160p"),
        ("沙丘2 (2024)/沙丘2 (2024) - 1080p.strm", "沙丘2", 2024, None, None, "1080p"),
        ("奥本海默 （2023）/奥本海默 （2023）.strm", "奥本海默", 2023, None, None, None),
        ("无名/无名.strm", "无名", None, None, None, None),
    ],
)
def test_movie_matrix(rel, title, year, season, episode, version):
    parsed = parse_path("movie", rel)
    assert parsed.kind == "movie"
    assert parsed.title == title
    assert parsed.year == year
    assert parsed.season == season
    assert parsed.episode == episode
    assert parsed.version == version
    assert parsed.confidence >= 0.75


@pytest.mark.parametrize(
    "rel,series,year,season,episode,confidence",
    [
        ("三体 (2023)/Season 01/三体 - S01E01.strm", "三体", 2023, 1, 1, 0.9),
        ("漫长的季节 (2023)/S01/漫长的季节.01.strm", "漫长的季节", 2023, 1, 1, 0.84),
        (
            "Some.Show.2020/Season 02/Some.Show.S02E03.1080p.strm",
            "Some Show",
            2020,
            2,
            3,
            0.9,
        ),
        ("狂飙/第一季/第12集.strm", "狂飙", None, 1, 12, 0.92),
        ("进击的巨人 (2013)/Season 01/进击的巨人 - S01E01.strm", "进击的巨人", 2013, 1, 1, 0.9),
        ("三体 (2023)/01.strm", "三体", 2023, 1, 1, 0.8),
        ("Some.Show.S01E01.1080p.WEB-DL.strm", "Some Show", None, 1, 1, 0.8),
    ],
)
def test_tv_matrix(rel, series, year, season, episode, confidence):
    parsed = parse_path("tv", rel)
    assert parsed.kind == "episode", rel
    assert parsed.title == f"第{episode}集"
    assert parsed.group_title == series
    assert parsed.year == year
    assert parsed.season == season
    assert parsed.episode == episode
    assert parsed.confidence >= confidence - 0.001


def test_home_and_course():
    home = parse_path("home", "2024-06-01 生日/VID_20240601.mp4.strm")
    assert home.kind == "video"
    assert home.group_title == "2024-06-01 生日"
    assert home.title == "VID 20240601"

    course = parse_path("course", "Rust 实战/01 所有权/01 所有权.strm")
    assert course.kind == "video"
    assert course.group_title == "Rust 实战"
    assert course.chapter_title == "所有权"
    assert course.season == 1
    assert course.episode == 1
    assert course.title == "所有权"


def test_explicit_ids_and_parts():
    parsed = parse_path("movie", "黑客帝国 (1999) {tmdb-603}/黑客帝国 (1999) - CD1.strm")
    assert parsed.explicit_ids.get("tmdb") == "603"
    assert parsed.part == 1
    assert parsed.title == "黑客帝国"

    parsed = parse_path("movie", "电影 (2023) {imdb-tt0133093}/电影 (2023) - part2.strm")
    assert parsed.explicit_ids.get("imdb") == "tt0133093"
    assert parsed.part == 2


def test_custom_template():
    parsed = parse_path(
        "tv",
        "三体/第1季/三体.S01E05.strm",
        template="{title}/第{season}季/{title}.S{season:02d}E{episode:02d}.strm",
    )
    assert parsed.parser == "template"
    assert parsed.kind == "episode"
    assert parsed.group_title == "三体"
    assert parsed.season == 1
    assert parsed.episode == 5


def test_tv_orphan_file_becomes_video():
    parsed = parse_path("tv", "README.strm")
    assert parsed.kind == "video"
    assert parsed.title == "README"


def test_normalize_title():
    assert normalize_title("三体 (2023)") == normalize_title("三体")
    assert normalize_title("进击的巨人 第一季") == normalize_title("进击的巨人")
    assert normalize_title("ＳＯＭＥ　ＳＨＯＷ") == "someshow"
