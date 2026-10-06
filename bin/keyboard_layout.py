"""Keyboard layout, geometry, and keycode mappings for Thor on-screen keyboard."""
from __future__ import annotations

# Linux event keycodes from <linux/input-event-codes.h>
KEY_ESC = 1
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_6 = 7
KEY_7 = 8
KEY_8 = 9
KEY_9 = 10
KEY_0 = 11
KEY_MINUS = 12
KEY_EQUAL = 13
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_Q = 16
KEY_W = 17
KEY_E = 18
KEY_R = 19
KEY_T = 20
KEY_Y = 21
KEY_U = 22
KEY_I = 23
KEY_O = 24
KEY_P = 25
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_F = 33
KEY_G = 34
KEY_H = 35
KEY_J = 36
KEY_K = 37
KEY_L = 38
KEY_SEMICOLON = 39
KEY_APOSTROPHE = 40
KEY_GRAVE = 41
KEY_LEFTSHIFT = 42
KEY_BACKSLASH = 43
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_V = 47
KEY_B = 48
KEY_N = 49
KEY_M = 50
KEY_COMMA = 51
KEY_DOT = 52
KEY_SLASH = 53
KEY_RIGHTSHIFT = 54
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_CAPSLOCK = 58
KEY_UP = 103
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_DOWN = 108
KEY_LEFTMETA = 125
KEY_DELETE = 111


class Key:
    def __init__(
        self,
        label: str,
        code: int,
        rel_width: float = 1.0,
        shift_label: str | None = None,
        is_modifier: bool = False,
        special: str | None = None,
    ) -> None:
        self.label = label
        self.code = code
        self.rel_width = rel_width
        self.shift_label = shift_label if shift_label is not None else label.upper()
        self.is_modifier = is_modifier
        self.special = special
        self.is_letter = len(label) == 1 and label.isalpha()
        self.has_sub_symbol = shift_label is not None and shift_label != label.upper()
        self.x = 0.0
        self.y = 0.0
        self.w = 0.0
        self.h = 0.0


def create_qwerty_rows() -> list[list[Key]]:
    return [
        [
            Key("`", KEY_GRAVE, 1.0, "~"),
            Key("1", KEY_1, 1.0, "!"),
            Key("2", KEY_2, 1.0, "@"),
            Key("3", KEY_3, 1.0, "#"),
            Key("4", KEY_4, 1.0, "$"),
            Key("5", KEY_5, 1.0, "%"),
            Key("6", KEY_6, 1.0, "^"),
            Key("7", KEY_7, 1.0, "&"),
            Key("8", KEY_8, 1.0, "*"),
            Key("9", KEY_9, 1.0, "("),
            Key("0", KEY_0, 1.0, ")"),
            Key("-", KEY_MINUS, 1.0, "_"),
            Key("=", KEY_EQUAL, 1.0, "+"),
            Key("⌫", KEY_BACKSPACE, 1.5),
        ],
        [
            Key("Tab", KEY_TAB, 1.3),
            Key("q", KEY_Q, 1.0),
            Key("w", KEY_W, 1.0),
            Key("e", KEY_E, 1.0),
            Key("r", KEY_R, 1.0),
            Key("t", KEY_T, 1.0),
            Key("y", KEY_Y, 1.0),
            Key("u", KEY_U, 1.0),
            Key("i", KEY_I, 1.0),
            Key("o", KEY_O, 1.0),
            Key("p", KEY_P, 1.0),
            Key("[", KEY_LEFTBRACE, 1.0, "{"),
            Key("]", KEY_RIGHTBRACE, 1.0, "}"),
            Key("\\", KEY_BACKSLASH, 1.2, "|"),
        ],
        [
            Key("Esc", KEY_ESC, 1.2),
            Key("a", KEY_A, 1.0),
            Key("s", KEY_S, 1.0),
            Key("d", KEY_D, 1.0),
            Key("f", KEY_F, 1.0),
            Key("g", KEY_G, 1.0),
            Key("h", KEY_H, 1.0),
            Key("j", KEY_J, 1.0),
            Key("k", KEY_K, 1.0),
            Key("l", KEY_L, 1.0),
            Key(";", KEY_SEMICOLON, 1.0, ":"),
            Key("'", KEY_APOSTROPHE, 1.0, '"'),
            Key("Enter", KEY_ENTER, 2.3),
        ],
        [
            Key("⇧", KEY_LEFTSHIFT, 1.8, is_modifier=True, special="shift"),
            Key("z", KEY_Z, 1.0),
            Key("x", KEY_X, 1.0),
            Key("c", KEY_C, 1.0),
            Key("v", KEY_V, 1.0),
            Key("b", KEY_B, 1.0),
            Key("n", KEY_N, 1.0),
            Key("m", KEY_M, 1.0),
            Key(",", KEY_COMMA, 1.0, "<"),
            Key(".", KEY_DOT, 1.0, ">"),
            Key("/", KEY_SLASH, 1.0, "?"),
            Key("⇧", KEY_RIGHTSHIFT, 1.7, is_modifier=True, special="shift"),
        ],
        [
            Key("Ctrl", KEY_LEFTCTRL, 1.2, is_modifier=True, special="ctrl"),
            Key("Alt", KEY_LEFTALT, 1.2, is_modifier=True, special="alt"),
            Key("Win", KEY_LEFTMETA, 1.1, is_modifier=True, special="super"),
            Key("Space", KEY_SPACE, 5.0),
            Key("←", KEY_LEFT, 1.1),
            Key("↑", KEY_UP, 1.1),
            Key("↓", KEY_DOWN, 1.1),
            Key("→", KEY_RIGHT, 1.1),
        ],
    ]


class KeyboardLayout:
    """Calculates key positions and handles hit testing."""

    def __init__(self, x: float, y: float, width: float, height: float) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.rows = create_qwerty_rows()
        self.shift_active = False
        self.ctrl_active = False
        self.alt_active = False
        self.layout_keys()

    def update_bounds(self, x: float, y: float, width: float, height: float) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.layout_keys()

    def layout_keys(self) -> None:
        margin_x = 12.0
        margin_y = 10.0
        gap = 8.0
        avail_w = self.width - 2 * margin_x
        avail_h = self.height - 2 * margin_y

        num_rows = len(self.rows)
        row_h = (avail_h - (num_rows - 1) * gap) / num_rows

        cur_y = self.y + margin_y
        for row in self.rows:
            total_rel = sum(k.rel_width for k in row)
            num_keys = len(row)
            row_avail_w = avail_w - (num_keys - 1) * gap
            unit_w = row_avail_w / total_rel

            cur_x = self.x + margin_x
            for k in row:
                k.x = cur_x
                k.y = cur_y
                k.w = k.rel_width * unit_w
                k.h = row_h
                cur_x += k.w + gap

            cur_y += row_h + gap

    def hit_test(self, px: float, py: float) -> Key | None:
        if not (self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height):
            return None
        for row in self.rows:
            for k in row:
                if k.x <= px <= k.x + k.w and k.y <= py <= k.y + k.h:
                    return k
        return None
