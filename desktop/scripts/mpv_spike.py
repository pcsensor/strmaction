"""Render spike: does mpv paint into a QOpenGLWidget, and do widgets stack?

Temporary verification harness for the libmpv migration.  It answers the three
questions the whole migration rests on:

1. does mpv render at all through MpvRenderContext
2. does Qt composite that FBO into the window (window.grab() is not black)
3. does a widget placed above the video stay visible (the original bug)

    python scripts/mpv_spike.py [out.png]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from strmaction_desktop.player.mpv_engine import (  # noqa: E402
    MpvEngine,
    MpvVideoWidget,
)
from strmaction_desktop.player.mpv_loader import is_available  # noqa: E402

SOURCE = "av://lavfi:testsrc2=size=640x360:rate=30"
STRIP_HEIGHT = 120


class RedOverlay(QWidget):
    """Semi-transparent strip standing in for the playback controls."""

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(255, 0, 0, 170))


def sample(image, top: int, bottom: int) -> tuple[float, float, float]:
    """Average RGB over a horizontal band."""
    r = g = b = 0.0
    count = 0
    step = max(1, image.width() // 60)
    for y in range(top, bottom, step):
        for x in range(0, image.width(), step):
            colour = image.pixelColor(x, y)
            r += colour.red()
            g += colour.green()
            b += colour.blue()
            count += 1
    if not count:
        return 0.0, 0.0, 0.0
    return r / count, g / count, b / count


def main() -> int:
    if not is_available():
        print("FAIL: libmpv 不可用")
        return 2

    # The widget requests its own GL format; no global default (breaks
    # QtWebEngine in the real app).
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.resize(960, 540)

    engine = MpvEngine()
    widget = MpvVideoWidget(engine)
    engine.set_video_output(widget)
    window.setCentralWidget(widget)
    window.show()

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("mpv_spike.png")
    state: dict[str, object] = {}

    def start_playback() -> None:
        # With vo=libmpv, mpv cannot open anything until a render context is
        # attached, and that only happens once the GL context exists.
        widget.grabFramebuffer()
        state["render_ctx"] = engine._rendering
        engine.load_media(SOURCE)

    def add_overlay() -> None:
        state["duration"] = engine.duration
        state["position"] = engine.position
        overlay = RedOverlay(widget)
        overlay.setGeometry(0, 0, widget.width(), STRIP_HEIGHT)
        overlay.show()
        overlay.raise_()
        state["overlay"] = overlay

    def finish() -> None:
        image = window.grab().toImage()
        image.save(str(out))

        band = sample(image, 10, STRIP_HEIGHT - 10)
        below = sample(image, STRIP_HEIGHT + 40, min(image.height() - 10, STRIP_HEIGHT + 220))
        video_only = widget.grabFramebuffer()

        print(f"渲染上下文      : {'已建立' if state.get('render_ctx') else '未建立'}")
        print(f"窗口截图        : {image.width()}x{image.height()} -> {out}")
        print(f"控件区平均 RGB  : {band[0]:.0f}, {band[1]:.0f}, {band[2]:.0f}")
        print(f"视频区平均 RGB  : {below[0]:.0f}, {below[1]:.0f}, {below[2]:.0f}")
        print(f"时长 / 位置(秒) : {state.get('duration')} / {state.get('position')}")
        print(f"视频帧尺寸      : {video_only.width()}x{video_only.height()}")

        controls_visible = band[0] > band[1] + 40 and band[0] > band[2] + 40
        video_composited = below[0] + below[1] + below[2] > 60
        print(f"控件可见        : {'是' if controls_visible else '否'}")
        print(f"Qt 合成视频     : {'是' if video_composited else '否'}")
        if controls_visible and video_composited:
            print("结论            : 通过——控件叠加在视频之上且正常显示")
            state["code"] = 0
        else:
            print("结论            : 未通过")
            state["code"] = 1
        app.quit()

    QTimer.singleShot(400, start_playback)
    QTimer.singleShot(3400, add_overlay)
    QTimer.singleShot(4000, finish)
    app.exec()

    engine.shutdown()
    return int(state.get("code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
