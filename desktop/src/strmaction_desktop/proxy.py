"""Local loopback HTTP streaming proxy for in-process media playback.

Handles custom headers (User-Agent, Referer, Cookies, Tokens) and preserves
them across 302/301 redirects when streaming from CDNs or Alist/Baidu Wangpan.
"""

from __future__ import annotations

import logging
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024  # 64 KB


class _PreservingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP redirect handler that preserves custom headers like User-Agent and Referer."""

    def __init__(self, custom_headers: dict[str, str]):
        super().__init__()
        self._custom_headers = custom_headers

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            for k, v in self._custom_headers.items():
                new_req.add_header(k, v)
        return new_req


class StreamSession:
    def __init__(self, stream_id: str, upstream_url: str, headers: Mapping[str, str]):
        self.stream_id = stream_id
        self.upstream_url = upstream_url
        self.headers = dict(headers)


class LocalStreamingProxy:
    """Lightweight in-process HTTP proxy running on 127.0.0.1."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._sessions: dict[str, StreamSession] = {}
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        if self._server:
            return self._server.server_address[1]
        return self._port

    def start(self) -> int:
        if self._server is not None:
            return self.port

        proxy_self = self

        class ProxyRequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # Suppress normal access log spam
                pass

            def do_HEAD(self):
                self._handle_proxy(head_only=True)

            def do_GET(self):
                self._handle_proxy(head_only=False)

            def _handle_proxy(self, head_only: bool = False):
                parsed = urllib.parse.urlparse(self.path)
                stream_id = parsed.path.lstrip("/").split("/")[0]

                session = proxy_self.get_session(stream_id)
                if not session:
                    self.send_error(404, "Stream not found")
                    return

                # Build upstream request headers
                req_headers = dict(session.headers)
                if "Range" in self.headers:
                    req_headers["Range"] = self.headers["Range"]

                opener = urllib.request.build_opener(
                    _PreservingRedirectHandler(session.headers)
                )

                req = urllib.request.Request(
                    session.upstream_url,
                    headers=req_headers,
                    method="HEAD" if head_only else "GET",
                )

                try:
                    with opener.open(req, timeout=15) as resp:
                        status_code = resp.status
                        self.send_response(status_code)

                        # Forward relevant headers
                        for hdr in [
                            "Content-Type",
                            "Content-Length",
                            "Content-Range",
                            "Accept-Ranges",
                            "Last-Modified",
                            "ETag",
                        ]:
                            val = resp.headers.get(hdr)
                            if val:
                                self.send_header(hdr, val)
                        self.end_headers()

                        if head_only:
                            return

                        while True:
                            chunk = resp.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    # Client stopped or seeked away; normal behavior
                    pass
                except urllib.error.HTTPError as exc:
                    try:
                        self.send_response(exc.code)
                        self.end_headers()
                    except Exception:
                        pass
                except Exception as exc:
                    logger.debug("Proxy stream error: %s", exc)
                    try:
                        self.send_error(502, f"Upstream error: {exc}")
                    except Exception:
                        pass

        self._server = ThreadingHTTPServer((self.host, self._port), ProxyRequestHandler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="strmaction-streaming-proxy",
            daemon=True,
        )
        self._server_thread.start()
        logger.info("Local streaming proxy started at http://%s:%d", self.host, self.port)
        return self.port

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._server_thread = None
            logger.info("Local streaming proxy stopped")

    def register_stream(
        self,
        stream_id: str,
        upstream_url: str,
        headers: Mapping[str, str],
    ) -> str:
        """Register an upstream stream session and return its local loopback URL."""
        self.start()
        with self._lock:
            self._sessions[stream_id] = StreamSession(stream_id, upstream_url, headers)
        return f"http://{self.host}:{self.port}/{stream_id}"

    def unregister_stream(self, stream_id: str) -> None:
        with self._lock:
            self._sessions.pop(stream_id, None)

    def get_session(self, stream_id: str) -> StreamSession | None:
        with self._lock:
            return self._sessions.get(stream_id)


# Global singleton instance
_global_proxy: LocalStreamingProxy | None = None
_proxy_lock = threading.Lock()


def get_proxy() -> LocalStreamingProxy:
    global _global_proxy
    with _proxy_lock:
        if _global_proxy is None:
            _global_proxy = LocalStreamingProxy()
            _global_proxy.start()
        return _global_proxy
