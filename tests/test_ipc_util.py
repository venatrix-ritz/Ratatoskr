"""Tests for the IPC helpers (run: python tests/test_ipc_util.py). Uses socket pairs only."""
import json
import os
import re
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import ipc_util as iu  # noqa: E402


KEEP = []


def feed(parts, delay=0.0, close=True):
    """A connected pair; a thread writes `parts` to one end. Returns the other end."""
    a, b = socket.socketpair()

    def run():
        for p in parts:
            time.sleep(delay)
            a.sendall(p)
        if close:
            a.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    KEEP.append((a, t))  # sockets have no __dict__: keep the writer end alive here
    return b


def test_a_request_in_one_piece():
    s = feed([b'{"action": "get_status"}'], close=False)
    assert iu.read_json_request(s, timeout=1.0) == {"action": "get_status"}


def test_a_request_that_arrives_in_pieces():
    raw = json.dumps({"action": "set_settings", "sensitivity": 1.5, "glide": True}).encode()
    s = feed([raw[:9], raw[9:20], raw[20:]], delay=0.05, close=False)
    assert iu.read_json_request(s, timeout=2.0)["sensitivity"] == 1.5


def test_a_request_larger_than_one_recv():
    big = {"action": "set_settings", "pad": "x" * 9000}
    s = feed([json.dumps(big).encode()], close=False)
    assert iu.read_json_request(s, timeout=2.0)["pad"] == "x" * 9000


def test_malformed_oversized_and_empty_requests():
    for parts, expect in (([b"{not json"], ValueError), ([b'{"action": "x"'], ValueError)):
        s = feed(parts)
        try:
            iu.read_json_request(s, timeout=1.0)
            raise AssertionError("expected an error")
        except expect:
            pass
    s = feed([b"{" + b" " * 70000])
    try:
        iu.read_json_request(s, limit=1000, timeout=1.0)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert iu.read_json_request(feed([]), timeout=1.0) is None      # connected and closed


def test_a_stalled_client_times_out_instead_of_blocking_forever():
    s = feed([b'{"action": "get'], close=False)
    t0 = time.monotonic()
    try:
        iu.read_json_request(s, timeout=0.3)
        raise AssertionError("expected TimeoutError")
    except TimeoutError:
        pass
    assert time.monotonic() - t0 < 2.0


def test_a_reply_bigger_than_4096_is_read_whole():
    payload = json.dumps({"ok": True, "pad": "y" * 200000}).encode()
    s = feed([payload[:70000], payload[70000:]], delay=0.02)
    assert json.loads(iu.read_until_eof(s, timeout=3.0))["pad"] == "y" * 200000


def test_a_reply_that_never_ends_times_out():
    s = feed([b'{"ok": true'], close=False)
    try:
        iu.read_until_eof(s, timeout=0.3)
        raise AssertionError("expected TimeoutError")
    except TimeoutError:
        pass


def test_the_request_builders_only_use_actions_the_driver_handles():
    src = open(os.path.join(ROOT, "bin", "thor_app.py"), encoding="utf-8").read()
    handled = set(re.findall(r'action == "([a-z_]+)"', src))
    for req in (iu.settings_request(sensitivity=2.0), iu.brightness_request("top", 40),
                iu.brightness_request("bottom", 40), iu.hud_request(True)):
        assert req["action"] in handled, (req, sorted(handled))


def test_settings_are_flat_and_brightness_uses_the_drivers_key():
    assert iu.settings_request(glide=False, friction=7) == {"action": "set_settings", "glide": False, "friction": 7}
    assert iu.brightness_request("bottom", 55) == {"action": "set_bottom_brightness", "brightness": 55}
    assert iu.hud_request(True) == {"action": "set_settings", "debug_hud": True}


def test_zz_the_drivers_reply_to_a_status_request_is_not_cut_at_4096():
    # the old clients called recv(4096) once; a real status reply is larger than that on the Thor
    reply = {"ok": True, "hardware_stats": {f"k{i}": i for i in range(600)}}
    assert len(json.dumps(reply)) > 4096
    s = feed([json.dumps(reply).encode()])
    assert json.loads(iu.read_until_eof(s, timeout=1.0)) == reply


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
