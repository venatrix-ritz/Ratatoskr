"""Plain-assert tests for the idle-dim mirror (run: python tests/test_dim_mirror.py). No device needed."""
import json
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


class World:
    """A mirror wired to fakes, with its recovery file and saved-level file in a temp dir."""

    def __init__(self, pct=80, ok=True, saved=None):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "state", "dim-restore.json")
        self.saved = os.path.join(self.dir, "saved")
        if saved is not None:
            with open(self.saved, "w") as f:
                f.write(f"{saved}\n")
        self.stats, self.log = FakeStats(pct, ok), FakeLogger()
        self.mirror = dm.DimMirror(self.stats, dm.IdleTracker(self.log), self.log, lambda: {},
                                   state_file=self.state, saved_path=self.saved)

    def record(self):
        try:
            with open(self.state) as f:
                return json.load(f)["pct"]
        except OSError:
            return None


def no_sleep():
    real, dm.time.sleep = dm.time.sleep, lambda s: None
    return real


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


def test_dim_changes_armadas_saved_level_on_the_last_step_only():
    w = World(80)
    real = no_sleep()
    try:
        w.mirror._dim(300, 301.0, 3)
    finally:
        dm.time.sleep = real
    assert w.mirror.dimmed and w.mirror._saved == 80
    assert [c[1] for c in w.stats.calls] == [False] * 5 + [True], w.stats.calls  # fade is brief, the end state is persisted
    assert w.stats.calls[-1][0] == 3 and all(c[2] == 1 for c in w.stats.calls)
    assert w.record() == 80, "the pre-dim level must be recorded for crash recovery"


def test_dim_starts_from_armadas_saved_level():
    w = World(80, saved=60)
    real = no_sleep()
    try:
        w.mirror._dim(300, 301.0, 3)
    finally:
        dm.time.sleep = real
    assert w.mirror._saved == 60 and w.record() == 60


def test_restore_persists_and_clears_the_record():
    w = World(80)
    real = no_sleep()
    try:
        w.mirror._dim(300, 301.0, 3)
    finally:
        dm.time.sleep = real
    assert w.mirror.restore("input") is True
    assert not w.mirror.dimmed and w.record() is None
    assert w.stats.calls[-1] == (80, True, 1)
    assert any(c == DebugCode.DIM_MIRROR for c, _ in w.log.lines)


def test_restore_failure_keeps_the_state_and_retries():
    w = World(80)
    real = no_sleep()
    try:
        w.mirror._dim(300, 301.0, 3)
    finally:
        dm.time.sleep = real
    w.stats.ok = False
    assert w.mirror.restore("input") is False
    assert w.mirror.dimmed and w.record() == 80
    assert any(c == DebugCode.ERR_BACKLIGHT_SYSFS for c, _ in w.log.lines)
    w.stats.ok = True
    assert w.mirror.restore("input") is True and w.record() is None


def test_no_dim_when_already_at_floor():
    w = World(2)
    w.mirror._dim(300, 301.0, 3)
    assert not w.mirror.dimmed and w.stats.calls == [] and w.record() is None


def test_unwritable_backlight_backs_off_and_rolls_back():
    w = World(80, ok=False)
    real = no_sleep()
    try:
        w.mirror._dim(300, 301.0, 3)
    finally:
        dm.time.sleep = real
    assert not w.mirror.dimmed and w.record() is None
    assert w.mirror._retry_after > time.monotonic() + 30
    assert w.stats.calls[-1] == (80, True, 1), "a failed dim tries to put the old level back"
    assert any(c == DebugCode.ERR_BACKLIGHT_SYSFS for c, _ in w.log.lines)


def test_recover_restores_a_dim_left_by_a_crash():
    w = World(3)
    os.makedirs(os.path.dirname(w.state), exist_ok=True)
    with open(w.state, "w") as f:
        json.dump({"pct": 70}, f)
    w.mirror.recover()
    assert w.stats.calls == [(70, True, 1)] and w.record() is None


def test_recover_keeps_the_record_if_the_write_fails():
    w = World(3, ok=False)
    os.makedirs(os.path.dirname(w.state), exist_ok=True)
    with open(w.state, "w") as f:
        json.dump({"pct": 70}, f)
    w.mirror.recover()
    assert w.record() == 70


def test_recover_ignores_a_corrupt_record():
    w = World(3)
    os.makedirs(os.path.dirname(w.state), exist_ok=True)
    with open(w.state, "w") as f:
        f.write("not json")
    w.mirror.recover()
    assert w.stats.calls == []


def test_on_ac_power():
    d = tempfile.mkdtemp()

    def put(name, text):
        path = os.path.join(d, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    usb1, usb0 = put("u1", "1\n"), put("u0", "0\n")
    charging, notcharging, disch = put("c", "Charging\n"), put("n", "Not charging\n"), put("d", "Discharging\n")
    assert dm.on_ac_power(disch, usb1) is True          # USB online wins, e.g. when a charge limit says "Not charging"
    assert dm.on_ac_power(notcharging, usb1) is True
    assert dm.on_ac_power(charging, usb0) is True
    assert dm.on_ac_power(notcharging, usb0) is False
    assert dm.on_ac_power(disch, usb0) is False
    assert dm.on_ac_power("/nonexistent", "/nonexistent") is False


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
