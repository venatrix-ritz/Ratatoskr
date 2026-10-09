#!/usr/bin/env python3
"""Render the on-screen keyboard labels to PNG files for a visual check (needs pycairo; the Thor has it).

Usage: python tests/render_keyboard.py OUT_DIR
Writes keyboard-full.png, keyboard-full-shift.png, keyboard-split.png, keyboard-split-shift.png. The key boxes are
simplified; the labels use the same bin/key_render.py code as the driver. Not a unit test (the name keeps it out of
the test runs).
"""
import os
import sys

import cairo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import key_render  # noqa: E402
from keyboard_layout import KeyboardLayout  # noqa: E402

W, H, HEADER = 1240, 1080, 92.0   # bin/engine.py SCREEN_WIDTH / SCREEN_HEIGHT, thor_app HEADER_HEIGHT
ARROWS = (105, 103, 108, 106)


def rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def render(path, top, shift_on):
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0.04, 0.05, 0.07)
    cr.paint()
    kb = KeyboardLayout(0, top, W, H - top)
    for row in kb.rows:
        for k in row:
            rrect(cr, k.x, k.y, k.w, k.h, 10.0)
            cr.set_source_rgb(0.10, 0.11, 0.15)
            cr.fill_preserve()
            cr.set_source_rgb(0.22, 0.25, 0.32)
            cr.set_line_width(1.0)
            cr.stroke()
            cr.new_path()
            if k.has_sub_symbol:
                key_render.draw_dual_label(cr, k, shift_on, False)
            elif k.code in ARROWS:
                continue
            else:
                label = k.shift_label if shift_on and k.is_letter else k.label
                key_render.draw_plain_label(cr, k, label, False, shift_on and k.is_letter)
    surf.write_to_png(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for name, top in (("full", HEADER), ("split", 500.0)):
        for shift in (False, True):
            render(os.path.join(out, f"keyboard-{name}{'-shift' if shift else ''}.png"), top, shift)
    print("wrote 4 PNGs to", out)
