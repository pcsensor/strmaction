from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from strmaction_desktop.player.drawer import PlayerDrawer
from strmaction_desktop.player.keyboard import KeyboardHandler
from strmaction_desktop.player.seekbar import BufferedSeekBar, format_time


def _get_app():
    return QApplication.instance() or QApplication([])


def test_format_time():
    assert format_time(0) == "00:00"
    assert format_time(65) == "01:05"
    assert format_time(3600) == "01:00:00"
    assert format_time(3665) == "01:01:05"
    assert format_time(-10) == "00:00"


def test_keyboard_space_play_pause():
    _get_app()
    handler = KeyboardHandler()
    toggled = []
    handler.play_pause_toggled.connect(lambda: toggled.append(True))

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    handled = handler.handle_key_press(event)
    assert handled is True
    assert len(toggled) == 1

    # Auto repeat should be ignored
    event_repeat = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Space,
        Qt.KeyboardModifier.NoModifier,
        text=" ",
        autorep=True,
        count=1,
    )
    handler.handle_key_press(event_repeat)
    assert len(toggled) == 1


def test_keyboard_left_arrow_seek():
    _get_app()
    handler = KeyboardHandler()
    seeks = []
    handler.seek_relative.connect(lambda s: seeks.append(s))

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    handled = handler.handle_key_press(event)
    assert handled is True
    assert seeks == [-5.0]


def test_keyboard_right_arrow_click_seek():
    _get_app()
    handler = KeyboardHandler()
    seeks = []
    boost_start = []
    boost_end = []
    handler.seek_relative.connect(lambda s: seeks.append(s))
    handler.speed_boost_started.connect(lambda s: boost_start.append(s))
    handler.speed_boost_ended.connect(lambda: boost_end.append(True))

    # Press Right
    event_press = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    handler.handle_key_press(event_press)

    # Immediately release before 250ms timer
    event_release = QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    handler.handle_key_release(event_release)

    assert seeks == [5.0]
    assert len(boost_start) == 0
    assert len(boost_end) == 0


def test_keyboard_right_arrow_hold_speed_boost():
    _get_app()
    handler = KeyboardHandler()
    seeks = []
    boost_start = []
    boost_end = []
    handler.seek_relative.connect(lambda s: seeks.append(s))
    handler.speed_boost_started.connect(lambda s: boost_start.append(s))
    handler.speed_boost_ended.connect(lambda: boost_end.append(True))

    # Press Right
    event_press = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    handler.handle_key_press(event_press)

    # Simulate timer firing (holding > 250ms)
    handler._on_hold_timer_fired()
    assert boost_start == [2.0]
    assert len(seeks) == 0

    # Auto repeat keypress events while holding should be consumed
    event_rep = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Right,
        Qt.KeyboardModifier.NoModifier,
        autorep=True,
        count=1,
    )
    handler.handle_key_press(event_rep)
    assert len(seeks) == 0

    # Finally release
    event_release = QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    handler.handle_key_release(event_release)

    assert len(boost_end) == 1
    # No seek should be emitted after long press release
    assert len(seeks) == 0


def test_keyboard_volume_and_navigation():
    _get_app()
    handler = KeyboardHandler()
    volumes = []
    navs = []
    handler.volume_relative.connect(lambda v: volumes.append(v))
    handler.prev_episode_requested.connect(lambda: navs.append("prev"))
    handler.next_episode_requested.connect(lambda: navs.append("next"))

    handler.handle_key_press(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    handler.handle_key_press(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert volumes == [5, -5]

    handler.handle_key_press(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_BracketLeft, Qt.KeyboardModifier.NoModifier))
    handler.handle_key_press(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_BracketRight, Qt.KeyboardModifier.NoModifier))
    assert navs == ["prev", "next"]


def test_player_drawer_tabs_and_selection():
    _get_app()
    drawer = PlayerDrawer()
    selected_episodes = []
    selected_speeds = []
    drawer.episode_selected.connect(lambda eid: selected_episodes.append(eid))
    drawer.speed_selected.connect(lambda sp: selected_speeds.append(sp))

    drawer.set_data(
        playlist=[
            {"item_id": 101, "code": "E01", "title": "First", "current": True},
            {"item_id": 102, "code": "E02", "title": "Second", "current": False},
        ],
        current_item_id=101,
        current_speed=1.0,
    )

    # Drawer defaults to episodes tab when playlist > 1
    assert drawer._current_tab == "episodes"

    # Select second episode
    drawer._select_episode(102)
    assert selected_episodes == [102]

    # Switch to speed tab
    drawer.switch_tab("speed")
    assert drawer._current_tab == "speed"
    drawer._select_speed(1.5)
    assert selected_speeds == [1.5]


