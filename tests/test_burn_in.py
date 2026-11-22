"""Tests for the active burn-in protection module (run: python tests/test_burn_in.py)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import burn_in  # noqa: E402
from burn_in import BurnInProtector, plan_redraw  # noqa: E402


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


def idle_frames(seconds=180.0, tick=1.0):
    """Drive the planner the way ThorApp._on_tick does on an idle, lit screen whose stats never change: the times at
    which a frame went out."""
    p = BurnInProtector()
    p.start_time = p.mode_change_time = p.last_touch_time = -1000.0  # hint long faded, luminance at its floor
    def state(t):
        return {"orbit": p.orbit_step(t), "lum": round(p.get_luminance_scale(t), 2), "hint": 0.0,
                "page": ("same",), "ribbon": ("same",)}
    drawn, frames, t = state(0.0), [], 0.0
    while t < seconds:
        t += p.next_tick_s(t)
        if plan_redraw(drawn, state(t)):
            drawn = state(t)
            frames.append(t)
    return frames


def test_the_orbit_moves_in_half_pixel_steps_over_its_full_reach():
    p = BurnInProtector()
    xs, ys, steps, last = set(), set(), 0, None
    for i in range(900):  # one 90 s cycle at 0.1 s
        dx, dy = p.orbit_step(i * 0.1)
        assert dx * 2 == round(dx * 2) and dy * 2 == round(dy * 2), (dx, dy)
        xs.add(dx)
        ys.add(dy)
        steps += last is not None and (dx, dy) != last
        last = (dx, dy)
    assert min(xs) == -1.5 and max(xs) == 1.5 and min(ys) == -1.5 and max(ys) == 1.5, (xs, ys)
    assert len(xs) == 7 and len(ys) == 7, (xs, ys)
    assert 24 <= steps <= 30, steps
    print(f"  orbit: {steps} half-pixel steps per 90 s cycle")


def test_an_idle_screen_with_unchanged_stats_still_gets_a_new_frame_at_every_orbit_step():
    frames = idle_frames(180.0)
    gaps = [b - a for a, b in zip([0.0] + frames, frames)]
    assert len(frames) >= 50, len(frames)  # 27 steps per 90 s cycle
    # The longest dwell is where both axes turn at once (t = 45 s of each cycle, 11 s); everywhere else a few seconds
    assert max(gaps) <= 12.0, max(gaps)
    assert sorted(gaps)[len(gaps) // 2] <= 4.0, sorted(gaps)
    print(f"  idle, stats unchanged: {len(frames)} frames in 180 s ({len(frames) / 180:.2f}/s), longest gap {max(gaps):.0f} s")


def test_the_luminance_ease_and_the_hint_fade_draw_at_four_frames_a_second():
    p = BurnInProtector()
    p.start_time = p.mode_change_time = 0.0
    p.last_touch_time = 0.0
    assert p.next_tick_s(2.0) == burn_in.IDLE_TICK_S
    assert p.next_tick_s(4.5) == burn_in.TRANSITION_TICK_S   # the second before the hint fade starts
    assert p.next_tick_s(5.7) == burn_in.TRANSITION_TICK_S   # mid-fade
    assert p.next_tick_s(10.0) == burn_in.IDLE_TICK_S
    assert p.next_tick_s(29.5) == burn_in.TRANSITION_TICK_S  # just before the luminance ease
    assert p.next_tick_s(32.0) == burn_in.TRANSITION_TICK_S
    assert p.next_tick_s(40.0) == burn_in.IDLE_TICK_S        # at the floor
    lums, t = [], 30.0
    while t < 35.0:
        t += p.next_tick_s(t)
        lums.append(round(p.get_luminance_scale(t), 2))
    assert len(set(lums)) >= 18, lums  # each 0.25 s tick of the 5 s ease is a new veil level


def test_plan_redraw():
    base = {"orbit": (0.5, -1.0), "lum": 1.0, "hint": 0.0, "page": ("p",), "ribbon": ("a",)}
    assert plan_redraw(None, base) == "full"
    assert plan_redraw(base, dict(base)) is None
    assert plan_redraw(base, dict(base, ribbon=("b",))) == "ribbon"
    assert plan_redraw(base, dict(base, ribbon=("b",)), ribbon_ok=False) == "full"
    for key, value in (("orbit", (1.0, -1.0)), ("lum", 0.4), ("hint", 0.5), ("page", ("q",))):
        assert plan_redraw(base, dict(base, **{key: value})) == "full", key
        assert plan_redraw(base, dict(base, ribbon=("b",), **{key: value})) == "full", key


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
