"""The driver's IPC protocol and its helpers.

One JSON object per connection each way over a UNIX socket. The server replies and then closes the connection, so a
client reads until EOF; neither side may assume a message fits one recv() (a status reply is several KB), and neither
may wait forever.
"""
from __future__ import annotations

import json
import os
import socket
import time

MAX_REQUEST = 64 * 1024
MAX_REPLY = 1024 * 1024


def read_json_request(conn: socket.socket, limit: int = MAX_REQUEST, timeout: float = 2.0):
    """Read one JSON request from a connected client. Returns the parsed value, or None if the client connected and
    closed without sending anything. Raises ValueError for malformed or oversized input and TimeoutError if the
    request does not complete in time."""
    deadline = time.monotonic() + timeout
    buf = b""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request not complete in time")
        conn.settimeout(remaining)
        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            raise TimeoutError("request not complete in time") from None
        if not chunk:
            if not buf:
                return None
            return json.loads(buf.decode("utf-8"))  # raises ValueError if it was cut short
        buf += chunk
        if len(buf) > limit:
            raise ValueError("request too large")
        try:
            return json.loads(buf.decode("utf-8"))
        except ValueError:
            continue  # not all of it has arrived yet


def read_until_eof(sock: socket.socket, limit: int = MAX_REPLY, timeout: float = 2.0) -> bytes:
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("reply not complete in time")
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            raise TimeoutError("reply not complete in time") from None
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise ValueError("reply too large")


def request(path: str, payload: dict, timeout: float = 2.0) -> dict:
    """Send one request to the driver and return its reply, or {"ok": False, "error": ...}."""
    if not os.path.exists(path):
        return {"ok": False, "error": "socket not found"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(json.dumps(payload).encode("utf-8"))
            data = read_until_eof(s, timeout=timeout)
        if not data:
            return {"ok": False, "error": "empty reply"}
        return json.loads(data.decode("utf-8"))
    except Exception as err:
        return {"ok": False, "error": f"{type(err).__name__}: {err}"}


# Request builders. The driver reads flat keys (a nested {"settings": {...}} is ignored), takes brightness through
# set_top_brightness / set_bottom_brightness, and has no set_debug_hud action; tests/test_ipc_util.py checks these
# against the actions thor_app.py really handles.

def settings_request(**settings) -> dict:
    return {"action": "set_settings", **settings}


def brightness_request(target: str, percent: int) -> dict:
    return {"action": "set_top_brightness" if target == "top" else "set_bottom_brightness", "brightness": int(percent)}


def hud_request(enabled: bool) -> dict:
    return settings_request(debug_hud=bool(enabled))
