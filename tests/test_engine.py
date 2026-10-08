"""Gesture engine tests with a fake output device (run: python tests/test_engine.py). No device needed."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import engine as E  # noqa: E402


class FakeBridge:
    def __init__(self):
        self.log = []

    def emit_mouse_rel(self, dx, dy):
        self.log.append(("rel", dx, dy))

    def emit_scroll(self, dx, dy):
        self.log.append(("scroll", dx, dy))

    def tap_button(self, button, *a):
        self.log.append(("click", button))

    def tap_key(self, key, *a):
        self.log.append(("tapkey", key))

    def key(self, key, down):
        self.log.append(("key", key, down))

    def mouse_button(self, button, down):
        self.log.append(("btn", button, down))


def fresh(**settings):
    bridge = FakeBridge()
    g = E.TouchGestureProcessor(bridge)
    g.set_settings(**settings)
    bridge.log.clear()
    return g, bridge


def moves(log):
    return [e for e in log if e[0] == "rel"]


def clicks(log):
    return [e for e in log if e[0] == "click"]


def finger_path(g, tid, x0, y0, steps, dx, dy, t0, dt):
    """Put a finger down at (x0, y0) at t0 and move it `steps` times by (dx, dy) every dt seconds; returns the last time."""
    g.touch_down(tid, x0, y0, t0)
    t = t0
    for i in range(1, steps + 1):
        t = t0 + dt * i
        g.touch_move(tid, x0 + dx * i, y0 + dy * i, t)
    return t


# --- tap versus move --------------------------------------------------------------------------------------

def test_quick_nudge_moves_the_cursor_and_does_not_click():
    g, b = fresh(sensitivity=1.5, glide=False)
    t = finger_path(g, 1, 300, 300, 10, 3, 0, 100.0, 0.015)      # 30 px in 0.15 s
    g.touch_up(1, t + 0.01)
    assert moves(b.log) and not clicks(b.log), b.log


def test_clean_tap_clicks_and_does_not_move_the_cursor():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 302, 301, 100.03)                            # finger jitter
    g.touch_move(1, 301, 300, 100.06)
    g.touch_up(1, 100.10)
    assert clicks(b.log) == [("click", E.BTN_LEFT)] and not moves(b.log), b.log


def test_slow_drag_moves_and_does_not_click():
    g, b = fresh(sensitivity=1.5, glide=False)
    t = finger_path(g, 1, 300, 300, 40, 3, 0, 100.0, 0.015)      # 120 px in 0.6 s
    g.touch_up(1, t + 0.01)
    assert len(moves(b.log)) > 20 and not clicks(b.log)


def test_resting_finger_is_neither_a_click_nor_a_move():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 301, 300, 100.2)
    g.touch_up(1, 100.6)                                          # held 0.6 s without travelling
    assert not clicks(b.log) and not moves(b.log), b.log


def test_a_slide_that_starts_after_a_pause_still_moves():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 301, 300, 100.1)
    for i in range(1, 11):                                        # 0.4 s after touchdown the finger slides
        g.touch_move(1, 301 + 5 * i, 300, 100.4 + 0.015 * i)
    g.touch_up(1, 100.6)
    assert len(moves(b.log)) >= 8 and not clicks(b.log)


def test_two_finger_tap_right_clicks_even_with_some_jitter():
    g, b = fresh(two_finger_right_click=True)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_down(2, 400, 300, 100.01)
    g.touch_move(1, 306, 304, 100.05)
    g.touch_move(2, 405, 303, 100.05)
    g.touch_up(1, 100.12)
    g.touch_up(2, 100.13)
    assert clicks(b.log) == [("click", E.BTN_RIGHT)], b.log


def test_tap_to_click_off_means_no_click():
    g, b = fresh(tap_to_click=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_up(1, 100.1)
    assert not clicks(b.log)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
