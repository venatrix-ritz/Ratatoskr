#!/usr/bin/env python3
"""Thor Input App: Bottom-screen GTK 3 interface with diagnostic telemetry & HUD."""
from __future__ import annotations

import fcntl
import glob
import json
import os
import select
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

# Add bin directory and parent directory to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR))
from debug_codes import DebugCode, DebugLogger, run_self_diagnostics
from engine import (
    ABS_MT_POSITION_X,
    ABS_MT_POSITION_Y,
    ABS_MT_SLOT,
    ABS_MT_TRACKING_ID,
    BTN_LEFT,
    BTN_RIGHT,
    EV_ABS,
    EV_SYN,
    EVENT_STRUCT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TouchGestureProcessor,
    UInputBridge,
    raw_to_screen,
)
from keyboard_layout import KeyboardLayout

SOCKET_PATH = f"/run/user/{os.getuid()}/thor-input.sock"
CONFIG_PATH = os.path.expanduser("~/.config/thor-input/config.json")
HEADER_HEIGHT = 64.0


class ThorApp:
    def __init__(self) -> None:
        self.logger = DebugLogger("app")
        self.logger.log(DebugCode.DAEMON_STARTING)

        self.mode = "trackpad"  # 'trackpad', 'split', 'keyboard'
        self.show_debug_hud = False
        self.touch_dev_node = ""

        # Bridge & processors
        self.bridge = UInputBridge(self.logger)
        self.gesture = TouchGestureProcessor(self.bridge, self.logger)
        self.kb_layout = KeyboardLayout(0, HEADER_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - HEADER_HEIGHT)
        self.held_ui_button: str | None = None
        self.active_key_press: int | None = None
        self.last_key_label = ""
        self.last_event_time = time.time()
        self.fps = 60.0
        self.frame_count = 0
        self.last_fps_calc = time.time()

        self.load_config()

        # Touch input thread
        self.touch_fd = -1
        self.touch_stop = threading.Event()
        self.touch_thread: threading.Thread | None = None

        # IPC server
        self.ipc_stop = threading.Event()
        self.ipc_thread: threading.Thread | None = None

        # UI Window
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Thor Input")
        self.window.set_default_size(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.window.fullscreen()
        self.window.connect("destroy", self.on_destroy)

        # Drawing Area
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.connect("draw", self.on_draw)
        self.window.add(self.drawing_area)

        self.update_mode_bounds()

    def load_config(self) -> None:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.mode = cfg.get("mode", self.mode)
                    self.show_debug_hud = cfg.get("debug_hud", self.show_debug_hud)
                    self.gesture.set_settings(
                        cfg.get("sensitivity", 1.5),
                        cfg.get("glide", True),
                    )
            except Exception as err:
                self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"load_config: {err}")

    def save_config(self) -> None:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            cfg = {
                "mode": self.mode,
                "sensitivity": self.gesture.sensitivity,
                "glide": self.gesture.glide_enabled,
                "debug_hud": self.show_debug_hud,
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as err:
            self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"save_config: {err}")

    def set_mode(self, mode: str) -> None:
        if mode not in ("trackpad", "split", "keyboard"):
            return
        self.mode = mode
        self.update_mode_bounds()
        self.save_config()
        GLib.idle_add(self.drawing_area.queue_draw)

    def update_mode_bounds(self) -> None:
        if self.mode == "keyboard":
            self.kb_layout.update_bounds(0, HEADER_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - HEADER_HEIGHT)
        elif self.mode == "split":
            split_y = 480.0
            self.kb_layout.update_bounds(0, split_y, SCREEN_WIDTH, SCREEN_HEIGHT - split_y)

    def start(self) -> None:
        self._start_touch_reader()
        self._start_ipc_server()
        self.window.show_all()
        self.logger.log(DebugCode.DAEMON_READY, f"Mode={self.mode}, Device={self.touch_dev_node}")

    def on_destroy(self, *_) -> None:
        self.cleanup()
        Gtk.main_quit()

    def cleanup(self) -> None:
        self.logger.log(DebugCode.DAEMON_STOPPING)
        self.touch_stop.set()
        self.ipc_stop.set()
        if self.touch_fd >= 0:
            try:
                EVIOCGRAB = (1 << 30) | (struct.calcsize("i") << 16) | (ord("E") << 8) | 0x90
                fcntl.ioctl(self.touch_fd, EVIOCGRAB, 0)
            except OSError:
                pass
            os.close(self.touch_fd)
            self.touch_fd = -1
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except OSError:
                pass
        self.bridge.close()
        self.logger.log(DebugCode.DAEMON_STOPPED)

    # -------------------------------------------------------------------------
    # Touch Event Processing
    # -------------------------------------------------------------------------

    def _find_touch_device(self) -> str | None:
        for name_file in glob.glob("/sys/class/input/event*/device/name"):
            try:
                with open(name_file, encoding="utf-8") as f:
                    if f.read().strip() == "bottom_touchscreen":
                        return "/dev/input/" + name_file.split("/")[4]
            except OSError:
                continue
        return None

    def _start_touch_reader(self) -> None:
        dev_path = self._find_touch_device()
        if not dev_path:
            self.logger.log(DebugCode.ERR_TOUCH_MISSING)
            return

        self.touch_dev_node = dev_path
        try:
            self.touch_fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
            EVIOCGRAB = (1 << 30) | (struct.calcsize("i") << 16) | (ord("E") << 8) | 0x90
            fcntl.ioctl(self.touch_fd, EVIOCGRAB, 1)
            self.logger.log(DebugCode.TOUCH_OK, f"Exclusively grabbed {dev_path}")
        except OSError as err:
            self.logger.log(DebugCode.ERR_TOUCH_GRAB, f"{dev_path}: {err}")
            return

        def _reader_loop():
            slot = 0
            raw: dict[int, list[int]] = {}
            tracking: dict[int, int] = {}
            active_contacts: dict[int, tuple[float, float]] = {}

            while not self.touch_stop.is_set():
                r, _, _ = select.select([self.touch_fd], [], [], 0.1)
                if not r:
                    continue
                try:
                    data = os.read(self.touch_fd, EVENT_STRUCT.size * 64)
                except (BlockingIOError, OSError):
                    continue

                for off in range(0, len(data) - EVENT_STRUCT.size + 1, EVENT_STRUCT.size):
                    sec, usec, etype, code, value = EVENT_STRUCT.unpack_from(data, off)
                    if etype == EV_ABS:
                        if code == ABS_MT_SLOT:
                            slot = value
                        elif code == ABS_MT_TRACKING_ID:
                            if value >= 0:
                                tracking[slot] = value
                            else:
                                tracking.pop(slot, None)
                        elif code in (ABS_MT_POSITION_X, ABS_MT_POSITION_Y):
                            raw.setdefault(slot, [0, 0])[code - ABS_MT_POSITION_X] = value
                    elif etype == EV_SYN and code == 0:
                        now = time.monotonic()
                        live: dict[int, tuple[float, float]] = {}
                        for s, tid in tracking.items():
                            raw_coords = raw.get(s, [0, 0])
                            live[tid] = raw_to_screen(raw_coords[0], raw_coords[1])

                        for tid in list(active_contacts.keys()):
                            if tid not in live:
                                active_contacts.pop(tid)
                                self._handle_touch_up(tid, now)

                        for tid, (sx, sy) in live.items():
                            if tid not in active_contacts:
                                active_contacts[tid] = (sx, sy)
                                self._handle_touch_down(tid, sx, sy, now)
                            else:
                                prev_sx, prev_sy = active_contacts[tid]
                                if (sx, sy) != (prev_sx, prev_sy):
                                    active_contacts[tid] = (sx, sy)
                                    self._handle_touch_move(tid, sx, sy, now)

        self.touch_thread = threading.Thread(target=_reader_loop, daemon=True)
        self.touch_thread.start()

    def _handle_touch_down(self, tid: int, x: float, y: float, now: float) -> None:
        self.last_event_time = time.time()
        if y < HEADER_HEIGHT:
            self._handle_header_touch(x, y, True)
            return

        if self.mode == "keyboard" or (self.mode == "split" and y >= 480.0):
            key = self.kb_layout.hit_test(x, y)
            if key:
                self.active_key_press = key.code
                self.last_key_label = key.label
                if key.special == "shift":
                    self.kb_layout.shift_active = not self.kb_layout.shift_active
                    self.bridge.key(key.code, self.kb_layout.shift_active)
                elif key.special in ("ctrl", "alt", "super"):
                    setattr(self.kb_layout, f"{key.special}_active", not getattr(self.kb_layout, f"{key.special}_active"))
                    self.bridge.key(key.code, getattr(self.kb_layout, f"{key.special}_active"))
                else:
                    self.bridge.tap_key(key.code)
                    if self.kb_layout.shift_active and not key.is_modifier:
                        self.kb_layout.shift_active = False
                        self.bridge.key(42, False)
                GLib.idle_add(self.drawing_area.queue_draw)
            return

        self.gesture.touch_down(tid, x, y, now)
        if self.show_debug_hud:
            GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_touch_move(self, tid: int, x: float, y: float, now: float) -> None:
        self.last_event_time = time.time()
        if y >= HEADER_HEIGHT:
            if self.mode == "trackpad" or (self.mode == "split" and y < 480.0):
                self.gesture.touch_move(tid, x, y, now)
                if self.show_debug_hud:
                    GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_touch_up(self, tid: int, now: float) -> None:
        self.last_event_time = time.time()
        if self.held_ui_button:
            if self.held_ui_button == "left":
                self.bridge.mouse_button(BTN_LEFT, False)
            elif self.held_ui_button == "right":
                self.bridge.mouse_button(BTN_RIGHT, False)
            self.held_ui_button = None
            GLib.idle_add(self.drawing_area.queue_draw)

        if self.active_key_press is not None:
            self.active_key_press = None
            GLib.idle_add(self.drawing_area.queue_draw)

        self.gesture.touch_up(tid, now)
        if self.show_debug_hud:
            GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_header_touch(self, x: float, y: float, down: bool) -> None:
        if 16 <= x <= 170:
            self.set_mode("trackpad")
        elif 180 <= x <= 320:
            self.set_mode("split")
        elif 330 <= x <= 490:
            self.set_mode("keyboard")
        elif 500 <= x <= 620:
            # HUD toggle button
            self.show_debug_hud = not self.show_debug_hud
            self.save_config()
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 750 <= x <= 920:
            self.held_ui_button = "left"
            self.bridge.mouse_button(BTN_LEFT, True)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 940 <= x <= 1110:
            self.held_ui_button = "right"
            self.bridge.mouse_button(BTN_RIGHT, True)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 1120 <= x <= 1220:
            self.window.close()

    # -------------------------------------------------------------------------
    # IPC Server for Decky Loader
    # -------------------------------------------------------------------------

    def _start_ipc_server(self) -> None:
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except OSError:
                pass

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(SOCKET_PATH)
        server_sock.listen(5)
        server_sock.settimeout(0.5)

        def _ipc_loop():
            while not self.ipc_stop.is_set():
                try:
                    conn, _ = server_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    try:
                        data = conn.recv(4096)
                        if not data:
                            continue
                        msg = json.loads(data.decode("utf-8"))
                        action = msg.get("action")
                        res = {"ok": True, "code": int(DebugCode.OK)}

                        if action == "get_status":
                            res["mode"] = self.mode
                            res["sensitivity"] = self.gesture.sensitivity
                            res["glide"] = self.gesture.glide_enabled
                            res["debug_hud"] = self.show_debug_hud
                        elif action == "get_debug":
                            res["telemetry"] = self.bridge.get_telemetry()
                            res["state"] = self.gesture.last_state_label
                            res["coords"] = self.gesture.last_coords
                            res["touch_device"] = self.touch_dev_node
                            res["active_fingers"] = len(self.gesture.active_contacts)
                            res["last_key"] = self.last_key_label
                        elif action == "set_mode":
                            self.set_mode(msg.get("mode", "trackpad"))
                        elif action == "set_settings":
                            self.gesture.set_settings(
                                msg.get("sensitivity", self.gesture.sensitivity),
                                msg.get("glide", self.gesture.glide_enabled),
                            )
                            if "debug_hud" in msg:
                                self.show_debug_hud = bool(msg["debug_hud"])
                            self.save_config()
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "toggle_hud":
                            self.show_debug_hud = not self.show_debug_hud
                            self.save_config()
                            res["debug_hud"] = self.show_debug_hud
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "run_diagnostics":
                            res["diagnostics"] = run_self_diagnostics()
                        elif action == "quit":
                            GLib.idle_add(self.window.close)
                        conn.sendall(json.dumps(res).encode("utf-8"))
                    except Exception as err:
                        self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, str(err))

            server_sock.close()

        self.ipc_thread = threading.Thread(target=_ipc_loop, daemon=True)
        self.ipc_thread.start()

    # -------------------------------------------------------------------------
    # Cairo Drawing (AMOLED UI + Debug HUD)
    # -------------------------------------------------------------------------

    def on_draw(self, _, cr: cairo.Context) -> bool:
        self.frame_count += 1
        now = time.time()
        if now - self.last_fps_calc >= 1.0:
            self.fps = self.frame_count / (now - self.last_fps_calc)
            self.frame_count = 0
            self.last_fps_calc = now

        # Pure Black Background
        cr.set_source_rgb(0, 0, 0)
        cr.paint()

        # Header Bar
        self._draw_header(cr)

        # Mode Contents
        if self.mode == "trackpad":
            self._draw_trackpad_surface(cr, HEADER_HEIGHT, SCREEN_HEIGHT - HEADER_HEIGHT)
        elif self.mode == "keyboard":
            self._draw_keyboard(cr)
        elif self.mode == "split":
            split_y = 480.0
            self._draw_trackpad_surface(cr, HEADER_HEIGHT, split_y - HEADER_HEIGHT)
            self._draw_keyboard(cr)

        # Live Debug HUD Overlay (when enabled)
        if self.show_debug_hud:
            self._draw_debug_hud(cr)

        return True

    def _draw_header(self, cr: cairo.Context) -> None:
        cr.set_source_rgb(0.12, 0.14, 0.18)
        cr.set_line_width(1.0)
        cr.move_to(0, HEADER_HEIGHT)
        cr.line_to(SCREEN_WIDTH, HEADER_HEIGHT)
        cr.stroke()

        self._draw_button(cr, 16, 10, 150, 44, "Trackpad", self.mode == "trackpad")
        self._draw_button(cr, 176, 10, 140, 44, "Split", self.mode == "split")
        self._draw_button(cr, 326, 10, 160, 44, "Keyboard", self.mode == "keyboard")

        # HUD Toggle Button
        hud_active = self.show_debug_hud
        self._draw_button(cr, 496, 10, 120, 44, "HUD", hud_active, accent_color=(0.15, 0.65, 0.45))

        # Click helper buttons
        left_active = self.held_ui_button == "left"
        right_active = self.held_ui_button == "right"
        self._draw_button(cr, 750, 10, 170, 44, "Left Click", left_active, accent_color=(0.3, 0.45, 0.95))
        self._draw_button(cr, 930, 10, 170, 44, "Right Click", right_active, accent_color=(0.85, 0.35, 0.35))
        self._draw_button(cr, 1120, 10, 95, 44, "✕ Close", False)

    def _draw_button(
        self,
        cr: cairo.Context,
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        active: bool,
        accent_color: tuple[float, float, float] = (0.38, 0.25, 0.85),
    ) -> None:
        radius = 12.0
        self._round_rect(cr, x, y, w, h, radius)
        if active:
            cr.set_source_rgb(*accent_color)
            cr.fill_preserve()
            cr.set_source_rgb(1.0, 1.0, 1.0)
        else:
            cr.set_source_rgb(0.08, 0.09, 0.12)
            cr.fill_preserve()
            cr.set_source_rgb(0.2, 0.22, 0.28)
            cr.set_line_width(1.5)
            cr.stroke()
            cr.set_source_rgb(0.85, 0.88, 0.92)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(18.0)
        extents = cr.text_extents(text)
        cr.move_to(x + (w - extents.width) / 2.0, y + (h + extents.height) / 2.0 - 2)
        cr.show_text(text)

    def _draw_trackpad_surface(self, cr: cairo.Context, y: float, h: float) -> None:
        margin = 24.0
        pad_x = margin
        pad_y = y + margin
        pad_w = SCREEN_WIDTH - 2 * margin
        pad_h = h - 2 * margin

        self._round_rect(cr, pad_x, pad_y, pad_w, pad_h, 20.0)
        cr.set_source_rgb(0.04, 0.04, 0.06)
        cr.fill_preserve()
        cr.set_source_rgb(0.15, 0.17, 0.22)
        cr.set_line_width(1.5)
        cr.stroke()

        cr.set_source_rgb(0.25, 0.28, 0.35)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(20.0)
        hint = "Trackpad: 1 finger moves · Tap clicks · 2 fingers scroll · Flick glides"
        extents = cr.text_extents(hint)
        cr.move_to(pad_x + (pad_w - extents.width) / 2.0, pad_y + (pad_h + extents.height) / 2.0)
        cr.show_text(hint)

    def _draw_keyboard(self, cr: cairo.Context) -> None:
        for row in self.kb_layout.rows:
            for k in row:
                is_active = self.active_key_press == k.code
                if k.special == "shift" and self.kb_layout.shift_active:
                    is_active = True
                elif k.special == "ctrl" and self.kb_layout.ctrl_active:
                    is_active = True
                elif k.special == "alt" and self.kb_layout.alt_active:
                    is_active = True

                self._round_rect(cr, k.x, k.y, k.w, k.h, 10.0)
                if is_active:
                    cr.set_source_rgb(0.38, 0.25, 0.85)
                    cr.fill_preserve()
                    cr.set_source_rgb(1.0, 1.0, 1.0)
                else:
                    cr.set_source_rgb(0.10, 0.11, 0.15)
                    cr.fill_preserve()
                    cr.set_source_rgb(0.22, 0.25, 0.32)
                    cr.set_line_width(1.0)
                    cr.stroke()
                    cr.set_source_rgb(0.92, 0.94, 0.96)

                label = k.shift_label if self.kb_layout.shift_active else k.label
                cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(20.0 if len(label) == 1 else 16.0)
                extents = cr.text_extents(label)
                cr.move_to(k.x + (k.w - extents.width) / 2.0, k.y + (k.h + extents.height) / 2.0 - 1)
                cr.show_text(label)

    def _draw_debug_hud(self, cr: cairo.Context) -> None:
        """Render diagnostic telemetry HUD in top-right of trackpad area."""
        hud_w, hud_h = 320.0, 170.0
        hud_x, hud_y = SCREEN_WIDTH - hud_w - 30.0, HEADER_HEIGHT + 20.0

        # HUD Box
        self._round_rect(cr, hud_x, hud_y, hud_w, hud_h, 10.0)
        cr.set_source_rgba(0.05, 0.07, 0.10, 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(0.18, 0.55, 0.35, 0.8)
        cr.set_line_width(1.5)
        cr.stroke()

        # Telemetry info
        telem = self.bridge.get_telemetry()
        lines = [
            f"DIAGNOSTICS [FPS: {self.fps:.0f}]",
            f"State: {self.gesture.last_state_label}",
            f"Coords: ({self.gesture.last_coords[0]:.0f}, {self.gesture.last_coords[1]:.0f})",
            f"Moves: {telem['mouse_moves']} | Scrolls: {telem['scrolls']}",
            f"Clicks L/R: {telem['clicks_left']}/{telem['clicks_right']} | Keys: {telem['keystrokes']}",
            f"HW Node: {self.touch_dev_node or 'None'}",
        ]

        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(13.0)
        line_y = hud_y + 24.0
        for i, text in enumerate(lines):
            cr.set_source_rgb(0.2, 0.9, 0.5) if i == 0 else cr.set_source_rgb(0.85, 0.88, 0.92)
            cr.move_to(hud_x + 14.0, line_y)
            cr.show_text(text)
            line_y += 22.0

    def _round_rect(self, cr: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5707963, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5707963)
        cr.arc(x + r, y + h - r, r, 1.5707963, 3.1415926)
        cr.arc(x + r, y + r, r, 3.1415926, 4.7123889)
        cr.close_path()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    app = ThorApp()
    app.start()
    try:
        Gtk.main()
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
