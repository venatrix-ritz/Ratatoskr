"""Keyboard timing settings for the on-screen keyboard: defaults, limits and clamping.

Kept free of GTK so it can be unit-tested anywhere (tests/test_keyboard_settings.py). The defaults are the values that
were hard-coded in bin/thor_app.py before 2026-10-09, so behaviour does not change until a setting is touched.
"""
from __future__ import annotations

# key -> (default, lowest, highest), all in milliseconds
LIMITS: dict[str, tuple[int, int, int]] = {
    "keyboard_repeat_delay_ms": (350, 150, 800),     # hold time before a held key starts repeating
    "keyboard_repeat_interval_ms": (60, 20, 200),    # time between repeats once it has started
    "keyboard_caps_window_ms": (350, 150, 800),      # a second Shift tap within this time turns on Caps Lock
}

DEFAULTS: dict[str, int] = {key: spec[0] for key, spec in LIMITS.items()}


def clamp(key: str, value) -> int:
    """Return value as an int inside the key's limits; a value that is not a number gives the default."""
    default, low, high = LIMITS[key]
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError, OverflowError):
        return default


def apply(cfg: dict, msg: dict) -> dict:
    """Copy the keyboard keys found in msg into cfg (clamped) and return cfg. Other keys in msg are ignored."""
    for key in LIMITS:
        if key in msg:
            cfg[key] = clamp(key, msg[key])
    return cfg
