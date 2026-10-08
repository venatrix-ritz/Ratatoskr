"""Tests for the three-way pen mode setting (run: python tests/test_pen_mode.py)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import pen_mode as pm  # noqa: E402


def test_the_button_cycles_off_pen_plus_and_back():
    assert pm.cycle("off") == "pen" and pm.cycle("pen") == "pen_plus" and pm.cycle("pen_plus") == "off"


def test_anything_unknown_is_off():
    assert pm.normalize(None) == "off" and pm.normalize("stylus") == "off" and pm.cycle("garbage") == "pen"


def test_a_saved_mode_wins():
    assert pm.initial({"pen_mode": "pen", "stylus_mode": False}, True) == "pen"
    assert pm.initial({"pen_mode": "bogus"}, True) == "off"


def test_an_older_config_is_migrated_from_stylus_mode_and_the_override_file():
    assert pm.initial({"stylus_mode": True}, False) == "pen"
    assert pm.initial({"stylus_mode": True}, True) == "pen_plus"      # the earlier switch had been turned on
    assert pm.initial({"stylus_mode": False}, True) == "off"
    assert pm.initial({}, False) == "off"


def test_only_pen_plus_wants_the_override_and_both_pens_turn_the_engine_on():
    assert [pm.wants_override(m) for m in pm.MODES] == [False, False, True]
    assert [pm.engine_flag(m) for m in pm.MODES] == [False, True, True]
    assert pm.label("pen_plus") == "Pen +" and pm.label("pen") == "Pen" and pm.label("off") == "Pen"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
