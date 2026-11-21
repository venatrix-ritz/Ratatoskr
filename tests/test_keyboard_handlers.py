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
import time  # noqa: E402

import keyboard_settings  # noqa: E402
import ps_pad  # noqa: E402
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

    def ps_touch(self, x, y):
        self.ev.append(("ps_touch",))

    def ps_touch_up(self):
        self.ev.append(("ps_lift",))


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
    app.last_key_label, app.last_event_time, app.ui_hidden = "", 0.0, False
    app._repeat_stop, app._repeat_thread = threading.Event(), None
    app._start_key_repeat = lambda key: None
    app.drawing_area = types.SimpleNamespace(queue_draw=lambda: None)
    app.save_config = lambda: None
    app.ps = ps_pad.PsPad(app.bridge, ps_pad.PsLayout(thor_app.HEADER_HEIGHT, thor_app.SCREEN_WIDTH, thor_app.SCREEN_HEIGHT))
    app.buzzes = []
    app.haptics = types.SimpleNamespace(pulse=lambda: app.buzzes.append(1), enabled=True, available=True)
    app.ps.on_press = app._haptic
    app.ps_cfg, app._ps_return_mode = {"ps_mode_auto": True, "ps_touch_rotation": 0}, "trackpad"
    app.ps_focus = types.SimpleNamespace(focused_app=None)
    app.logger = types.SimpleNamespace(log=lambda *a: None)
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


def _centre(button, app=None):
    layout = app._header_buttons() if app is not None else thor_app.HEADER_BUTTONS
    key, x, w = next(b for b in layout if b[0] == button)
    return x + w / 2.0, thor_app.HEADER_BUTTON_Y + thor_app.HEADER_BUTTON_H / 2.0


def header_tap(app, button, tid):
    x, y = _centre(button, app)
    thor_app.ThorApp._handle_touch_down(app, tid, x, y, 0.0)
    thor_app.ThorApp._handle_touch_up(app, tid, 0.1)


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


def ps_point(app, name):
    lay = app.ps.layout
    if name == "pad":
        return lay.pad_x + lay.pad_w / 2, lay.pad_y + lay.pad_h / 2
    _n, _l, bx, bw = next(b for b in lay.buttons if b[0] == name)
    return bx + bw / 2, lay.button_y + lay.button_h / 2


def test_chiaki_focus_switches_to_ps_mode_and_back():
    app = make("split")
    app._on_chiaki_focus(True)
    check("Chiaki focus turns PS mode on", app.mode == "ps" and app.ps.active, app.mode)
    app._on_chiaki_focus(False)
    check("losing focus goes back to split", app.mode == "split" and not app.ps.active, app.mode)


def test_auto_off_keeps_the_mode():
    app = make("trackpad")
    app.ps_cfg["ps_mode_auto"] = False
    app._on_chiaki_focus(True)
    check("ps_mode_auto off: the mode stays", app.mode == "trackpad", app.mode)


def test_ps_mode_sends_pad_touches_to_the_ps_device_not_the_pointer():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    x, y = ps_point(app, "pad")
    thor_app.ThorApp._handle_touch_down(app, 1, x, y, 0.0)
    thor_app.ThorApp._handle_touch_move(app, 1, x + 40, y, 0.05)
    thor_app.ThorApp._handle_touch_up(app, 1, 0.1)
    check("touch, nudge, move, lift", app.bridge.ev == [("ps_touch",)] * 3 + [("ps_lift",)], app.bridge.ev)
    check("the pointer got nothing", app.gesture.calls == [], app.gesture.calls)


def test_ps_buttons_send_chiaki_keys():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 2, *ps_point(app, "ps"), 0.0)
    thor_app.ThorApp._handle_touch_up(app, 2, 0.1)
    check("PS = Esc down, up", app.bridge.ev == [(1, "down"), (1, "up")], app.bridge.ev)


def test_entering_ps_mode_releases_a_latched_ctrl():
    app = make("keyboard")
    tap(app, "Ctrl", 1)
    app.bridge.ev.clear()
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 2, *ps_point(app, "options"), 0.0)
    check("ctrl goes up before Options (Ctrl+O would open Chiaki's stream menu)", app.bridge.ev == [(CTRL, "up"), (24, "down")], app.bridge.ev)


def test_leaving_ps_mode_or_hiding_lifts_the_touch_and_keys():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 1, *ps_point(app, "pad"), 0.0)
    thor_app.ThorApp._handle_touch_down(app, 2, *ps_point(app, "options"), 0.0)
    app.bridge.ev.clear()
    thor_app.ThorApp.set_mode(app, "keyboard")
    check("mode change lifts the touch and the Options key", app.bridge.ev == [("ps_lift",), (24, "up")], app.bridge.ev)
    app = make("trackpad")
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 1, *ps_point(app, "pad"), 0.0)
    app.bridge.ev.clear()
    thor_app.ThorApp.set_ui_hidden(app, True)
    check("Hide lifts the touch", app.bridge.ev == [("ps_lift",)], app.bridge.ev)


