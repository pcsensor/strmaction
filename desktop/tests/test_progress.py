from __future__ import annotations

import json

import httpx

from strmaction_desktop.progress import ProgressReporter


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_flush_payload_and_finished_threshold():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer pt_")
        assert request.url.path == "/api/items/42/progress"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    reporter = ProgressReporter(
        "https://media.example.com",
        42,
        "pt_abcdefghijklmnopqrstuvwxyz123456",
        5000,
        client=client,
    )
    reporter.update(120_000, 3_600_000)
    assert reporter.flush_once(force=True) is True
    assert seen[0]["position_ms"] == 120_000
    assert seen[0]["duration_ms"] == 3_600_000
    assert seen[0]["finished"] is False
    assert seen[0]["client_key"].startswith("desktop-")

    reporter.update(3_500_000, 3_600_000)
    assert reporter.flush_once(force=True) is True
    assert seen[1]["finished"] is True
    assert seen[1]["position_ms"] == 0
    assert seen[0]["client_key"] != seen[1]["client_key"]
    client.close()


def test_flush_keeps_latest_and_retries_after_server_error():
    calls = {"count": 0}
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        seen.append(json.loads(request.content))
        if calls["count"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    reporter = ProgressReporter(
        "https://media.example.com",
        42,
        "pt_abcdefghijklmnopqrstuvwxyz123456",
        5000,
        client=client,
    )
    reporter.update(10_000, 100_000)
    assert reporter.flush_once(force=True) is False
    reporter.update(20_000, 100_000)
    assert reporter.flush_once(force=True) is True
    assert seen[-1]["position_ms"] == 20_000
    client.close()


def test_auth_error_stops_reporting():
    errors: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "PLAY_TOKEN_EXPIRED"}})

    client = _client(handler)
    reporter = ProgressReporter(
        "https://media.example.com",
        42,
        "pt_abcdefghijklmnopqrstuvwxyz123456",
        5000,
        client=client,
        on_auth_error=lambda: errors.append(True),
    )
    reporter.update(10_000, 100_000)
    assert reporter.flush_once(force=True) is False
    assert reporter.auth_failed is True
    assert errors == [True]
    assert reporter.flush_once(force=True) is False
    client.close()
