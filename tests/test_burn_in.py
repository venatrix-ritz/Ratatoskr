"""Tests for the active burn-in protection module (run: python tests/test_burn_in.py)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

from burn_in import BurnInProtector  # noqa: E402


def test_orbital_offset_stays_within_radius():
    protector = BurnInProtector(shift_radius=1.5, cycle_seconds=90.0)
    for t in [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0, 105.0]:
        dx, dy = protector.get_orbital_offset(t)
        assert abs(dx) <= 1.5001, f"dx {dx} exceeded radius"
        assert abs(dy) <= 1.5001, f"dy {dy} exceeded radius"


def test_hint_alpha_fades_after_duration():
    protector = BurnInProtector(hint_duration=5.0)
    protector.start_time = 100.0
    protector.mode_change_time = 100.0

    assert protector.get_hint_alpha(102.0) == 1.0  # inside 5s duration
    assert 0.0 < protector.get_hint_alpha(105.5) < 1.0  # mid-fade
    assert protector.get_hint_alpha(107.0) == 0.0  # fully faded out


def test_mode_change_resets_hint_alpha():
    protector = BurnInProtector(hint_duration=5.0)
    protector.start_time = 100.0
    protector.mode_change_time = 100.0

    assert protector.get_hint_alpha(110.0) == 0.0  # faded
    protector.notify_mode_change(now=110.0)
    assert protector.get_hint_alpha(111.0) == 1.0  # renewed after mode change


def test_luminance_scale_dims_when_idle():
    protector = BurnInProtector(idle_timeout=30.0, idle_floor=0.4)
    protector.last_touch_time = 200.0

    assert protector.get_luminance_scale(210.0) == 1.0  # active
    assert protector.get_luminance_scale(230.0) == 1.0  # right at timeout
    assert 0.4 < protector.get_luminance_scale(232.5) < 1.0  # mid-fade
    assert protector.get_luminance_scale(240.0) == 0.4  # full floor

    # Touch wakes immediately
    protector.record_touch(now=241.0)
    assert protector.get_luminance_scale(241.0) == 1.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
