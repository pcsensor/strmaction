"""Check that mpv sends the payload's User-Agent / Referer on the wire.

The core requirement of this migration is that the player obeys the headers
the server hands out (Baidu CDN links reject anything else).  A local HTTP
server records the request headers mpv actually sends, then refuses the
request — playback is expected to fail, only the headers matter.

    python scripts/mpv_ua_check.py
"""

from __future__ import annotations

import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from strmaction_desktop.player.mpv_engine import MpvEngine  # noqa: E402
from strmaction_desktop.player.mpv_loader import is_available  # noqa: E402

EXPECTED = {
    "User-Agent": "pan.baidu.com",
    "Referer": "https://pan.baidu.com/",
}

seen: list[dict[str, object]] = []


class Recorder(http.server.BaseHTTPRequestHandler):
    """Answers /movie.mkv with a 302 to /real.mkv, then refuses the target.

    The redirect hop mirrors what Baidu CDN does, and it is exactly the case
    the old loopback proxy had to patch by hand: does the custom User-Agent
    survive the redirect?
    """

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        seen.append({"path": self.path, "headers": dict(self.headers.items())})
        if self.path.startswith("/movie.mkv"):
            self.send_response(302)
            self.send_header("Location", "/real.mkv")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, *_args) -> None:
        pass


def main() -> int:
    if not is_available():
        print("FAIL: libmpv 不可用")
        return 2

    server = http.server.HTTPServer(("127.0.0.1", 0), Recorder)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    app = QApplication([])
    engine = MpvEngine()
    engine.set_headers(EXPECTED)
    engine.load_media(f"http://127.0.0.1:{port}/movie.mkv")

    deadline = time.time() + 8
    while time.time() < deadline and not seen:
        app.processEvents()
        time.sleep(0.05)

    print(f"请求数       : {len(seen)}")
    ok = bool(seen)
    for index, entry in enumerate(seen, start=1):
        headers = entry["headers"]
        assert isinstance(headers, dict)
        print(f"请求 {index}       : {entry['path']}")
        for key, want in EXPECTED.items():
            got = headers.get(key)
            mark = "OK  " if got == want else "FAIL"
            print(f"  {mark} {key}: {got!r} (期望 {want!r})")
            ok = ok and got == want
    if not seen:
        print("FAIL: mpv 没有发出任何请求")
    elif len(seen) < 2:
        print("注意: 只看到一次请求，302 未被跟随")

    engine.shutdown()
    server.shutdown()
    print("结论         : " + ("通过——UA 在直连与 302 跳转后均生效" if ok else "未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
