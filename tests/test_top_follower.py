"""TopFollower: what the top backlight does, and when the bottom panel should dim and restore."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
from top_follower import TopFollower  # noqa: E402

HZ = 4.0
FLOOR = 112 / 4096  # Steam's idle floor on the Thor's top panel


def run(f, t0, steps):
    """steps: iterable of levels, one per 1/HZ s from t0. Returns [(t, action)] for every non-None answer and the end time."""
    out, t = [], t0
    for level in steps:
        a = f.update(t, level)
        if a:
            out.append((round(t - t0, 2), a))
        t += 1 / HZ
    return out, t


def ramp(a, b, seconds):
    n = int(seconds * HZ)
    return [a + (b - a) * i / n for i in range(1, n + 1)]


def test_idle_ramp_dims_within_a_few_seconds_and_restores_on_wake():
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 240)                      # a minute of normal brightness
    assert out == [], out
    out, t = run(f, t, ramp(1.0, FLOOR, 30) + [FLOOR] * 40)  # Steam's 30 s ramp, then the floor
    assert [a for _t, a in out] == ["dim"], out
    assert out[0][0] <= 4.0, ("dim should start within about 4 s of the ramp", out)
    assert f.dimmed
    out, t = run(f, t, [1.0] * 4)                          # input: the top comes back
    assert [a for _t, a in out] == ["restore"] and not f.dimmed, out


# The real ramp, read from the Thor's top backlight once a second (2026-10-08 19:48:00-19:48:29, Steam's idle dim).
REAL_RAMP = [4079, 4015, 3838, 3614, 3324, 3003, 2666, 2345, 2007, 1734, 1461, 1204, 1028, 835, 706, 578, 481, 401, 337, 289,
             240, 208, 176, 160, 144, 128, 112]


def test_steams_real_ramp_dims_early_even_when_sampled_once_a_second():
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 240)
    f2 = TopFollower()
    t0, hist = 0.0, []
    for i in range(60):
        f2.update(float(i), 1.0)
    acts = []
    for i, v in enumerate(REAL_RAMP + [112] * 5):
        a = f2.update(60.0 + i, v / 4096)
        if a:
            acts.append((i, a))
    assert acts and acts[0][1] == "dim" and acts[0][0] <= 6, ("dim within 6 s of the ramp's start", acts)
    assert [a for _i, a in acts] == ["dim"], acts


def test_small_changes_and_jitter_never_dim():
    f = TopFollower()
    out, _ = run(f, 0.0, [1.0, 0.998, 1.0, 0.997, 1.0] * 60 + ramp(1.0, 0.96, 3) + [0.96] * 40)
    assert out == [], out


def test_a_slider_move_that_stops_above_the_floor_is_undone():
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 80)
    out, t = run(f, t, ramp(1.0, 0.5, 3) + [0.5] * 40)     # dragged down to half and left there
    acts = [a for _t, a in out]
    assert acts == ["dim", "restore"], out
    assert not f.dimmed


def test_a_later_idle_ramp_from_the_new_level_dims_again():
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 80 + ramp(1.0, 0.5, 3) + [0.5] * 40)
    out, t = run(f, t, [0.5] * 40 + ramp(0.5, FLOOR, 30) + [FLOOR] * 8)
    assert "dim" in [a for _t, a in out], out


def test_touching_the_bottom_latches_until_the_top_recovers():
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 80 + ramp(1.0, FLOOR, 10))
    assert f.dimmed
    f.suppress()
    out, t = run(f, t, ramp(FLOOR, FLOOR / 2, 5) + [FLOOR] * 20)   # the top keeps going down: no new dim
    assert out == [], out
    out, t = run(f, t, [1.0] * 12)                                  # then it comes back (latch released)
    out2, t = run(f, t, [1.0] * 40 + ramp(1.0, FLOOR, 10))
    assert [a for _t, a in out2] == ["dim"], out2


def test_reject_forgets_the_fall_and_needs_a_fresh_one():
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 80 + ramp(1.0, 0.7, 3))
    assert [a for _t, a in out] == ["dim"] and f.dimmed
    f.reject()
    assert not f.dimmed
    out, t = run(f, t, ramp(0.7, 0.69, 1))                 # one more sample of the same slow drift: no new dim yet
    assert out == [], out
    out, t = run(f, t, ramp(0.69, 0.4, 4))                 # a new steady fall of several seconds: dim again
    assert "dim" in [a for _t, a in out], out


def test_a_suspend_between_samples_is_not_a_fall():
    # Full brightness, then a 14 s gap (the suspend, on a clock that counted it), then the top still at its floor on wake.
    f = TopFollower()
    out, t = run(f, 0.0, [1.0] * 80)
    out2, t = run(f, t + 14.0, [FLOOR, FLOOR, FLOOR, 0.5, 1.0, 1.0])
    assert out2 == [], out2
    # The same samples on a clock that stood still across the suspend DO look like a steep fall: why the boot clock matters.
    g = TopFollower()
    run(g, 0.0, [1.0] * 80)
    bad, _ = run(g, 20.0 + 0.25, [0.8, 0.6, 0.4, 0.2, FLOOR, FLOOR])
    assert [a for _t, a in bad] == ["dim"], bad


def test_starting_while_the_top_is_already_at_the_floor_dims_and_restores_on_wake():
    f = TopFollower()
    out, t = run(f, 0.0, [FLOOR] * 8)
    assert [a for _t, a in out] == ["dim"] and f.dimmed, out
    out, t = run(f, t, [1.0] * 4)
    assert [a for _t, a in out] == ["restore"] and not f.dimmed, out
    g = TopFollower()
    out, _ = run(g, 0.0, [0.5] * 8)                      # a user-chosen mid level at start is not a dim
    assert out == [], out


def test_sleep_blank_then_wake():
    f = TopFollower()
    run(f, 0.0, [1.0] * 80)
    out, t = run(f, 20.0, [1.0, 0.5, 0.08, 0.027, 0.027, 0.027, 0.027, 0.027])
    assert out == [], out        # the blank before a suspend is a one-second drop of most of the range: not a dim
    out, t = run(f, t, [1.0, 0.98, 0.5, 0.027, 0.027, 0.027])
    assert out == [], out        # at 4 Hz it is a couple of samples: the same
    out, _ = run(f, t + 1000, [1.0, 1.0, 1.0])
    assert not f.dimmed


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
