"""Tests for the pointer auto-hide override helper (run: python tests/test_session_cursor.py). Touches only temp dirs."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import session_cursor as sc  # noqa: E402


def fake_proc(root, procs):
    for pid, args in procs.items():
        os.makedirs(os.path.join(root, str(pid)), exist_ok=True)
        with open(os.path.join(root, str(pid), "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in args) + b"\0")


def test_turning_it_on_writes_the_override_and_off_removes_it():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "environment.d", "50-ratatoskr-cursor.conf")
        assert not sc.is_configured(path)
        assert sc.set_stay_visible(True, path) and sc.is_configured(path)
        text = open(path, encoding="utf-8").read()
        assert f"HIDE_CURSOR_DELAY_MS={sc.STAY_VISIBLE_MS}\n" in text and text.startswith("#")
        assert not os.path.exists(path + ".tmp")
        assert sc.set_stay_visible(False, path) and not sc.is_configured(path) and not os.path.exists(path)
        assert sc.set_stay_visible(False, path)           # already off: still fine


def test_the_file_is_valid_to_source_from_a_shell():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.conf")
        sc.set_stay_visible(True, path)
        data = open(path, "rb").read()
        assert b"\r" not in data
        assert all(line.startswith(b"#") or b"=" in line for line in data.splitlines() if line)


def test_a_file_system_error_is_reported_not_raised():
    with tempfile.TemporaryDirectory() as d:
        blocker = os.path.join(d, "afile")
        open(blocker, "w").close()
        assert sc.set_stay_visible(True, os.path.join(blocker, "sub", "x.conf")) is False


def test_the_running_delay_is_read_from_gamescopes_arguments():
    with tempfile.TemporaryDirectory() as d:
        fake_proc(d, {10: ["/usr/bin/bash", "x"],
                      11: ["gamescope", "--backend", "drm"],                      # the bottom screen's: no delay
                      12: ["/usr/bin/gamescope", "--hide-cursor-delay", "3000", "--steam"]})
        assert sc.running_delay_ms(d, ttl=0) == 3000


def test_the_equals_form_and_garbage_are_handled():
    with tempfile.TemporaryDirectory() as d:
        fake_proc(d, {1: ["gamescope", "--hide-cursor-delay=3600000"]})
        assert sc.running_delay_ms(d, ttl=0) == 3600000
    with tempfile.TemporaryDirectory() as d:
        fake_proc(d, {1: ["gamescope", "--hide-cursor-delay", "soon"]})
        assert sc.running_delay_ms(d, ttl=0) is None
    assert sc.running_delay_ms(os.path.join(tempfile.gettempdir(), "no-such-proc-root"), ttl=0) is None


def test_status_tells_pending_from_active():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "c.conf")
        proc = os.path.join(d, "proc")
        fake_proc(proc, {1: ["gamescope", "--hide-cursor-delay", "3000"]})
        s = sc.status(path, proc, ttl=0)
        assert s == {"cursor_stay_visible": False, "cursor_hide_delay_ms": 3000, "cursor_stay_visible_active": False}
        sc.set_stay_visible(True, path)                       # switched on, session not restarted yet
        s = sc.status(path, proc, ttl=0)
        assert s["cursor_stay_visible"] and not s["cursor_stay_visible_active"]
        fake_proc(proc, {1: ["gamescope", "--hide-cursor-delay", str(sc.STAY_VISIBLE_MS)]})   # after a restart
        s = sc.status(path, proc, ttl=0)
        assert s["cursor_stay_visible"] and s["cursor_stay_visible_active"]


def test_the_process_scan_is_cached():
    with tempfile.TemporaryDirectory() as d:
        fake_proc(d, {1: ["gamescope", "--hide-cursor-delay", "3000"]})
        assert sc.running_delay_ms(d, ttl=0) == 3000
        fake_proc(d, {1: ["gamescope", "--hide-cursor-delay", "9999"]})
        assert sc.running_delay_ms(d, ttl=60) == 3000          # served from the cache
        assert sc.running_delay_ms(d, ttl=0) == 9999


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
