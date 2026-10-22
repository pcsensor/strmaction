"""Shared pytest configuration for the desktop shell.

Playback tests must not spin up a real libmpv instance: that would need an
audio device, a GPU context and decode threads in CI.  The suite therefore
runs against the Qt Multimedia fallback by default; tests that specifically
exercise mpv opt in by clearing the variable themselves.
"""

from __future__ import annotations

import os

# Set before any player module is imported.
os.environ["STRMACTION_DISABLE_MPV"] = "1"
