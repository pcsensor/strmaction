from __future__ import annotations

import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from strmaction_desktop.proxy import LocalStreamingProxy, get_proxy
from strmaction_desktop.player.controller import QtPlayerController
from PySide6.QtWidgets import QApplication


def _get_app():
    return QApplication.instance() or QApplication([])


class DummyOriginHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        # Check for redirect test
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/content")
            self.end_headers()
            return

        if self.path == "/content":
            # Echo back user-agent header
            ua = self.headers.get("User-Agent", "")
            body = f"OK:{ua}".encode("utf-8")

            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                # Simple range support
                self.send_response(206)
                self.send_header("Content-Range", f"bytes 0-1/{len(body)}")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(body[:2])
                return

            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "video/mp4")
            self.end_headers()
            self.wfile.write(body)


def test_proxy_streaming_and_redirects():
    # Start mock origin server
    origin = ThreadingHTTPServer(("127.0.0.1", 0), DummyOriginHandler)
    origin_port = origin.server_address[1]
    origin_thread = threading.Thread(target=origin.serve_forever, daemon=True)
    origin_thread.start()

    try:
        proxy = LocalStreamingProxy()
        proxy.start()

        upstream_url = f"http://127.0.0.1:{origin_port}/redirect"
        custom_headers = {"User-Agent": "StrmActionTest/1.0"}
        local_url = proxy.register_stream("test_stream_1", upstream_url, custom_headers)

        assert local_url.startswith(f"http://127.0.0.1:{proxy.port}/test_stream_1")

        # Request through proxy
        req = urllib.request.Request(local_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8")
            assert data == "OK:StrmActionTest/1.0"

        # Test Range request
        req_range = urllib.request.Request(local_url, headers={"Range": "bytes=0-1"})
        with urllib.request.urlopen(req_range, timeout=5) as resp:
            assert resp.status == 206
            data = resp.read().decode("utf-8")
            assert data == "OK"

        proxy.unregister_stream("test_stream_1")
        assert proxy.get_session("test_stream_1") is None

        proxy.stop()
    finally:
        origin.shutdown()
        origin.server_close()


def test_qt_player_controller():
    _get_app()
    ctrl = QtPlayerController()

    speeds = []
    ctrl.speed_changed.connect(lambda s: speeds.append(s))
    ctrl.set_speed(1.5)
    assert speeds == [1.5]

    ctrl.seek(10.0)
    ctrl.set_volume_relative(-10)
    ctrl.stop()
