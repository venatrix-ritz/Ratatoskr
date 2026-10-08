"""Tests for the hardware helpers that need no device (run: python tests/test_system_stats.py)."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import system_stats as ss  # noqa: E402


class Done:
    def __init__(self, rc):
        self.returncode = rc


def with_run(fn, read=None):
    real_run, real_read = ss.subprocess.run, ss._read_str
    ss.subprocess.run = fn
    if read is not None:
        ss._read_str = lambda path, default="": read
    try:
        return ss._write_via_sudo("/sys/class/backlight/x/brightness", "8")
    finally:
        ss.subprocess.run, ss._read_str = real_run, real_read


def raise_timeout(*a, **k):
    raise subprocess.TimeoutExpired("sudo", 2.0)


def raise_other(*a, **k):
    raise FileNotFoundError("sudo")


def test_sudo_write_ok_and_failed():
    assert with_run(lambda *a, **k: Done(0)) is True
    assert with_run(lambda *a, **k: Done(1)) is False


def test_sudo_write_that_times_out_is_checked_by_reading_it_back():
    assert with_run(raise_timeout, read="8") is True    # tee finished before it was killed
    assert with_run(raise_timeout, read="255") is False  # it did not


def test_sudo_write_survives_other_errors():
    assert with_run(raise_other) is False


def test_sudo_write_gets_a_generous_timeout():
    seen = {}

    def spy(*a, **k):
        seen.update(k)
        return Done(0)

    with_run(spy)
    assert seen["timeout"] >= 1.5, seen


def test_failure_reason_is_recorded_for_the_logs():
    class Failed:
        returncode = 1
        stderr = "tee: /sys/class/backlight/x/brightness: Invalid argument\n"

    assert with_run(lambda *a, **k: Failed()) is False
    assert "exited 1" in ss.LAST_WRITE_ERROR and "Invalid argument" in ss.LAST_WRITE_ERROR
    assert with_run(raise_timeout, read="255") is False
    assert "timed out" in ss.LAST_WRITE_ERROR
    assert with_run(raise_other) is False
    assert "FileNotFoundError" in ss.LAST_WRITE_ERROR


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
