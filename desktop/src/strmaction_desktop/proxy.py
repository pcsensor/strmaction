"""Local loopback HTTP streaming proxy for in-process media playback.

Handles custom headers (User-Agent, Referer, Cookies, Tokens) and preserves
them across 302/301 redirects when streaming from CDNs or Alist/Baidu Wangpan.

Qt Multimedia cannot attach per-request headers to a media source, so the
player talks to this proxy instead and the proxy injects the headers the
strm payload was issued with.  TLS verification follows the desktop setting
``allow_self_signed_https`` because self-hosted Alist/CDN endpoints very often
use self-signed certificates.
"""

from __future__ import annotations

import logging
import mimetypes
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024  # 64 KB
UPSTREAM_TIMEOUT = 20.0
FORWARDED_RESPONSE_HEADERS = (
    "Content-Type",
    "Content-Length",
    "Content-Range",
    "Content-Encoding",
    "Accept-Ranges",
    "Last-Modified",
    "ETag",
    "Cache-Control",
)
# Passed to the upstream request so range seeking and conditional fetches keep
# working; without these Qt would receive the whole file for every seek.
FORWARDED_REQUEST_HEADERS = ("Range", "If-Range", "If-None-Match", "If-Modified-Since")
GENERIC_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}


def guess_content_type(url: str, upstream_type: str | None) -> str:
    """Prefer the upstream type, but fill in the extension when it is generic."""
    value = (upstream_type or "").strip()
    if value and value.split(";")[0].strip().lower() not in GENERIC_CONTENT_TYPES:
        return value
    path = urllib.parse.urlparse(url).path
    guessed, _ = mimetypes.guess_type(path)
    return guessed or value or "application/octet-stream"


class _PreservingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTP redirect handler that preserves custom headers like User-Agent and Referer."""

    def __init__(self, custom_headers: dict[str, str]):
        super().__init__()
        self._custom_headers = custom_headers

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            for key, value in self._custom_headers.items():
                new_req.add_unredirected_header(key, value)
        return new_req


class StreamSession:
    def __init__(self, stream_id: str, upstream_url: str, headers: Mapping[str, str]):
        self.stream_id = stream_id
        self.upstream_url = upstream_url
        self.headers = dict(headers)


class LocalStreamingProxy:
    """Lightweight in-process HTTP proxy running on 127.0.0.1."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, tls_verify: bool = True):
        self.host = host
        self._port = port
        self._tls_verify = tls_verify
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._sessions: dict[str, StreamSession] = {}
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        if self._server:
            return self._server.server_address[1]
        return self._port

    @property
    def tls_verify(self) -> bool:
        return self._tls_verify

    def set_tls_verify(self, verify: bool) -> None:
        """Switch certificate verification for upstream fetches.

        Called when the desktop setting changes so users do not need to restart
        StrmAction after enabling "allow self-signed HTTPS".
        """
        self._tls_verify = bool(verify)

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._tls_verify:
            # None lets urllib use its default (verifying) context.
            return None
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def _opener(self, headers: Mapping[str, str]) -> urllib.request.OpenerDirector:
        handlers: list = [_PreservingRedirectHandler(dict(headers))]
        context = self._ssl_context()
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        return urllib.request.build_opener(*handlers)

    def start(self) -> int:
        if self._server is not None:
            return self.port

        proxy_self = self

        class ProxyRequestHandler(BaseHTTPRequestHandler):
            # HTTP/1.0 keeps the stream framing trivial: the response body is
            # terminated by closing the connection, which every media backend
            # understands even when the upstream length is unknown.
            protocol_version = "HTTP/1.0"

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

                req_headers = dict(session.headers)
                for name in FORWARDED_REQUEST_HEADERS:
                    value = self.headers.get(name)
                    if value:
                        req_headers[name] = value

                req = urllib.request.Request(
                    session.upstream_url,
                    headers=req_headers,
                    method="HEAD" if head_only else "GET",
                )

                try:
                    with proxy_self._opener(req_headers).open(
                        req, timeout=UPSTREAM_TIMEOUT
                    ) as resp:
                        self.send_response(resp.status)
                        forwarded: set[str] = set()
                        for name in FORWARDED_RESPONSE_HEADERS:
                            value = resp.headers.get(name)
                            if value:
                                forwarded.add(name.lower())
                                if name.lower() == "content-type":
                                    value = guess_content_type(
                                        session.upstream_url, value
                                    )
                                self.send_header(name, value)
                        if "content-type" not in forwarded:
                            self.send_header(
                                "Content-Type",
                                guess_content_type(session.upstream_url, None),
                            )
                        if "accept-ranges" not in forwarded:
                            self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Connection", "close")
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
                    logger.debug("Proxy upstream HTTP %s: %s", exc.code, session.stream_id)
                    try:
                        self.send_response(exc.code)
                        self.send_header("Connection", "close")
                        self.end_headers()
                    except Exception:
                        pass
                except (socket.timeout, TimeoutError):
                    logger.warning("代理上游超时：%s", session.stream_id)
                    self._fail(504, "Upstream timeout")
                except Exception as exc:  # noqa: BLE001 - surface any TLS/network issue
                    logger.warning(
                        "代理上游失败：%s（%s）", type(exc).__name__, session.stream_id
                    )
                    self._fail(502, f"Upstream error: {type(exc).__name__}")

            def _fail(self, code: int, message: str) -> None:
                try:
                    self.send_error(code, message)
                except Exception:
                    pass

        self._server = ThreadingHTTPServer((self.host, self._port), ProxyRequestHandler)
        self._server.daemon_threads = True
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
_default_tls_verify = True


def get_proxy(tls_verify: bool | None = None) -> LocalStreamingProxy:
    global _global_proxy
    with _proxy_lock:
        policy = _default_tls_verify if tls_verify is None else bool(tls_verify)
        if _global_proxy is None:
            _global_proxy = LocalStreamingProxy(tls_verify=policy)
            _global_proxy.start()
        else:
            _global_proxy.set_tls_verify(policy)
        return _global_proxy


def configure_proxy_tls(verify: bool) -> None:
    """Update TLS policy without starting the proxy if it is not running yet."""
    global _global_proxy, _default_tls_verify
    with _proxy_lock:
        _default_tls_verify = bool(verify)
        if _global_proxy is not None:
            _global_proxy.set_tls_verify(_default_tls_verify)