def test_a_pad_tap_clicks_the_touchpad_then_lifts():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    x, y = ps_point(app, "pad")
    thor_app.ThorApp._handle_touch_down(app, 1, x, y, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 1, 0.05)
    check("touch, nudge, then T down with the touch still down", app.bridge.ev == [("ps_touch",), ("ps_touch",), (20, "down")], app.bridge.ev)
    time.sleep(ps_pad.TAP_CLICK_S + 0.1)
    check("then T up and the lift", app.bridge.ev[3:] == [(20, "up"), ("ps_lift",)], app.bridge.ev)


def test_keys_buttons_and_ps_buttons_buzz():
    app = make("keyboard")
    tap(app, "a", 1)
    check("a key buzzes once", app.buzzes == [1], app.buzzes)
    x = next(bx + bw / 2 for k, bx, bw in thor_app.HEADER_BUTTONS if k == "left")
    thor_app.ThorApp._handle_touch_down(app, 2, x, thor_app.HEADER_BUTTON_Y + 5, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 2, 0.1)
    check("a header button buzzes", app.buzzes == [1, 1], app.buzzes)
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 3, *ps_point(app, "options"), 0.0)
    thor_app.ThorApp._handle_touch_up(app, 3, 0.1)
    check("a PS button buzzes", app.buzzes == [1, 1, 1], app.buzzes)
    app.mode = "trackpad"
    app._touch_owner.clear()
    thor_app.ThorApp._handle_touch_down(app, 4, 600.0, 700.0, 0.0)
    check("a trackpad touch does not buzz by itself (the engine buzzes its clicks)", app.buzzes == [1, 1, 1], app.buzzes)


def test_the_ps_header_button_buzzes():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    header_tap(app, "trackpad", 1)
    app.buzzes.clear()
    header_tap(app, "ps", 2)
    check("the header PS button buzzes once and enters PS mode", app.buzzes == [1] and app.mode == "ps", (app.buzzes, app.mode))


def test_focus_loss_mid_touch_lifts_it_and_the_late_lift_does_nothing():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 1, *ps_point(app, "pad"), 0.0)
    app.bridge.ev.clear()
    app._on_chiaki_focus(False)
    thor_app.ThorApp._handle_touch_up(app, 1, 0.1)
    check("one lift, on the focus loss", app.bridge.ev == [("ps_lift",)], app.bridge.ev)


def test_the_ribbon_goes_to_quick_controls_and_back_to_ps():
    app = make("trackpad")
    app._on_chiaki_focus(True)
    thor_app.ThorApp._handle_touch_down(app, 3, 600.0, thor_app.HEADER_BUTTONS_H + 10, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 3, 0.1)
    check("ribbon opens Quick Controls", app.mode == "settings", app.mode)
    thor_app.ThorApp._handle_touch_down(app, 4, 600.0, thor_app.HEADER_BUTTONS_H + 10, 0.2)
    check("ribbon goes back to PS while Chiaki has focus", app.mode == "ps", app.mode)


def test_both_header_layouts_fit_and_hide_stays_under_the_open_button():
    for name, layout in (("default", thor_app.HEADER_BUTTONS), ("Chiaki focus", thor_app.HEADER_BUTTONS_PS)):
        gaps = [nx - (x + w) for (_k, x, w), (_n, nx, _w) in zip(layout, layout[1:])]
        check(f"{name}: buttons 8 px apart", gaps == [thor_app.HEADER_GAP] * (len(layout) - 1), gaps)
        check(f"{name}: the row spans 12..1228", layout[0][1] == 12 and layout[-1][1] + layout[-1][2] == thor_app.SCREEN_WIDTH - 12, layout)
        hide = next(b for b in layout if b[0] == "hide")
        check(f"{name}: Hide is where the Open button is", (hide[1], hide[2]) == (thor_app.OPEN_BUTTON[0], thor_app.OPEN_BUTTON[2]), hide)
    keys_default = [b[0] for b in thor_app.HEADER_BUTTONS]
    keys_ps = [b[0] for b in thor_app.HEADER_BUTTONS_PS]
    check("no PS button by default", "ps" not in keys_default, keys_default)
    check("with Chiaki focus: every button plus PS", keys_ps == keys_default[:3] + ["ps"] + keys_default[3:], keys_ps)
    right_side = ("left", "right", "pen", "hide")
    check("Left Click, Right Click, Pen and Hide do not move with Chiaki focus",
          [b for b in thor_app.HEADER_BUTTONS if b[0] in right_side] == [b for b in thor_app.HEADER_BUTTONS_PS if b[0] in right_side],
          (thor_app.HEADER_BUTTONS, thor_app.HEADER_BUTTONS_PS))


