"""Tests for the libmpv glue.

No real mpv instance is created here: the suite runs with
STRMACTION_DISABLE_MPV=1 (see conftest.py).  What is covered is the logic that
has actually bitten us — header formatting, error mapping, library discovery
and the disable switch.
"""

from __future__ import annotations

import os

import pytest

from strmaction_desktop.player import mpv_loader
from strmaction_desktop.player.mpv_engine import (
    _format_headers,
    _friendly_error,
    _parse_buffered_ranges,
    _parse_network_speed,
)


# -- library discovery ---------------------------------------------------
def test_library_names_are_platform_specific():
    names = mpv_loader.library_names()
    assert names
    assert all(name.startswith(("libmpv", "mpv")) for name in names)


def test_platform_dir_is_namespaced():
    directory = mpv_loader._platform_dir()
    assert "-" in directory
    assert "/" not in directory and "\\" not in directory


def test_explicit_env_file_wins(tmp_path, monkeypatch):
    fake = tmp_path / "libmpv-2.dll"
    fake.write_bytes(b"not a real library")
    monkeypatch.setenv("STRMACTION_LIBMPV", str(fake))
    assert mpv_loader.find_library() == fake


def test_env_dir_is_searched(tmp_path, monkeypatch):
    monkeypatch.delenv("STRMACTION_LIBMPV", raising=False)
    name = mpv_loader.library_names()[0]
    (tmp_path / name).write_bytes(b"stub")
    monkeypatch.setenv("STRMACTION_LIBMPV_DIR", str(tmp_path))
    assert mpv_loader.find_library() == tmp_path / name


def test_disable_switch_forces_fallback(monkeypatch):
    monkeypatch.setenv("STRMACTION_DISABLE_MPV", "1")
    mpv_loader.reset_cache()
    assert mpv_loader.is_available() is False
    mpv_loader.reset_cache()


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_disable_values(monkeypatch, value):
    monkeypatch.setenv("STRMACTION_DISABLE_MPV", value)
    assert mpv_loader._disabled() is True


def test_disable_off_by_default(monkeypatch):
    monkeypatch.delenv("STRMACTION_DISABLE_MPV", raising=False)
    assert mpv_loader._disabled() is False


# -- header formatting ---------------------------------------------------
def test_format_headers_joins_entries():
    result = _format_headers(
        {"User-Agent": "pan.baidu.com", "Referer": "https://pan.baidu.com/"}
    )
    assert result == "User-Agent: pan.baidu.com,Referer: https://pan.baidu.com/"


def test_format_headers_drops_entries_that_break_the_grammar():
    # A comma or colon inside the *name* would corrupt mpv's option syntax.
    assert _format_headers({"Bad,Key": "x", "Good": "y"}) == "Good: y"
    assert _format_headers({"Bad:Key": "x"}) == ""


def test_format_headers_skips_blank_values():
    assert _format_headers({"Empty": "   ", "Ok": "1"}) == "Ok: 1"


def test_format_headers_empty():
    assert _format_headers({}) == ""


# -- error mapping -------------------------------------------------------
@pytest.mark.parametrize(
    "code,fragment",
    [
        (-13, "无法打开片源"),
        (-17, "格式不受支持"),
        (-16, "可播放的音视频轨道"),
        (-15, "视频输出"),
        (-14, "音频设备"),
    ],
)
def test_friendly_error_maps_known_codes(code, fragment):
    assert fragment in _friendly_error(code)


@pytest.mark.parametrize("code", [-999, None, "nonsense"])
def test_friendly_error_falls_back(code):
    assert _friendly_error(code) == "播放失败，请查看日志或稍后重试"


# -- cache state ----------------------------------------------------------
def test_parse_buffered_ranges_uses_seekable_ranges():
    state = {
        "seekable-ranges": [
            {"start": 30.0, "end": 60.0},
            {"start": 5.0, "end": 20.0},
            {"start": 18.0, "end": 25.0},
        ]
    }
    assert _parse_buffered_ranges(state) == [(5.0, 25.0), (30.0, 60.0)]


def test_parse_buffered_ranges_falls_back_to_reader_and_cache_end():
    state = {"reader-pts": 12.5, "cache-end": 42.0}
    assert _parse_buffered_ranges(state) == [(12.5, 42.0)]


def test_parse_buffered_ranges_derives_start_from_cache_duration():
    state = {"cache-end": 42.0, "cache-duration": 10.0}
    assert _parse_buffered_ranges(state) == [(32.0, 42.0)]


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"seekable-ranges": [{"start": None, "end": 4.0}]},
        {"seekable-ranges": [{"start": 5.0, "end": 4.0}]},
        {"seekable-ranges": "not-a-list"},
        {"reader-pts": 9.0},
    ],
)
def test_parse_buffered_ranges_ignores_unusable_state(state):
    assert _parse_buffered_ranges(state) == []


def test_parse_network_speed_reads_raw_input_rate():
    assert _parse_network_speed({"raw-input-rate": 123456}) == 123456.0
    assert _parse_network_speed({"raw-input-rate": 0}) == 0.0


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"raw-input-rate": None},
        {"raw-input-rate": -1},
        {"raw-input-rate": "bad"},
    ],
)
def test_parse_network_speed_ignores_unavailable_values(state):
    assert _parse_network_speed(state) is None


