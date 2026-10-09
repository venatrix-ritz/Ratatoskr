#!/usr/bin/env python3
"""Tests for bin/modifiers.py (no GTK, no device). Run: python tests/test_modifiers.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
from modifiers import ModifierState  # noqa: E402

SHIFT, CTRL = 42, 29
W = 0.35  # double-tap window
FAILED = []


def check(name, cond, got=None):
    print(("ok " if cond else "FAIL ") + name + ("" if cond else f"  got {got!r}"))
    if not cond:
        FAILED.append(name)


def test_tapped_shift_applies_to_the_next_key_only():
    m = ModifierState()
    ev = m.press("shift", 1, 0.0, W) + m.release(1)
    check("tap shift sends shift down and keeps it", ev == [(SHIFT, True)], ev)
    check("shift is latched after the tap", m.latched("shift"))
    m.key_typed()
    ev = m.key_released()
    check("the next key's release lets shift go", ev == [(SHIFT, False)], ev)
    check("shift is off afterwards", not m.active("shift"))
    m.key_typed()
    check("a second key gets no shift", m.key_released() == [])


def test_double_tap_locks_and_a_third_tap_unlocks():
    m = ModifierState()
    m.press("shift", 1, 0.0, W); m.release(1)
    ev = m.press("shift", 2, 0.2, W) + m.release(2)
    check("double tap locks without another down", ev == [] and m.locked("shift"), ev)
    for _ in range(3):
        m.key_typed()
        check("typing does not release a locked shift", m.key_released() == [])
    ev = m.press("shift", 3, 5.0, W) + m.release(3)
    check("tap while locked turns it off", ev == [(SHIFT, False)] and not m.active("shift"), ev)


def test_slow_second_tap_turns_latched_off():
    m = ModifierState()
    m.press("shift", 1, 0.0, W); m.release(1)
    ev = m.press("shift", 2, 1.0, W) + m.release(2)
    check("a tap after the window cancels the latch", ev == [(SHIFT, False)] and not m.active("shift"), ev)


def test_held_shift_covers_every_key_then_releases_with_the_finger():
    m = ModifierState()
    m.press("shift", 1, 0.0, W)
    for _ in range(2):
        m.key_typed()
        check("a held shift is not released by a key", m.key_released() == [])
    ev = m.release(1)
    check("lifting the shift finger after typing releases it", ev == [(SHIFT, False)] and not m.active("shift"), ev)


def test_ctrl_and_shift_together_and_release_all():
    m = ModifierState()
    m.press("ctrl", 1, 0.0, W); m.release(1)
    m.press("shift", 2, 0.1, W); m.release(2)
    m.key_typed()
    ev = sorted(m.key_released())
    check("both one-shot modifiers go up after the key", ev == sorted([(CTRL, False), (SHIFT, False)]), ev)
    m.press("ctrl", 3, 1.0, W); m.press("ctrl", 4, 1.1, W)  # locked
    ev = m.release_all()
    check("release_all lifts a locked ctrl", ev == [(CTRL, False)] and not m.active("ctrl"), ev)
    check("release_all with nothing active sends nothing", m.release_all() == [])


def test_zz_modifier_touch_tracking():
    m = ModifierState()
    m.press("alt", 7, 0.0, W)
    check("the finger on alt is a modifier touch", m.is_modifier_touch(7))
    m.release(7)
    check("after lifting it is not", not m.is_modifier_touch(7))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