def test_player_drawer_backend_id_format():
    _get_app()
    drawer = PlayerDrawer()
    selected_episodes = []
    drawer.episode_selected.connect(lambda eid: selected_episodes.append(eid))

    # Backend sends "id" rather than "item_id"
    drawer.set_data(
        playlist=[
            {"id": 201, "code": "E01", "title": "Ep 1", "current": True},
            {"id": 202, "code": "E02", "title": "Ep 2", "current": False},
        ],
        current_item_id=201,
    )
    assert drawer._current_tab == "episodes"
    # 2 episode buttons + 1 trailing stretch
    assert drawer.content_vbox.count() == 3

    # Verify clicking episode button with "id" emits the ID
    drawer._select_episode(202)
    assert selected_episodes == [202]


def test_overlay_speed_badge_placement_and_transparency():
    _get_app()
    from strmaction_desktop.player.overlay import ControlsOverlay

    overlay = ControlsOverlay()
    # speed_badge should be inside top_badge_container (anchored near top)
    assert overlay.speed_badge.parent() == overlay.top_badge_container
    # style should have 0.45 rgba transparency
    style = overlay.speed_badge.styleSheet()
    assert "rgba(0, 0, 0, 0.45)" in style
    assert overlay.top_badge_container.parent() == overlay


def test_overlay_mouse_move_throttling():
    _get_app()
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QPointF
    from strmaction_desktop.player.overlay import ControlsOverlay

    overlay = ControlsOverlay()
    overlay.show()
    overlay.show_controls()
    assert not overlay.top_bar.isHidden()

    # Move mouse event while controls are already visible
    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(100, 100),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mouseMoveEvent(event)
    assert not overlay.top_bar.isHidden()
    overlay.close()


def test_seekbar_buffer_progress_and_stability():
    _get_app()
    bar = BufferedSeekBar()
    bar.set_duration(100.0)

    # Setting buffer progress
    bar.set_buffer_progress(0.4)
    assert len(bar._buffered_ranges) == 1
    assert bar._buffered_ranges[0] == (0.0, 40.0)

    # During dragging, seeking does not abruptly wipe out existing buffer
    bar._is_dragging = True
    bar.set_buffer_end(0.0)
    assert bar._buffered_ranges[0] == (0.0, 40.0)

    bar._is_dragging = False
    bar.set_buffer_end(60.0)
    assert bar._buffered_ranges[0] == (0.0, 60.0)



def test_resume_seek_is_not_clamped_to_zero_before_duration_known():
    """Resume must survive load_media(): duration is 0 until the media loads."""
    _get_app()
    from strmaction_desktop.player.controller import QtPlayerController

    controller = QtPlayerController()
    controller.seek(600.0, relative=False)
    assert controller._pending_seek_ms == 600_000

    # Once the duration is known the seek is clamped to the media length.
    controller._duration_sec = 100.0
    controller.seek(600.0, relative=False)
    assert controller._pending_seek_ms == 600_000
    controller.stop()


def test_end_card_counts_down_and_autoplays():
    _get_app()
    from strmaction_desktop.player.endcard import MessageCard

    card = MessageCard()
    fired: list[bool] = []
    card.primary_clicked.connect(lambda: fired.append(True))
    card.show_message("播放结束", "下一集", primary="播放下一集", countdown=2)
    assert "2" in card.btn_primary.text()

    card._tick()
    assert "1" in card.btn_primary.text()
    assert fired == []

    card._tick()
    assert fired == [True]
    assert not card.isVisible()


def test_drawer_subtitle_track_zero_is_selectable():
    """Track id 0 is a real track and must not be treated as 'subtitles off'."""
    _get_app()
    from strmaction_desktop.player.drawer import PlayerDrawer

    drawer = PlayerDrawer()
    drawer.set_data(
        subtitles=[{"id": 0, "label": "简体中文"}],
        current_sid="no",
        subtitle_hint="片中无内嵌字幕",
    )
    selected: list = []
    drawer.subtitle_selected.connect(lambda sid: selected.append(sid))
    drawer.open_tab("tracks")
    buttons = [
        child
        for child in drawer.scroll_content.findChildren(type(drawer.btn_tab_episodes))
        if child.text() == "简体中文"
    ]
    assert buttons, "subtitle button should exist"
    buttons[0].click()
    assert selected == [0]
