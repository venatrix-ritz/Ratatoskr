#!/usr/bin/env python3
"""Tests for bin/keyboard_settings.py (no GTK, no device). Run: python tests/test_keyboard_settings.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import keyboard_settings as ks  # noqa: E402

FAILED = []


def check(name, cond):
    print(("ok " if cond else "FAIL ") + name)
    if not cond:
        FAILED.append(name)


def test_defaults_match_the_old_hard_coded_values():
    check("defaults are 350 / 60 / 350 ms",
          ks.DEFAULTS == {"keyboard_repeat_delay_ms": 350, "keyboard_repeat_interval_ms": 60, "keyboard_caps_window_ms": 350})


def test_values_are_clamped_to_the_limits():
    check("below the lowest becomes the lowest", ks.clamp("keyboard_repeat_delay_ms", 10) == 150)
    check("above the highest becomes the highest", ks.clamp("keyboard_repeat_interval_ms", 5000) == 200)
    check("a value inside the range is kept", ks.clamp("keyboard_caps_window_ms", 500) == 500)
    check("a float is rounded", ks.clamp("keyboard_repeat_delay_ms", 399.6) == 400)


def test_junk_gives_the_default():
    for junk in (None, "", "abc", [], {}, float("nan"), float("inf")):
        check(f"junk {junk!r} gives the default", ks.clamp("keyboard_repeat_delay_ms", junk) == 350)


def test_apply_only_touches_keyboard_keys():
    cfg = {"mode": "keyboard", "sensitivity": 1.5}
    ks.apply(cfg, {"keyboard_repeat_delay_ms": 9999, "sensitivity": 4.0, "other": 1})
    check("keyboard key written and clamped", cfg["keyboard_repeat_delay_ms"] == 800)
    check("other keys in the message are not copied", "other" not in cfg and cfg["sensitivity"] == 1.5)
    check("keys not in the message are not added", "keyboard_caps_window_ms" not in cfg)


def test_zz_every_limit_has_default_inside_range():
    for key, (default, low, high) in ks.LIMITS.items():
        check(f"{key} default inside {low}-{high}", low <= default <= high)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
