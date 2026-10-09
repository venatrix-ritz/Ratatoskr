#!/usr/bin/env python3
"""Render every bottom-screen mode of the real drawing code (ThorApp._paint) to PNG, without a window or devices.

Usage (on the Thor, which has gi and pycairo): python3 tests/render_screens.py OUT_DIR
Writes screen-trackpad.png, screen-split.png, screen-keyboard.png, screen-keyboard-shift.png, screen-settings.png and
screen-trackpad-hud.png. Not a unit test (the name keeps it out of the test runs).
"""
import os
import sys
import time

import cairo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))
import thor_app  # noqa: E402
from engine import TouchGestureProcessor  # noqa: E402
from keyboard_layout import KeyboardLayout  # noqa: E402
from modifiers import ModifierState  # noqa: E402

STATS = {
    "bat_cap": 80, "bat_status": "Charging", "bat_watts": 12.4, "cpu_load": 23, "cpu_temp": 61, "cpu_ghz": 2.3,
    "gpu_mhz": 680, "gpu_temp": 55, "ram_used_gb": 5.1, "ram_total_gb": 15.1, "ram_pct": 34, "vol_pct": 45,
    "vol_muted": False, "top_bright_pct": 70, "bot_bright_pct": 60,
}


# gleipnir --status --json on the Thor, 2026-10-09, plus the service flag gleipnir_view adds
GLEIPNIR = {"clamp_value": 0, "node_max": 9000000, "verified": True, "capacity": 78, "status": "Discharging", "usb_online": 0,
            "current_ua": -642716, "temp_dc": 300, "limit": 9000000, "sleep_floor": 0, "service_active": True}


# battery / charger sysfs on the Thor, 2026-10-09 (on battery), and a charging variant on the 8.4 V PD charger
BATT = {"charge_now": "4856746", "charge_full": "6241000", "charge_full_design": "5938000", "cycle_count": "3",
        "voltage_now": "3994391", "current_now": "-1706951", "temp": "300", "health": "Good", "time_to_empty_avg": "12082",
        "capacity": "77", "usb_online": "0", "usb_type": "[Unknown] SDP DCP CDP ACA C PD PD_DRP PD_PPS BrickID"}
BATT_CHARGING = {**BATT, "current_now": "2400000", "charge_now": "4600000", "capacity": "74", "voltage_now": "4105000",
                 "usb_online": "1", "usb_type": "C [PD] PD_PPS", "usb_voltage_now": "8376000", "usb_input_current_limit": "3000000"}


class Stats:
    def get_stats(self):
        return dict(STATS)


class Bridge:
    def get_telemetry(self):
        return {"mouse_moves": 120, "clicks_left": 4, "clicks_right": 1, "scrolls": 9, "pointer_wakes": 2,
                "keystrokes": 30, "held_buttons": [], "held_keys": []}

    def __getattr__(self, name):  # any output call is a no-op here
        return lambda *a, **k: None


def make_app(mode, hud=False, shift=False, gleipnir=None):
    app = thor_app.ThorApp.__new__(thor_app.ThorApp)
    app.mode, app.show_debug_hud = mode, hud
    app.frame_count, app.last_fps_calc, app.fps = 0, time.time(), 60.0
    app.stats, app.bridge = Stats(), Bridge()
    app.gesture = TouchGestureProcessor(app.bridge)
    app.held_ui_button, app.pen_mode, app.touch_dev_node = None, "off", "/dev/input/event5"
    app.kb_layout = KeyboardLayout(0, thor_app.HEADER_HEIGHT, thor_app.SCREEN_WIDTH, thor_app.SCREEN_HEIGHT - thor_app.HEADER_HEIGHT)
    app.active_key_press, app.mods = None, ModifierState()
    app.gleipnir_cfg = {"gleipnir_ribbon": gleipnir is not None}
    app.gleipnir_status = gleipnir
    app.gleipnir_batt = dict(BATT_CHARGING if gleipnir and gleipnir.get("current_ua", 0) > 0 else BATT)
    app.gleipnir_events = [("11:24", "CLAMP at 80%"), ("15:18", "RELEASE (charger unplugged)")]
    app.update_mode_bounds()
    if shift:
        app.mods.press("shift", 1, 0.0, 0.35)
        app.mods.release(1)
        app._sync_modifier_flags = thor_app.ThorApp._sync_modifier_flags.__get__(app)
        app._sync_modifier_flags()
    return app


def render(app, path):
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, thor_app.SCREEN_WIDTH, thor_app.SCREEN_HEIGHT)
    app._paint(cairo.Context(surf))
    surf.write_to_png(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    shots = {
        "trackpad": make_app("trackpad"), "split": make_app("split"), "keyboard": make_app("keyboard"),
        "keyboard-shift": make_app("keyboard", shift=True), "settings": make_app("settings"),
        "trackpad-hud": make_app("trackpad", hud=True),
        "settings-gleipnir-charging": make_app("settings", gleipnir={**GLEIPNIR, "current_ua": 2400000, "usb_online": 1, "capacity": 74}),
        "trackpad-gleipnir-held": make_app("trackpad", gleipnir={**GLEIPNIR, "limit": 0, "capacity": 80, "usb_online": 1, "current_ua": 0}),
    }
    for name, app in shots.items():
        render(app, os.path.join(out, f"screen-{name}.png"))
    print(f"wrote {len(shots)} PNGs to {out}")
