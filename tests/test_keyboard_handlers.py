#!/usr/bin/env python3
"""The real touch handlers of bin/thor_app.py driven by synthetic touches, with a fake virtual keyboard.

Needs gi (GTK) and pycairo because thor_app imports them: run it on the Thor (python3 tests/test_keyboard_handlers.py).
Elsewhere it prints "skip" and passes. It covers the 2026-10-09 review: a tapped Shift must reach the next key, a double
tap must lock Caps, a held Shift must cover every key, leaving the keyboard must release modifiers, and in split mode a
drag that crosses the split line must keep moving the pointer.
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))
try:
    import thor_app  # noqa: E402
except Exception as err:  # no GTK / cairo here
    print(f"skip: thor_app cannot be imported here ({type(err).__name__}: {err})")
    sys.exit(0)
import threading  # noqa: E402

import keyboard_settings  # noqa: E402
from keyboard_layout import KeyboardLayout  # noqa: E402
from modifiers import ModifierState  # noqa: E402
from burn_in import BurnInProtector  # noqa: E402

FAILED = []
SHIFT, CTRL, KEY_A, KEY_B = 42, 29, 30, 48


def check(name, cond, got=None):
    print(("ok " if cond else "FAIL ") + name + ("" if cond else f"  got {got!r}"))
    if not cond:
        FAILED.append(name)


class Bridge:
    def __init__(self):
        self.ev = []

    def key(self, code, down):
        self.ev.append((code, "down" if down else "up"))

    def tap_key(self, code, delay_s=0.02):
        self.ev.append((code, "tap"))

    def mouse_button(self, *a):
        pass


class Gesture:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("touch_"):
            return lambda *a: self.calls.append((name, a[0]))
        raise AttributeError(name)


def make(mode="keyboard"):
    app = thor_app.ThorApp.__new__(thor_app.ThorApp)
    app.mode = mode
    app.kb_layout = KeyboardLayout(0, thor_app.HEADER_HEIGHT, thor_app.SCREEN_WIDTH, thor_app.SCREEN_HEIGHT - thor_app.HEADER_HEIGHT)
    app.bridge, app.gesture = Bridge(), Gesture()
    app.burn_in = BurnInProtector()
    app.keyboard_cfg = dict(keyboard_settings.DEFAULTS)
    app.mods, app._touch_owner, app.input_lock = ModifierState(), {}, threading.RLock()
    app.held_key = app.held_key_tid = app.active_key_press = app.active_key_tid = None
    app.held_ui_button = app.held_ui_button_tid = app._slider_drag = None
    app.last_key_label, app.last_event_time, app.show_debug_hud, app.ui_hidden = "", 0.0, False, False
    app._repeat_stop, app._repeat_thread = threading.Event(), None
    app._start_key_repeat = lambda key: None
    app.drawing_area = types.SimpleNamespace(queue_draw=lambda: None)
    app.save_config = lambda: None
    app.update_mode_bounds()
    return app


def keys(app):
    return {k.label: k for row in app.kb_layout.rows for k in row}


def tap(app, label, tid, hold=False):
    k = keys(app)[label]
    thor_app.ThorApp._handle_touch_down(app, tid, k.x + k.w / 2, k.y + k.h / 2, 0.0)
    if not hold:
        thor_app.ThorApp._handle_touch_up(app, tid, 0.0)


def test_tapped_shift_reaches_the_next_key():
    app = make()
    tap(app, "Shift", 1)
    tap(app, "a", 2)
    check("shift down, a, shift up", app.bridge.ev == [(SHIFT, "down"), (KEY_A, "tap"), (SHIFT, "up")], app.bridge.ev)
    app.bridge.ev.clear()
    tap(app, "b", 3)
    check("the next letter has no shift", app.bridge.ev == [(KEY_B, "tap")], app.bridge.ev)


def test_double_tap_locks_caps_across_letters():
    app = make()
    tap(app, "Shift", 1)
    tap(app, "Shift", 2)
    tap(app, "a", 3)
    tap(app, "b", 4)
    check("caps lock is on", app.kb_layout.caps_lock)
    check("shift stays down across letters", app.bridge.ev == [(SHIFT, "down"), (KEY_A, "tap"), (KEY_B, "tap")], app.bridge.ev)


def test_held_shift_covers_two_letters():
    app = make()
    tap(app, "Shift", 1, hold=True)
    tap(app, "a", 2)
    tap(app, "b", 3)
    thor_app.ThorApp._handle_touch_up(app, 1, 0.0)
    check("held shift: down, a, b, up", app.bridge.ev == [(SHIFT, "down"), (KEY_A, "tap"), (KEY_B, "tap"), (SHIFT, "up")], app.bridge.ev)


def test_leaving_the_keyboard_releases_modifiers():
    app = make()
    tap(app, "Ctrl", 1)
    tap(app, "Ctrl", 2)  # locked
    app.bridge.ev.clear()
    thor_app.ThorApp.set_mode(app, "trackpad")
    check("ctrl goes up on the switch to trackpad", app.bridge.ev == [(CTRL, "up")], app.bridge.ev)
    check("nothing is left active", not app.mods.active("ctrl"))


def test_split_drag_across_the_line_keeps_moving_the_pointer():
    app = make("split")
    thor_app.ThorApp._handle_touch_down(app, 9, 600.0, 300.0, 0.0)   # trackpad half
    thor_app.ThorApp._handle_touch_move(app, 9, 600.0, 700.0, 0.1)   # into the keyboard half
    thor_app.ThorApp._handle_touch_up(app, 9, 0.2)
    check("the drag stays with the trackpad", app.gesture.calls == [("touch_down", 9), ("touch_move", 9), ("touch_up", 9)], app.gesture.calls)
    check("no key was typed", app.bridge.ev == [], app.bridge.ev)


def test_turning_shift_off_clears_its_highlight():
    app = make()
    tap(app, "Shift", 1)
    app.mods.last_tap["shift"] -= 10.0  # the handler reads the real clock: make the first tap long ago
    k = keys(app)["Shift"]
    thor_app.ThorApp._handle_touch_down(app, 2, k.x + k.w / 2, k.y + k.h / 2, 5.0)  # slow second tap: turns it off
    check("shift went up", app.bridge.ev[-1] == (SHIFT, "up"), app.bridge.ev)
    thor_app.ThorApp._handle_touch_up(app, 2, 5.1)
    check("no key is drawn pressed after the lift", app.active_key_press is None, app.active_key_press)
    check("shift is not drawn active", not app.kb_layout.shift_active and not app.kb_layout.caps_lock)


def _centre(button):
    key, x, w = next(b for b in thor_app.HEADER_BUTTONS if b[0] == button)
    return x + w / 2.0, thor_app.HEADER_BUTTON_Y + thor_app.HEADER_BUTTON_H / 2.0


def test_hide_button_blanks_the_ui_and_releases_modifiers():
    app = make()
    tap(app, "Ctrl", 1)
    tap(app, "Ctrl", 2)  # locked
    app.bridge.ev.clear()
    x, y = _centre("hide")
    thor_app.ThorApp._handle_touch_down(app, 5, x, y, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 5, 0.1)
    check("the UI is hidden", app.ui_hidden)
    check("the mode is kept for when the UI comes back", app.mode == "keyboard", app.mode)
    check("ctrl goes up on hiding", app.bridge.ev == [(CTRL, "up")], app.bridge.ev)


def test_hidden_screen_is_a_trackpad_except_the_open_button():
    app = make("keyboard")
    app.ui_hidden = True
    ox, oy, ow, oh = thor_app.OPEN_BUTTON
    check("the keyboard area is trackpad while hidden", app._owner_at(600.0, 800.0) == "trackpad")
    check("the old header area is trackpad while hidden", app._owner_at(300.0, 40.0) == "trackpad")
    check("the Open button is its own area", app._owner_at(ox + ow / 2, oy + oh / 2) == "open")
    check("a finger just off the Open button still opens", app._owner_at(ox - 10.0, oy + oh + 10.0) == "open")
    thor_app.ThorApp._handle_touch_down(app, 7, 600.0, 800.0, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 7, 0.1)
    check("a touch on the hidden screen moves the pointer, types nothing", app.gesture.calls == [("touch_down", 7), ("touch_up", 7)] and app.bridge.ev == [], (app.gesture.calls, app.bridge.ev))


def test_open_button_brings_the_ui_back():
    app = make("keyboard")
    app.ui_hidden = True
    ox, oy, ow, oh = thor_app.OPEN_BUTTON
    thor_app.ThorApp._handle_touch_down(app, 8, ox + ow / 2, oy + oh / 2, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 8, 0.1)
    check("the UI is back", not app.ui_hidden)
    check("the Open touch did not reach the pointer", app.gesture.calls == [], app.gesture.calls)
    check("the keyboard is where it was", app._owner_at(600.0, 800.0) == "keyboard")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
