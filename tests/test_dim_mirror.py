"""Plain-assert tests for the idle-dim mirror (run: python tests/test_dim_mirror.py). No device needed."""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import dim_mirror as dm  # noqa: E402
from debug_codes import DebugCode  # noqa: E402

VDF = '''"system"
{
\t"IdleBacklightDimBatterySeconds"\t\t"300"
\t"IdleBacklightDimACSeconds"\t\t"0"
\t"DisplayBrightness"\t\t"0.0100000007078051567"
}
'''


class FakeStats:
    def __init__(self, pct=80, ok=True):
        self.pct, self.ok, self.calls, self.last_write_ok = pct, ok, [], True

    def get_stats(self):
        return {"bot_bright_pct": self.pct}

    def set_bottom_brightness(self, pct, persist=True, minimum=5):
        self.calls.append((pct, persist, minimum))
        self.last_write_ok = self.ok
        if self.ok:
            self.pct = pct
        return pct


class FakeLogger:
    def __init__(self):
        self.lines = []

    def log(self, code, msg=""):
        self.lines.append((code, msg))


def test_vdf():
    with tempfile.NamedTemporaryFile("w", suffix=".vdf", delete=False, encoding="utf-8") as f:
        f.write(VDF)
    try:
        assert dm.read_dim_seconds(False, f.name) == 300
        assert dm.read_dim_seconds(True, f.name) == 0
    finally:
        os.unlink(f.name)
    assert dm.read_dim_seconds(False, "/nonexistent/config.vdf") == 0


def test_activity():
    k, a = dm.EV_KEY, dm.EV_ABS
    assert dm._is_activity(k, 304, 1, "Xbox pad")
    assert not dm._is_activity(k, 304, 0, "Xbox pad")  # release
    assert not dm._is_activity(a, dm.ABS_X, 3000, "Xbox pad")  # drift
    assert dm._is_activity(a, dm.ABS_X, -20000, "Xbox pad")
    assert dm._is_activity(a, dm.ABS_Z, 255, "Xbox pad")
    assert dm._is_activity(a, dm.ABS_HAT0X, -1, "Xbox pad")
    assert dm._is_activity(a, 0x35, 500, "top_touchscreen")  # ABS_MT_POSITION_X
    assert not dm._is_activity(0x00, 0, 0, "Xbox pad")  # EV_SYN


def test_dim_and_restore():
    stats, log = FakeStats(80), FakeLogger()
    mirror = dm.DimMirror(stats, dm.IdleTracker(log), log, lambda: {})
    real_sleep, dm.time.sleep = dm.time.sleep, lambda s: None
    try:
        mirror._dim(300, 301.0, 3)
        assert mirror.dimmed and mirror._saved == 80
        assert stats.calls[-1] == (3, False, 1), stats.calls
        assert all(c[1] is False for c in stats.calls)  # never persisted to Armada's saved level
        mirror.restore("input")
        assert not mirror.dimmed and stats.calls[-1] == (80, False, 1)
        assert any(c == DebugCode.DIM_MIRROR for c, _ in log.lines)
    finally:
        dm.time.sleep = real_sleep


def test_no_dim_when_already_at_floor():
    stats = FakeStats(2)
    mirror = dm.DimMirror(stats, dm.IdleTracker(FakeLogger()), FakeLogger(), lambda: {})
    mirror._dim(300, 301.0, 3)
    assert not mirror.dimmed and stats.calls == []


def test_unwritable_backlight_backs_off():
    stats, log = FakeStats(80, ok=False), FakeLogger()
    mirror = dm.DimMirror(stats, dm.IdleTracker(log), log, lambda: {})
    real_sleep, dm.time.sleep = dm.time.sleep, lambda s: None
    try:
        mirror._dim(300, 301.0, 3)
    finally:
        dm.time.sleep = real_sleep
    assert not mirror.dimmed and mirror._retry_after > time.monotonic() + 30
    assert any(c == DebugCode.ERR_BACKLIGHT_SYSFS for c, _ in log.lines)


def test_idle_tracker_poke():
    t = dm.IdleTracker(FakeLogger())
    time.sleep(0.2)
    assert t.idle_seconds() >= 0.1
    t.poke()
    assert t.idle_seconds() < 0.1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
