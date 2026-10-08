#!/usr/bin/env python3
"""Touch Master Standalone Manager & Control App for Plasma Mobile & Desktop.

Provides a standalone GUI control panel and CLI interface to monitor,
start, stop, and configure the Touch Master bottom-screen input driver
independent of Decky Loader.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

# Fix environment for systemd user session if invoked from environments lacking them
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
    bus_path = f"/run/user/{os.getuid()}/bus"
    if os.path.exists(bus_path):
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"

SOCKET_PATH = f"/run/user/{os.getuid()}/thor-input.sock"
CONFIG_PATH = Path(os.path.expanduser("~/.config/thor-input/config.json"))
SERVICE_NAME = "touch-master.service"
STOCK_BOTTOM_SERVICE = "armada-bottom-screen.service"

DEFAULT_CONFIG = {
    "enabled": True,
    "mode": "trackpad",
    "sensitivity": 1.5,
    "glide": False,
    "friction": 7,
    "scroll_speed": 3,
    "tap_to_click": True,
    "long_press_right_click": False,
    "long_press_delay_ms": 450,
    "two_finger_right_click": True,
    "three_finger_middle_click": False,
    "pinch_zoom_enabled": False,
    "three_finger_swipe_enabled": False,
    "drag_lock_enabled": False,
    "mirror_dim": False,
    "mirror_dim_floor_percent": 3,
    "debug_hud": False,
}


def read_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def send_ipc(request: dict, timeout: float = 0.5) -> dict:
    if not os.path.exists(SOCKET_PATH):
        return {"ok": False, "error": "Socket not found"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(SOCKET_PATH)
            s.sendall(json.dumps(request).encode("utf-8"))
            data = s.recv(4096)
            if not data:
                return {"ok": False, "error": "Empty response"}
            return json.loads(data.decode("utf-8"))
    except Exception as err:
        return {"ok": False, "error": str(err)}


def is_service_active() -> bool:
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        return res.stdout.strip() == "active"
    except Exception:
        return False


def start_service() -> bool:
    cfg = read_config()
    cfg["enabled"] = True
    save_config(cfg)
    try:
        subprocess.run(["systemctl", "--user", "disable", STOCK_BOTTOM_SERVICE], check=False, timeout=3.0)
        subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=False, timeout=3.0)
        res = subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=False, timeout=3.0)
        return res.returncode == 0
    except Exception:
        return False


def stop_service() -> bool:
    cfg = read_config()
    cfg["enabled"] = False
    save_config(cfg)
    try:
        res = subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=False, timeout=3.0)
        subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=False, timeout=3.0)
        # Restore stock Armada bottom screen session
        subprocess.run(["systemctl", "--user", "enable", STOCK_BOTTOM_SERVICE], check=False, timeout=3.0)
        subprocess.run(["systemctl", "--user", "start", STOCK_BOTTOM_SERVICE], check=False, timeout=3.0)
        return res.returncode == 0
    except Exception:
        return False


def toggle_service() -> bool:
    if is_service_active():
        return stop_service()
    else:
        return start_service()


def launch_gui() -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    class TouchMasterWindow(Gtk.Window):
        def __init__(self):
            super().__init__(title="Touch Master")
            self.set_default_size(520, 680)
            self.set_position(Gtk.WindowPosition.CENTER)
            self.set_border_width(16)

            self.updating_ui = False
            self.cfg = read_config()

            # Main vertical container with scroll
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.add(scrolled)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            scrolled.add(vbox)

            # Header Card: Title, Status Badge & Toggle
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            vbox.pack_start(header_box, False, False, 0)

            title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title_lbl = Gtk.Label()
            title_lbl.set_markup("<span size='x-large' weight='bold'>Touch Master</span>")
            title_lbl.set_xalign(0)
            title_box.pack_start(title_lbl, False, False, 0)

            self.status_lbl = Gtk.Label()
            self.status_lbl.set_xalign(0)
            title_box.pack_start(self.status_lbl, False, False, 0)
            header_box.pack_start(title_box, True, True, 0)

            self.toggle_btn = Gtk.Button()
            self.toggle_btn.connect("clicked", self.on_toggle_clicked)
            header_box.pack_end(self.toggle_btn, False, False, 0)

            vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

            # Mode Selector Card
            mode_frame = Gtk.Frame(label=" Bottom Screen Input Mode ")
            mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            mode_box.set_border_width(10)
            mode_frame.add(mode_box)
            vbox.pack_start(mode_frame, False, False, 0)

            self.btn_trackpad = Gtk.RadioButton.new_with_label(None, "Trackpad")
            self.btn_keyboard = Gtk.RadioButton.new_with_label_from_widget(self.btn_trackpad, "Keyboard")
            self.btn_settings = Gtk.RadioButton.new_with_label_from_widget(self.btn_trackpad, "Quick Controls")

            self.btn_trackpad.connect("toggled", lambda b: self.on_mode_toggled(b, "trackpad"))
            self.btn_keyboard.connect("toggled", lambda b: self.on_mode_toggled(b, "keyboard"))
            self.btn_settings.connect("toggled", lambda b: self.on_mode_toggled(b, "settings"))

            mode_box.pack_start(self.btn_trackpad, True, True, 0)
            mode_box.pack_start(self.btn_keyboard, True, True, 0)
            mode_box.pack_start(self.btn_settings, True, True, 0)

            # Dynamics & Gestures Frame
            dyn_frame = Gtk.Frame(label=" Pointer & Gestures ")
            dyn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            dyn_box.set_border_width(10)
            dyn_frame.add(dyn_box)
            vbox.pack_start(dyn_frame, False, False, 0)

            # Sensitivity Slider
            sens_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            dyn_box.pack_start(sens_box, False, False, 0)
            self.sens_lbl = Gtk.Label(label=f"Sensitivity: {self.cfg.get('sensitivity', 1.5):.1f}x")
            self.sens_lbl.set_xalign(0)
            sens_box.pack_start(self.sens_lbl, True, True, 0)

            self.sens_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 3.0, 0.1)
            self.sens_scale.set_value(self.cfg.get("sensitivity", 1.5))
            self.sens_scale.set_size_request(240, -1)
            self.sens_scale.connect("value-changed", self.on_sensitivity_changed)
            sens_box.pack_end(self.sens_scale, False, False, 0)

            # Tap to click
            self.tap_click_switch = Gtk.Switch()
            self.tap_click_switch.set_active(self.cfg.get("tap_to_click", True))
            self.tap_click_switch.connect("notify::active", lambda s, p: self.on_cfg_switch(s, "tap_to_click"))
            tap_row = self._make_switch_row("Tap to Click", self.tap_click_switch)
            dyn_box.pack_start(tap_row, False, False, 0)

            # Two finger right click
            self.two_finger_switch = Gtk.Switch()
            self.two_finger_switch.set_active(self.cfg.get("two_finger_right_click", True))
            self.two_finger_switch.connect("notify::active", lambda s, p: self.on_cfg_switch(s, "two_finger_right_click"))
            two_row = self._make_switch_row("Two-Finger Tap Right Click", self.two_finger_switch)
            dyn_box.pack_start(two_row, False, False, 0)

            # Dim the bottom screen on Steam's idle-dim timer
            self.mirror_switch = Gtk.Switch()
            self.mirror_switch.set_active(self.cfg.get("mirror_dim", False))
            self.mirror_switch.connect("notify::active", lambda s, p: self.on_cfg_switch(s, "mirror_dim"))
            mirror_row = self._make_switch_row("Dim bottom screen with Steam's idle dim", self.mirror_switch)
            dyn_box.pack_start(mirror_row, False, False, 0)

            # Debug HUD
            self.hud_switch = Gtk.Switch()
            self.hud_switch.set_active(self.cfg.get("debug_hud", False))
            self.hud_switch.connect("notify::active", self.on_hud_toggled)
            hud_row = self._make_switch_row("Bottom Screen HUD Coordinates Overlay", self.hud_switch)
            dyn_box.pack_start(hud_row, False, False, 0)

            # Brightness Controls Frame
            bright_frame = Gtk.Frame(label=" Display Brightness ")
            bright_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            bright_box.set_border_width(10)
            bright_frame.add(bright_box)
            vbox.pack_start(bright_frame, False, False, 0)

            top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            bright_box.pack_start(top_box, False, False, 0)
            self.top_lbl = Gtk.Label(label="Top Screen: 100%")
            self.top_lbl.set_xalign(0)
            top_box.pack_start(self.top_lbl, True, True, 0)
            self.top_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
            self.top_scale.set_value(100)
            self.top_scale.set_size_request(240, -1)
            self.top_scale.connect("value-changed", lambda s: self.on_brightness_changed("top", s))
            top_box.pack_end(self.top_scale, False, False, 0)

            bot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            bright_box.pack_start(bot_box, False, False, 0)
            self.bot_lbl = Gtk.Label(label="Bottom Screen: 100%")
            self.bot_lbl.set_xalign(0)
            bot_box.pack_start(self.bot_lbl, True, True, 0)
            self.bot_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
            self.bot_scale.set_value(100)
            self.bot_scale.set_size_request(240, -1)
            self.bot_scale.connect("value-changed", lambda s: self.on_brightness_changed("bottom", s))
            bot_box.pack_end(self.bot_scale, False, False, 0)

            # Telemetry Frame
            telem_frame = Gtk.Frame(label=" Hardware Health & Telemetry ")
            self.telem_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.telem_box.set_border_width(10)
            telem_frame.add(self.telem_box)
            vbox.pack_start(telem_frame, False, False, 0)

            self.hw_lbl = Gtk.Label()
            self.hw_lbl.set_xalign(0)
            self.telem_box.pack_start(self.hw_lbl, False, False, 0)

            self.stats_lbl = Gtk.Label()
            self.stats_lbl.set_xalign(0)
            self.telem_box.pack_start(self.stats_lbl, False, False, 0)

            # Initial status refresh and periodic timer
            self.refresh_status()
            GLib.timeout_add(1000, self.refresh_status)

        def _make_switch_row(self, label_text: str, switch: Gtk.Switch) -> Gtk.Box:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=label_text)
            lbl.set_xalign(0)
            row.pack_start(lbl, True, True, 0)
            row.pack_end(switch, False, False, 0)
            return row

        def refresh_status(self) -> bool:
            active = is_service_active()
            self.updating_ui = True

            if active:
                self.status_lbl.set_markup("<span color='#2ecc71' weight='bold'>● Running</span> (Driver Active on Bottom Screen)")
                self.toggle_btn.set_label("Stop Driver")
                res = send_ipc({"action": "get_status"})
                debug_info = send_ipc({"action": "get_debug"})

                if res.get("ok"):
                    mode = res.get("mode", "trackpad")
                    if mode == "trackpad":
                        self.btn_trackpad.set_active(True)
                    elif mode == "keyboard":
                        self.btn_keyboard.set_active(True)
                    elif mode == "settings":
                        self.btn_settings.set_active(True)

                    hw = res.get("hardware_stats", {})
                    self.hw_lbl.set_markup(
                        f"<b>Battery:</b> {hw.get('bat_cap', 0)}% ({hw.get('bat_watts', 0)}W) | "
                        f"<b>CPU:</b> {hw.get('cpu_load', 0)}% ({hw.get('cpu_temp', 0)}°C) | "
                        f"<b>GPU:</b> {hw.get('gpu_mhz', 0)}MHz ({hw.get('gpu_temp', 0)}°C)"
                    )
                    top_b = hw.get("top_bright_pct", 100)
                    bot_b = hw.get("bot_bright_pct", 100)
                    self.top_lbl.set_text(f"Top Screen: {top_b}%")
                    self.bot_lbl.set_text(f"Bottom Screen: {bot_b}%")

                telem = debug_info.get("telemetry", {})
                self.stats_lbl.set_markup(
                    f"<b>Input Moves:</b> {telem.get('mouse_moves', 0)} | "
                    f"<b>Scrolls:</b> {telem.get('scrolls', 0)} | "
                    f"<b>Clicks:</b> {(telem.get('clicks_left', 0) + telem.get('clicks_right', 0))} | "
                    f"<b>Keystrokes:</b> {telem.get('keystrokes', 0)}"
                )
            else:
                self.status_lbl.set_markup("<span color='#95a5a6'>○ Stopped</span> (Bottom Screen Driver Inactive)")
                self.toggle_btn.set_label("Start Driver")
                self.hw_lbl.set_text("Driver is inactive. Click 'Start Driver' to activate bottom screen trackpad.")
                self.stats_lbl.set_text("")

            self.updating_ui = False
            return True

        def on_toggle_clicked(self, _btn):
            if is_service_active():
                stop_service()
            else:
                start_service()
            self.refresh_status()

        def on_mode_toggled(self, btn, mode: str):
            if btn.get_active() and not self.updating_ui:
                self.cfg["mode"] = mode
                save_config(self.cfg)
                send_ipc({"action": "set_mode", "mode": mode})

        def on_sensitivity_changed(self, scale):
            if self.updating_ui:
                return
            val = round(scale.get_value(), 1)
            self.sens_lbl.set_text(f"Sensitivity: {val:.1f}x")
            self.cfg["sensitivity"] = val
            save_config(self.cfg)
            send_ipc({"action": "set_settings", "settings": {"sensitivity": val}})

        def on_cfg_switch(self, switch, key: str):
            if self.updating_ui:
                return
            active = switch.get_active()
            self.cfg[key] = active
            save_config(self.cfg)
            send_ipc({"action": "set_settings", "settings": {key: active}})

        def on_hud_toggled(self, switch, _param):
            if self.updating_ui:
                return
            active = switch.get_active()
            self.cfg["debug_hud"] = active
            save_config(self.cfg)
            send_ipc({"action": "set_debug_hud", "enabled": active})

        def on_brightness_changed(self, target: str, scale):
            if self.updating_ui:
                return
            pct = int(scale.get_value())
            if target == "top":
                self.top_lbl.set_text(f"Top Screen: {pct}%")
            else:
                self.bot_lbl.set_text(f"Bottom Screen: {pct}%")
            send_ipc({"action": "set_brightness", "target": target, "percent": pct})

    win = TouchMasterWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


def main():
    parser = argparse.ArgumentParser(description="Touch Master Standalone Driver Manager")
    parser.add_argument("--start", action="store_true", help="Start and enable Touch Master service")
    parser.add_argument("--stop", action="store_true", help="Stop and disable Touch Master service")
    parser.add_argument("--toggle", action="store_true", help="Toggle Touch Master service on/off")
    parser.add_argument("--status", action="store_true", help="Query service and driver status")
    parser.add_argument("--mode", choices=["trackpad", "keyboard", "settings"], help="Switch input mode")
    args = parser.parse_args()

    if args.start:
        ok = start_service()
        print("Started" if ok else "Failed to start")
        sys.exit(0 if ok else 1)
    elif args.stop:
        ok = stop_service()
        print("Stopped" if ok else "Failed to stop")
        sys.exit(0 if ok else 1)
    elif args.toggle:
        ok = toggle_service()
        print("Toggled" if ok else "Failed to toggle")
        sys.exit(0 if ok else 1)
    elif args.status:
        active = is_service_active()
        cfg = read_config()
        ipc = send_ipc({"action": "get_status"})
        print(json.dumps({"service_active": active, "config": cfg, "ipc": ipc}, indent=2))
        sys.exit(0)
    elif args.mode:
        cfg = read_config()
        cfg["mode"] = args.mode
        save_config(cfg)
        res = send_ipc({"action": "set_mode", "mode": args.mode})
        print(json.dumps(res, indent=2))
        sys.exit(0)
    else:
        launch_gui()


if __name__ == "__main__":
    main()
