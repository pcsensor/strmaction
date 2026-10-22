"""Embedded Player UI package modeled after the Android companion app."""

from .view import PlayerView
from .overlay import ControlsOverlay
from .seekbar import BufferedSeekBar
from .drawer import PlayerDrawer
from .keyboard import KeyboardHandler

__all__ = [
    "PlayerView",
    "ControlsOverlay",
    "BufferedSeekBar",
    "PlayerDrawer",
    "KeyboardHandler",
]