def test_apply_cache_state_emits_only_changed_ranges():
    from unittest.mock import MagicMock
    from strmaction_desktop.player.mpv_engine import MpvEngine

    engine = MpvEngine.__new__(MpvEngine)
    engine._mpv = MagicMock()
    engine._buffered_ranges = []
    engine._network_speed = None
    engine.buffered_ranges_changed = MagicMock()
    engine.network_speed_changed = MagicMock()

    state = {
        "seekable-ranges": [{"start": 10.0, "end": 30.0}],
        "raw-input-rate": 2 * 1024 * 1024,
    }
    engine._apply_cache_state(state)
    engine.buffered_ranges_changed.emit.assert_called_once_with([(10.0, 30.0)])
    engine.network_speed_changed.emit.assert_called_once_with(2 * 1024 * 1024)

    # Repeating the same values must not repaint the seekbar or the label.
    engine._apply_cache_state(state)
    engine.buffered_ranges_changed.emit.assert_called_once()
    engine.network_speed_changed.emit.assert_called_once()


def test_load_media_with_resume_position():
    from unittest.mock import MagicMock
    from strmaction_desktop.player.mpv_engine import MpvEngine

    engine = MpvEngine.__new__(MpvEngine)
    engine._mpv = MagicMock()
    engine._current_headers = {}
    engine.load_media("https://example.com/test.mkv", start_ms=22153)

    engine._mpv.command.assert_called_once_with(
        "loadfile", "https://example.com/test.mkv", "replace", -1, "start=22.153"
    )


def test_load_media_start_from_beginning():
    from unittest.mock import MagicMock
    from strmaction_desktop.player.mpv_engine import MpvEngine

    engine = MpvEngine.__new__(MpvEngine)
    engine._mpv = MagicMock()
    engine._current_headers = {}
    engine.load_media("https://example.com/test.mkv", start_ms=0)

    engine._mpv.command.assert_called_once_with(
        "loadfile", "https://example.com/test.mkv", "replace"
    )


# -- render pacing --------------------------------------------------------
def _render_engine(block: bool = False):
    from unittest.mock import MagicMock
    from strmaction_desktop.player.mpv_engine import MpvEngine

    engine = MpvEngine.__new__(MpvEngine)
    engine._render_ctx = MagicMock()
    engine._block_for_target_time = block
    return engine


def test_render_uses_non_blocking_target_time():
    engine = _render_engine()
    assert engine.render(640, 360, 3) is True
    engine._render_ctx.render.assert_called_once_with(
        flip_y=True,
        opengl_fbo={"w": 640, "h": 360, "fbo": 3},
        block_for_target_time=0,
    )


def test_render_blocking_fallback_omits_target_time():
    engine = _render_engine(block=True)
    engine.render(640, 360, 3)
    kwargs = engine._render_ctx.render.call_args.kwargs
    assert "block_for_target_time" not in kwargs


def test_consume_frame_update_reports_new_frame():
    engine = _render_engine()
    engine._render_ctx.update.return_value = False
    assert engine.consume_frame_update() is False

    engine._render_ctx.update.return_value = True
    assert engine.consume_frame_update() is True


def test_report_swap_is_forwarded():
    engine = _render_engine()
    engine.report_swap()
    engine._render_ctx.report_swap.assert_called_once_with()


def test_video_widget_skips_repaint_without_new_frame():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from strmaction_desktop.player.mpv_engine import MpvVideoWidget

    widget_updates: list[bool] = []
    widget = SimpleNamespace(
        _engine=MagicMock(),
        _needs_render=False,
        update=lambda: widget_updates.append(True),
    )

    widget._engine.consume_frame_update.return_value = False
    MpvVideoWidget._request_update(widget)
    assert widget_updates == []
    assert widget._needs_render is False

    widget._engine.consume_frame_update.return_value = True
    MpvVideoWidget._request_update(widget)
    assert widget_updates == [True]
    assert widget._needs_render is True


def test_video_widget_reports_swap_only_after_render():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from strmaction_desktop.player.mpv_engine import MpvVideoWidget

    widget = SimpleNamespace(
        _engine=MagicMock(),
        _needs_render=True,
        _frame_rendered=False,
        devicePixelRatioF=lambda: 1.0,
        width=lambda: 640,
        height=lambda: 360,
        defaultFramebufferObject=lambda: 5,
    )
    widget._engine.render.return_value = True

    MpvVideoWidget.paintGL(widget)
    widget._engine.render.assert_called_once_with(640, 360, 5)
    assert widget._frame_rendered is True
    widget._engine.report_swap.assert_not_called()

    # A second overlay-only paint must not re-render the video.
    MpvVideoWidget.paintGL(widget)
    widget._engine.render.assert_called_once()

    MpvVideoWidget._on_frame_swapped(widget)
    widget._engine.report_swap.assert_called_once_with()
    assert widget._frame_rendered is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_block_render_env_flag(monkeypatch, value):
    from strmaction_desktop.player.mpv_engine import _BLOCK_RENDER_ENV, _env_flag

    monkeypatch.setenv(_BLOCK_RENDER_ENV, value)
    assert _env_flag(_BLOCK_RENDER_ENV) is True


def test_block_render_env_off_by_default(monkeypatch):
    from strmaction_desktop.player.mpv_engine import _BLOCK_RENDER_ENV, _env_flag

    monkeypatch.delenv(_BLOCK_RENDER_ENV, raising=False)
    assert _env_flag(_BLOCK_RENDER_ENV) is False
