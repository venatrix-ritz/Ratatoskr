"""Pen mode has three settings: off, pen, and pen_plus.

pen      one pointer, no gestures, edge strips scroll, double-tap clicks, hold right-clicks. The driver nudges the
         pointer before a scroll or press so Game Mode's 3 s pointer auto-hide cannot swallow it.
pen_plus pen, plus Game Mode's pointer-visible override (session_cursor.py), so the nudges are not needed. The
         override is a gamescope launch argument and applies the next time Game Mode starts.
"""
from __future__ import annotations

MODES = ("off", "pen", "pen_plus")


def normalize(value) -> str:
    return value if value in MODES else "off"


def cycle(mode) -> str:
    """The next mode when the Pen button is tapped: off, pen, pen +, off..."""
    return MODES[(MODES.index(normalize(mode)) + 1) % len(MODES)]


def initial(cfg: dict, override_configured: bool) -> str:
    """The mode to start in. A config saved before this setting existed only has stylus_mode; if the earlier
    "Keep the pointer visible" switch had written the override file, that was Pen +."""
    if "pen_mode" in cfg:
        return normalize(cfg["pen_mode"])
    if cfg.get("stylus_mode"):
        return "pen_plus" if override_configured else "pen"
    return "off"


def engine_flag(mode) -> bool:
    return normalize(mode) != "off"


def wants_override(mode) -> bool:
    return normalize(mode) == "pen_plus"


def label(mode) -> str:
    return "Pen +" if normalize(mode) == "pen_plus" else "Pen"
