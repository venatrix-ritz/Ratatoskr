"""Key label drawing for the on-screen keyboard.

Pure cairo, no GTK, so the labels can be rendered to a PNG and checked off the device (tests/render_keyboard.py).
Sizes follow the key, not fixed pixel values: the bottom screen is 1240x1080 and keys are about 66-200 px, so the
earlier fixed 14 px / 11 px text was small and the main symbol of a two-symbol key sat near the bottom edge.
"""
from __future__ import annotations

import cairo

FACE = "Sans"
MAIN_MAX_PX = 34.0       # largest main label, for the biggest keys
MODIFIER_MAX_PX = 26.0   # multi-character labels (Ctrl, Enter, Backspace ...)
SUB_RATIO = 0.62         # corner symbol size relative to the main symbol
SUB_MIN_PX = 14.0
MARGIN_X = 8.0
MARGIN_Y = 6.0

WHITE = (1.0, 1.0, 1.0)
MAIN = (0.95, 0.96, 0.98)
SHIFTED = (0.40, 0.85, 1.0)
SUB = (0.66, 0.72, 0.84)     # brighter than the old (0.42, 0.48, 0.58), which was hard to read on the dark key


def _fit(cr: cairo.Context, text: str, max_size: float, max_w: float) -> cairo.TextExtents:
    """Select the bold face at max_size, shrink it if the text is wider than max_w, return its extents."""
    cr.select_font_face(FACE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(max_size)
    ext = cr.text_extents(text)
    if ext.x_advance > max_w > 0:
        cr.set_font_size(max_size * max_w / ext.x_advance)
        ext = cr.text_extents(text)
    return ext


def _cap_height(cr: cairo.Context) -> float:
    """Height of a capital H in the current font and size: the reference for a shared baseline."""
    return cr.text_extents("H").height


def _show_centered(cr: cairo.Context, text: str, cx: float, cy: float) -> None:
    """Draw text centred on (cx, cy): horizontally by its ink box, vertically by a shared baseline.

    Centring on each glyph's own ink box made letters with descenders (q, p, g, y, j) sit higher than flat ones.
    With the baseline fixed at cy + cap height / 2, every label of the same size lines up, and punctuation sits where
    it does in the font."""
    ext = cr.text_extents(text)
    cr.move_to(cx - (ext.x_bearing + ext.width / 2.0), cy + _cap_height(cr) / 2.0)
    cr.show_text(text)


def main_size(key) -> float:
    return max(12.0, min(key.h * 0.34, key.w * 0.50, MAIN_MAX_PX))


def draw_dual_label(cr: cairo.Context, key, shift_on: bool, is_active: bool) -> None:
    """Two-symbol key (1 / !): the symbol that will be typed is large and centred, the other is small in the corner."""
    prim, sub = (key.shift_label, key.label) if shift_on else (key.label, key.shift_label)

    _fit(cr, prim, main_size(key), key.w - 2 * MARGIN_X)
    cr.set_source_rgb(*(WHITE if is_active else SHIFTED if shift_on else MAIN))
    _show_centered(cr, prim, key.x + key.w / 2.0, key.y + key.h / 2.0)

    sub_size = max(SUB_MIN_PX, main_size(key) * SUB_RATIO)
    ext = _fit(cr, sub, sub_size, key.w * 0.35)
    cr.set_source_rgb(*SUB)
    # baseline = top margin + cap height, so '_' and '~' land where the font puts them
    cr.move_to(key.x + key.w - MARGIN_X - ext.x_advance, key.y + MARGIN_Y + _cap_height(cr))
    cr.show_text(sub)


def draw_plain_label(cr: cairo.Context, key, label: str, is_active: bool, tinted: bool) -> None:
    """Letter or modifier key: one label, centred."""
    limit = main_size(key) if len(label) == 1 else min(MODIFIER_MAX_PX, key.h * 0.24)
    _fit(cr, label, limit, key.w - 2 * MARGIN_X)
    cr.set_source_rgb(*(WHITE if is_active else SHIFTED if tinted else MAIN))
    _show_centered(cr, label, key.x + key.w / 2.0, key.y + key.h / 2.0)
