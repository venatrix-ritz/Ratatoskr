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


# --- slider writes ----------------------------------------------------------------------------------------

def test_a_burst_of_slider_values_is_folded_into_few_writes_and_the_last_one_wins():
    import time
    seen = []

    def slow_write(v):
        time.sleep(0.03)
        seen.append(v)

    w = ss._LatestWriter(slow_write, "test-writer")
    for v in range(1, 61):                            # 60 touch events in about 0.3 s
        w.submit(v)
        time.sleep(0.005)
    assert w.wait_idle(2.0)
    assert seen[-1] == 60, seen
    assert len(seen) < 20, f"{len(seen)} writes for 60 events"
    assert seen == sorted(seen)


def test_a_failing_write_does_not_end_the_writer():
    import time
    seen = []

    def flaky(v):
        seen.append(v)
        if v == 1:
            raise RuntimeError("boom")

    w = ss._LatestWriter(flaky, "test-flaky")
    w.submit(1)
    assert w.wait_idle(1.0)
    w.submit(2)
    assert w.wait_idle(1.0)
    assert seen == [1, 2] and "boom" in ss.LAST_WRITE_ERROR


class CountingStats(ss.HardwareStats):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.samples = 0
        self.written = []

    def _sample(self):
        self.samples += 1
        return {"bot_bright_pct": 40, "top_bright_pct": 50, "vol_pct": 30}

    def set_bottom_brightness(self, pct, persist=True, minimum=5):
        self.written.append(pct)
        return pct


def test_the_requested_value_shows_at_once_and_the_real_one_returns_later():
    import time
    s = CountingStats(optimistic_hold=0.1)
    s._writers["bottom"]._fn = s.set_bottom_brightness
    s.start_sampler(interval=60)
    assert s.get_stats()["bot_bright_pct"] == 40
    assert s.request_bottom_brightness(75) == 75
    assert s.get_stats()["bot_bright_pct"] == 75       # drawn before any write has finished
    assert s.wait_for_writes(1.0) and s.written == [75]
    time.sleep(0.15)
    assert s.get_stats()["bot_bright_pct"] == 40       # the sampled value takes over once the hold ends
    s.stop_sampler()


def test_with_the_sampler_running_get_stats_never_samples():
    s = CountingStats()
    s.start_sampler(interval=60)
    before = s.samples
    for _ in range(200):
        s.get_stats()
    s.request_bottom_brightness(60)                    # a write used to force a fresh sample on the next read
    for _ in range(200):
        s.get_stats()
    assert s.samples == before, (before, s.samples)
    s.stop_sampler()


def test_requests_are_clamped():
    s = CountingStats()
    assert s.request_bottom_brightness(-30) == 5
    assert s.request_bottom_brightness(900) == 100
    assert s.request_volume(-1) == 0 and s.request_volume(400) == 100


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