def test_the_bottom_screen_hud_is_gone():
    src = open(thor_app.__file__, encoding="utf-8").read()
    check("no HUD header button", all(b[0] != "hud" for b in thor_app.HEADER_BUTTONS + thor_app.HEADER_BUTTONS_PS))
    check("no toggle_hud action or HUD drawing", "toggle_hud" not in src and "_draw_debug_hud" not in src and "show_debug_hud" not in src)
    check("three Quick Controls buttons, 20 px apart, inside the 30 px margins",
          len(thor_app.QC_BUTTON_XS) == 3 and thor_app.QC_BUTTON_XS[0] == 30
          and thor_app.QC_BUTTON_XS[-1] + thor_app.QC_BUTTON_W == thor_app.SCREEN_WIDTH - 30
          and all(b - a == thor_app.QC_BUTTON_W + 20 for a, b in zip(thor_app.QC_BUTTON_XS, thor_app.QC_BUTTON_XS[1:])),
          (thor_app.QC_BUTTON_XS, thor_app.QC_BUTTON_W))


def test_the_quick_controls_buttons_act_and_buzz():
    app = make("settings")
    app.gesture.tap_to_click, app.gesture.two_finger_right_click, app.gesture.long_press_right_click = False, True, False
    y = thor_app.QC_BUTTONS_Y + thor_app.QC_BUTTONS_H / 2
    centre = [bx + thor_app.QC_BUTTON_W / 2 for bx in thor_app.QC_BUTTON_XS]
    thor_app.ThorApp._handle_settings_touch(app, 1, centre[0], y)
    check("Tap Click turns on", app.gesture.tap_to_click is True)
    thor_app.ThorApp._handle_settings_touch(app, 2, centre[1], y)
    check("right click goes to press-hold", (app.gesture.two_finger_right_click, app.gesture.long_press_right_click) == (False, True))
    thor_app.ThorApp._handle_settings_touch(app, 3, thor_app.QC_BUTTON_XS[1] - 10, y)
    check("the gap between buttons does nothing", app.buzzes == [1, 1] and app.mode == "settings", (app.buzzes, app.mode))
    thor_app.ThorApp._handle_settings_touch(app, 4, centre[2], y)
    check("Back to Trackpad", app.mode == "trackpad", app.mode)
    check("each button buzzed once", app.buzzes == [1, 1, 1], app.buzzes)


def test_the_ps_header_button_shows_only_while_chiaki_has_focus():
    app = make("trackpad")
    check("no PS button without focus", "ps" not in [b[0] for b in app._header_buttons()])
    _k, x, w = next(b for b in thor_app.HEADER_BUTTONS_PS if b[0] == "ps")
    thor_app.ThorApp._handle_touch_down(app, 1, x + w / 2, thor_app.HEADER_BUTTON_Y + 20, 0.0)
    thor_app.ThorApp._handle_touch_up(app, 1, 0.1)
    check("a tap where it would be does not enter PS mode", app.mode != "ps", app.mode)
    app = make("trackpad")
    app._on_chiaki_focus(True)
    check("the PS button shows with focus", "ps" in [b[0] for b in app._header_buttons()])
    app._on_chiaki_focus(False)
    check("and goes with the focus", "ps" not in [b[0] for b in app._header_buttons()])


def test_the_ps_header_button_returns_to_ps_and_keeps_the_return_mode():
    app = make("split")
    app._on_chiaki_focus(True)
    header_tap(app, "trackpad", 1)
    check("Trackpad leaves PS mode", app.mode == "trackpad", app.mode)
    header_tap(app, "ps", 2)
    check("one tap on PS brings PS mode back", app.mode == "ps", app.mode)
    check("the return mode is still split", app._ps_return_mode == "split", app._ps_return_mode)
    app._on_chiaki_focus(False)
    check("losing focus goes back to split", app.mode == "split", app.mode)


def test_with_auto_off_the_ps_button_returns_to_the_mode_held_at_focus():
    app = make("keyboard")
    app.ps_cfg["ps_mode_auto"] = False
    app._on_chiaki_focus(True)
    check("auto off: still the keyboard", app.mode == "keyboard", app.mode)
    header_tap(app, "ps", 1)
    check("the PS button enters PS mode", app.mode == "ps", app.mode)
    app._on_chiaki_focus(False)
    check("losing focus goes back to the keyboard", app.mode == "keyboard", app.mode)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
