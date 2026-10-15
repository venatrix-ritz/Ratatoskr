"""Tests for the AMOLED palette module (run: python tests/test_theme.py)."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import theme  # noqa: E402


def _colours():
    for name, value in sorted(vars(theme).items()):
        if name.isupper() and isinstance(value, tuple):
            yield name, value


def test_every_colour_is_three_channels_in_range():
    found = list(_colours())
    assert found, "theme.py defines no colour tuples"
    for name, value in found:
        assert len(value) == 3, f"{name} has {len(value)} channels"
        assert all(0.0 <= c <= 1.0 for c in value), f"{name} out of range: {value}"


def test_background_is_pure_black():
    assert theme.BG == (0.0, 0.0, 0.0)


def test_every_theme_name_used_in_the_app_exists():
    used = set()
    for folder in ("bin", "tests"):
        for dirpath, _, files in os.walk(os.path.join(ROOT, folder)):
            for fname in files:
                if fname.endswith(".py"):
                    with open(os.path.join(dirpath, fname), encoding="utf-8") as f:
                        used.update(re.findall(r"\btheme\.([A-Z][A-Z0-9_]*)\b", f.read()))
    missing = sorted(name for name in used if not hasattr(theme, name))
    assert not missing, f"app uses theme names that theme.py does not define: {missing}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
