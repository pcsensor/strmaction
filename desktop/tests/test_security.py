from __future__ import annotations

import pytest

from strmaction_desktop.security import (
    PayloadError,
    parse_payload,
    redact_headers,
    redact_url,
)


def _payload(**overrides):
    payload = {
        "item_id": 42,
        "play_url": "https://pan.example.com/video.m3u8",
        "headers": {
            "User-Agent": "pan.baidu.com",
            "Referer": "https://pan.baidu.com/",
        },
        "play_token": "pt_abcdefghijklmnopqrstuvwxyz123456",
        "resume_ms": 12000,
        "progress_interval_ms": 5000,
        "subtitles": [
            {"label": "简体", "url": "/api/items/42/subtitles/0?pt=pt_abcdefghijklmnopqrstuvwxyz123456"}
        ],
        "title": "测试影片",
    }
    payload.update(overrides)
    return payload


def test_parse_payload_and_absolute_subtitles():
    parsed = parse_payload(_payload(), "https://media.example.com/")
    assert parsed.item_id == 42
    assert parsed.headers["User-Agent"] == "pan.baidu.com"
    assert parsed.resume_ms == 12000
    assert parsed.subtitles[0].url.startswith("https://media.example.com/api/items/42/")
    assert parsed.title == "测试影片"


def test_parse_payload_rejects_bad_urls_and_headers():
    with pytest.raises(PayloadError):
        parse_payload(_payload(play_url="file:///etc/passwd"), "https://media.example.com")
    with pytest.raises(PayloadError):
        parse_payload(_payload(item_id=0), "https://media.example.com")
    with pytest.raises(PayloadError):
        parse_payload(
            _payload(headers={"X-Test": "a\r\nInjected: 1"}),
            "https://media.example.com",
        )
    with pytest.raises(PayloadError):
        parse_payload(_payload(play_token="short"), "https://media.example.com")


def test_parse_payload_clamps_interval():
    parsed = parse_payload(
        _payload(progress_interval_ms=10), "https://media.example.com"
    )
    assert parsed.progress_interval_ms == 2000
    parsed = parse_payload(
        _payload(progress_interval_ms=999999), "https://media.example.com"
    )
    assert parsed.progress_interval_ms == 60000


def test_redaction():
    assert redact_url("https://pan.example.com/secret?token=1") == "https://pan.example.com/***"
    assert redact_url("not-a-url") == "<invalid-url>"
    assert redact_headers({"Authorization": "secret", "Referer": "x"}) == {
        "Authorization": "***",
        "Referer": "***",
    }
