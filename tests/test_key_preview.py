#!/usr/bin/env python3
"""Key preview bubble geometry in bin/keyboard_layout.py (no GTK, no device). Run: python tests/test_key_preview.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import keyboard_layout as kl  # noqa: E402

FAILED = []
W, H = 1240.0, 1080.0  # bin/engine.py SCREEN_WIDTH / SCREEN_HEIGHT
KEYBOARD_TOP, SPLIT_TOP = 168.0, 500.0  # thor_app HEADER_HEIGHT and SPLIT_Y


def check(name, cond, got=None):
    print(("ok " if cond else "FAIL ") + name + ("" if cond else f"  got {got!r}"))
    if not cond:
        FAILED.append(name)


def layout(top):
    return kl.KeyboardLayout(0, top, W, H - top)


def key(kb, label):
    return next(k for row in kb.rows for k in row if k.label == label)


def on_screen(r):
    x, y, w, h = r
    m = kl.PREVIEW_MARGIN
    return x >= m - 1e-6 and y >= m - 1e-6 and x + w <= W - m + 1e-6 and y + h <= H - m + 1e-6


def overlaps(r, k):
    x, y, w, h = r
    return x < k.x + k.w and k.x < x + w and y < k.y + k.h and k.y < y + h


def test_only_character_keys_get_a_bubble():
    kb = layout(KEYBOARD_TOP)
    chars = {k.label for row in kb.rows for k in row if k.is_character}
    others = {k.label for row in kb.rows for k in row if not k.is_character}
    check("letters, digits and symbols", {"a", "q", "1", "`", "-", "/", ";", "\\"} <= chars, sorted(chars))
    check("no Space, Backspace, Enter, Tab, Esc, modifiers or arrows",
          others == {"Bksp", "Tab", "Esc", "Enter", "Shift", "Ctrl", "Alt", "Win", "Space", "Left", "Up", "Down", "Right"}, sorted(others))


def test_a_middle_key_gets_a_centred_bubble_above_it():
    k = key(layout(KEYBOARD_TOP), "g")
    x, y, w, h = kl.preview_rect(k, W, H)
    check("centred on the key", abs((x + w / 2) - (k.x + k.w / 2)) < 1e-6, (x, w, k.x, k.w))
    check("its bottom sits the gap above the key", abs((y + h) - (k.y - kl.PREVIEW_GAP)) < 1e-6, (y, h, k.y))
    check("wider than the key", w > k.w, (w, k.w))


def test_edge_keys_are_clamped_inside_the_screen():
    kb = layout(KEYBOARD_TOP)
    left = kl.preview_rect(key(kb, "`"), W, H)
    right = kl.preview_rect(key(kb, "\\"), W, H)
    check("the leftmost key's bubble starts at the margin", abs(left[0] - kl.PREVIEW_MARGIN) < 1e-6, left)
    check("the rightmost character key's bubble ends at the margin", abs(right[0] + right[2] - (W - kl.PREVIEW_MARGIN)) < 1e-6, right)
    check("both still above their keys", left[1] + left[3] <= key(kb, "`").y and right[1] + right[3] <= key(kb, "\\").y, (left, right))


def test_every_bubble_is_on_screen_and_clear_of_its_key_in_both_modes():
    for name, top in (("Keyboard", KEYBOARD_TOP), ("Split", SPLIT_TOP)):
        kb = layout(top)
        bad = [k.label for row in kb.rows for k in row if k.is_character
               and (not on_screen(kl.preview_rect(k, W, H)) or overlaps(kl.preview_rect(k, W, H), k))]
        check(f"{name} mode: on screen, above the finger", not bad, bad)


def test_a_top_row_with_no_room_above_goes_beside_the_key():
    kb = layout(0.0)  # keyboard flush with the top of the screen
    k = key(kb, "5")
    r = kl.preview_rect(k, W, H)
    check("on screen", on_screen(r), r)
    check("right of the key, clear of it", abs(r[0] - (k.x + k.w + kl.PREVIEW_GAP)) < 1e-6 and not overlaps(r, k), (r, k.x, k.w))
    edge = key(kb, "=")  # Backspace is to its right, but the bubble is wider than the room left before the edge
    edge.x = W - kl.PREVIEW_MARGIN - edge.w
    r = kl.preview_rect(edge, W, H)
    check("at the right edge it goes left of the key", abs(r[0] + r[2] - (edge.x - kl.PREVIEW_GAP)) < 1e-6 and on_screen(r), r)


def test_with_no_room_anywhere_it_covers_the_top_of_the_key():
    k = kl.Key("m", kl.KEY_M)
    k.x, k.y, k.w, k.h = kl.PREVIEW_MARGIN, 0.0, W - 2 * kl.PREVIEW_MARGIN, 80.0
    r = kl.preview_rect(k, W, H)
    check("on screen, over the key", on_screen(r) and overlaps(r, k) and abs(r[1] - kl.PREVIEW_MARGIN) < 1e-6, r)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
