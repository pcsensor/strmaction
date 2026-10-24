"""Loopback HTTP/1.1 fixture for CI's production Swift cache tests."""
import json
import os
import subprocess
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

state = {"entries": 0, "ticket": 0, "active": 0, "peak": 0, "ports": set(), "head_starts": []}
lock = threading.Lock()
length = 12 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, code, data=b"", headers=None):
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        if self.path == "/stats":
            with lock:
                result = {**state, "ports": len(state["ports"])}
            self.reply(200, json.dumps(result).encode())
            return
        if self.path == "/expire":
            with lock:
                state["ticket"] += 1
            self.reply(200)
            return
        if self.headers.get("User-Agent") != "pan-fixture" or self.headers.get("Referer") != "https://pan.example/":
            self.reply(400)
            return
        if self.path == "/entry":
            with lock:
                state["entries"] += 1
                state["ticket"] += 1
                ticket = state["ticket"]
            self.reply(302, headers={"Location": f"/file?ticket={ticket}"})
            return
        if self.path == "/non-range":
            self.reply(200, b"plain-video", {"Content-Type": "video/mp4"})
            return
        if self.path.startswith("/file"):
            with lock:
                ticket = state["ticket"]
            if self.path != f"/file?ticket={ticket}":
                self.reply(403)
                return
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if not match:
            self.reply(400)
            return
        start = int(match[1])
        end = min(length - 1, int(match[2]) if match[2] else length - 1)
        if start > end:
            self.reply(416)
            return
        probe = start == end == 0
        stall_head = False
        with lock:
            state["ports"].add(self.client_address[1])
            if not probe:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                if self.path.startswith("/head-stall"):
                    state["head_starts"].append(start)
                    stall_head = len(state["head_starts"]) == 1
        try:
            if not probe:
                time.sleep(2 if self.path.startswith("/slow") else 0.04)
            self.send_response(206)
            bad = self.path.startswith("/bad-range") and not probe
            self.send_header("Content-Range", f"bytes {start + 1 if bad else start}-{end}/{length}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Content-Type", "video/mp4")
            self.send_header("ETag", '"fixture"')
            self.end_headers()
            cursor = start
            if stall_head or (self.path.startswith("/stream-prefix") and end - start > 1024 * 1024):
                count = min(64 * 1024, end - start + 1)
                self.wfile.write(bytes((cursor + i) % 251 for i in range(count)))
                self.wfile.flush()
                cursor += count
                time.sleep(5)
            for cursor in range(cursor, end + 1, 256 * 1024):
                self.wfile.write(bytes((cursor + i) % 251 for i in range(min(256 * 1024, end - cursor + 1))))
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        finally:
            if self.path.startswith("/stale"):
                self.close_connection = True
            with lock:
                if not probe:
                    state["active"] -= 1


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if sys.argv[1] == "--run":
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = subprocess.run([sys.argv[2]], env={**os.environ, "RANGE_FIXTURE_URL": f"http://127.0.0.1:{server.server_port}/"}, timeout=120)
            raise SystemExit(result.returncode)
        finally:
            server.shutdown()
            server.server_close()
    else:
        with open(sys.argv[1], "w") as port_file:
            port_file.write(str(server.server_port))
        server.serve_forever()
