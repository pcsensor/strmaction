"""StrmAction desktop shell.

The desktop client is a WebView shell around the existing StrmAction web UI.
Python only handles local mpv playback and progress reporting; it never stores
the account password or the web session cookie.
"""

from .version import __version__

APP_NAME = "StrmAction"

__all__ = ["APP_NAME", "__version__"]
