#!/usr/bin/env python3
"""Thor Input App: Bottom-screen AMOLED interface with trackpad, keyboard, system monitor & quick controls."""
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
from system_stats import HardwareStats

SOCKET_PATH = f"/run/user/{os.getuid()}/thor-input.sock"
CONFIG_PATH = os.path.expanduser("~/.config/thor-input/config.json")
HEADER_BUTTONS_H = 48.0
STATUS_RIBBON_H = 44.0
HEADER_HEIGHT = HEADER_BUTTONS_H + STATUS_RIBBON_H  # 92.0


class ThorApp:
    def __init__(self) -> None:
        self.logger = DebugLogger("app")
        self.logger.log(DebugCode.DAEMON_STARTING)

        self.mode = "trackpad"  # 'trackpad', 'split', 'keyboard', 'settings'
        self.show_debug_hud = False
        self.touch_dev_node = ""

        # Hardware stats & control sampler
        self.stats = HardwareStats(cache_ttl=0.4)

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
        self.window.set_title("Touch Master")
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
                    self.gesture.set_settings(**cfg)
            except Exception as err:
                self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"load_config: {err}")

    def save_config(self) -> None:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            cfg = {
                "mode": self.mode,
                "debug_hud": self.show_debug_hud,
                **self.gesture.get_settings(),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as err:
            self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"save_config: {err}")

    def set_mode(self, mode: str) -> None:
        if mode not in ("trackpad", "split", "keyboard", "settings"):
            return
        self.mode = mode
        self.update_mode_bounds()
        self.save_config()
        GLib.idle_add(self.drawing_area.queue_draw)

    def update_mode_bounds(self) -> None:
        if self.mode == "keyboard":
            self.kb_layout.update_bounds(0, HEADER_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - HEADER_HEIGHT)
        elif self.mode == "split":
            split_y = 500.0
            self.kb_layout.update_bounds(0, split_y, SCREEN_WIDTH, SCREEN_HEIGHT - split_y)

    def start(self) -> None:
        self._start_touch_reader()
        self._start_ipc_server()
        self.window.show_all()
        # Periodic 1-second refresh for live system monitor ribbon
        GLib.timeout_add(1000, self._on_stats_tick)
        self.logger.log(DebugCode.DAEMON_READY, f"Mode={self.mode}, Device={self.touch_dev_node}")

    def _on_stats_tick(self) -> bool:
        if not self.touch_stop.is_set():
            self.drawing_area.queue_draw()
            return True
        return False

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
            try:
                os.close(self.touch_fd)
            except OSError:
                pass
            self.touch_fd = -1
        self.bridge.close()
        self.logger.log(DebugCode.DAEMON_STOPPED)

    # -------------------------------------------------------------------------
    # Touch Input Processing (Raw Digitizer Thread)
    # -------------------------------------------------------------------------

    def _start_touch_reader(self) -> None:
        node = self._find_bottom_touchscreen()
        if not node:
            self.logger.log(DebugCode.ERR_TOUCH_MISSING, "No bottom touchscreen digitizer located")
            return

        self.touch_dev_node = node
        try:
            self.touch_fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
            EVIOCGRAB = (1 << 30) | (struct.calcsize("i") << 16) | (ord("E") << 8) | 0x90
            fcntl.ioctl(self.touch_fd, EVIOCGRAB, 1)
            self.logger.log(DebugCode.TOUCH_OK, f"Exclusively grabbed {node}")
        except PermissionError:
            self.logger.log(DebugCode.ERR_TOUCH_OPEN, f"Permission denied accessing {node}")
            return
        except OSError as err:
            self.logger.log(DebugCode.ERR_TOUCH_GRAB, f"Failed grabbing {node}: {err}")
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

    def _find_bottom_touchscreen(self) -> str | None:
        for node in sorted(glob.glob("/dev/input/event*")):
            try:
                with open(f"/sys/class/input/{os.path.basename(node)}/device/name", encoding="utf-8") as f:
                    name = f.read().strip().lower()
                    if "bottom" in name and "touchscreen" in name:
                        return node
            except OSError:
                pass
        return "/dev/input/event5" if os.path.exists("/dev/input/event5") else None

    # -------------------------------------------------------------------------
    # Touch Event Routing
    # -------------------------------------------------------------------------

    def _handle_touch_down(self, tid: int, x: float, y: float, now: float) -> None:
        self.last_event_time = time.time()

        # 1. Header Navigation Bar (y < 48)
        if y < HEADER_BUTTONS_H:
            self._handle_header_touch(x, y, True)
            return

        # 2. Status Ribbon (48 <= y < HEADER_HEIGHT) -> tap toggles Quick Settings
        if y < HEADER_HEIGHT:
            if self.mode == "settings":
                self.set_mode("trackpad")
            else:
                self.set_mode("settings")
            return

        # 3. Quick Settings Mode
        if self.mode == "settings":
            self._handle_settings_touch(x, y)
            return

        # 4. Keyboard / Split Mode
        if self.mode == "keyboard" or (self.mode == "split" and y >= 500.0):
            key = self.kb_layout.hit_test(x, y)
            if key:
                self.active_key_press = key.code
                self.last_key_label = key.label
                if key.special == "shift":
                    self.kb_layout.shift_active = not self.kb_layout.shift_active
                    self.bridge.key(key.code, self.kb_layout.shift_active)
                elif key.special in ("ctrl", "alt", "super"):
                    current = getattr(self.kb_layout, f"{key.special}_active", False)
                    setattr(self.kb_layout, f"{key.special}_active", not current)
                    self.bridge.key(key.code, not current)
                else:
                    self.bridge.tap_key(key.code)
                    if self.kb_layout.shift_active and not key.is_modifier:
                        self.kb_layout.shift_active = False
                        self.bridge.key(42, False)
                GLib.idle_add(self.drawing_area.queue_draw)
            return

        # 5. Trackpad Mode (or top half of Split)
        self.gesture.touch_down(tid, x, y, now)
        if self.show_debug_hud:
            GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_touch_move(self, tid: int, x: float, y: float, now: float) -> None:
        self.last_event_time = time.time()
        if y >= HEADER_HEIGHT:
            if self.mode == "settings":
                # Continuous slider drag in settings
                self._handle_settings_drag(x, y)
            elif self.mode == "trackpad" or (self.mode == "split" and y < 500.0):
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

        if self.mode != "settings":
            self.gesture.touch_up(tid, now)
            if self.show_debug_hud:
                GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_header_touch(self, x: float, y: float, down: bool) -> None:
        if 12 <= x <= 132:
            self.set_mode("trackpad")
        elif 140 <= x <= 240:
            self.set_mode("split")
        elif 248 <= x <= 368:
            self.set_mode("keyboard")
        elif 376 <= x <= 526:
            self.set_mode("settings")
        elif 534 <= x <= 614:
            # HUD toggle
            self.show_debug_hud = not self.show_debug_hud
            self.save_config()
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 680 <= x <= 820:
            self.held_ui_button = "left"
            self.bridge.mouse_button(BTN_LEFT, True)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 828 <= x <= 968:
            self.held_ui_button = "right"
            self.bridge.mouse_button(BTN_RIGHT, True)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 1120 <= x <= 1220:
            self.window.close()

    def _handle_settings_touch(self, x: float, y: float) -> None:
        # Card 1: Volume (y = 120 .. 230)
        if 160 <= y <= 220:
            if 30 <= x <= 120:
                self.stats.adjust_volume(-5)
            elif 130 <= x <= 950:
                pct = round((x - 130) / (950 - 130) * 100)
                self.stats.set_volume(pct)
            elif 960 <= x <= 1050:
                self.stats.adjust_volume(5)
            elif 1060 <= x <= 1210:
                self.stats.toggle_mute()
            GLib.idle_add(self.drawing_area.queue_draw)
            return

        # Card 2: Top Brightness (y = 270 .. 380)
        if 310 <= y <= 370:
            if 30 <= x <= 120:
                self.stats.adjust_top_brightness(-10)
            elif 130 <= x <= 1090:
                pct = round((x - 130) / (1090 - 130) * 100)
                self.stats.set_top_brightness(pct)
            elif 1100 <= x <= 1210:
                self.stats.adjust_top_brightness(10)
            GLib.idle_add(self.drawing_area.queue_draw)
            return

        # Card 3: Bottom Brightness (y = 420 .. 530)
        if 460 <= y <= 520:
            if 30 <= x <= 120:
                self.stats.adjust_bottom_brightness(-10)
            elif 130 <= x <= 1090:
                pct = round((x - 130) / (1090 - 130) * 100)
                self.stats.set_bottom_brightness(pct)
            elif 1100 <= x <= 1210:
                self.stats.adjust_bottom_brightness(10)
            GLib.idle_add(self.drawing_area.queue_draw)
            return

        # Bottom Action Buttons (y = 850 .. 910)
        if 850 <= y <= 910:
            if 30 <= x <= 380:
                # Diagnostics self-test
                run_self_diagnostics()
            elif 400 <= x <= 650:
                self.show_debug_hud = not self.show_debug_hud
                self.save_config()
            elif 670 <= x <= 920:
                self.set_mode("trackpad")
            GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_settings_drag(self, x: float, y: float) -> None:
        if 160 <= y <= 220 and 130 <= x <= 950:
            pct = round((x - 130) / (950 - 130) * 100)
            self.stats.set_volume(pct)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 310 <= y <= 370 and 130 <= x <= 1090:
            pct = round((x - 130) / (1090 - 130) * 100)
            self.stats.set_top_brightness(pct)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif 460 <= y <= 520 and 130 <= x <= 1090:
            pct = round((x - 130) / (1090 - 130) * 100)
            self.stats.set_bottom_brightness(pct)
            GLib.idle_add(self.drawing_area.queue_draw)

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
                            res["debug_hud"] = self.show_debug_hud
                            res["hardware_stats"] = self.stats.get_stats()
                            res.update(self.gesture.get_settings())
                        elif action == "get_debug":
                            res["telemetry"] = self.bridge.get_telemetry()
                            res["state"] = self.gesture.last_state_label
                            res["coords"] = self.gesture.last_coords
                            res["touch_device"] = self.touch_dev_node
                            res["active_fingers"] = len(self.gesture.active_contacts)
                            res["last_key"] = self.last_key_label
                            res["hardware_stats"] = self.stats.get_stats()
                            res.update(self.gesture.get_settings())
                        elif action == "set_mode":
                            self.set_mode(msg.get("mode", "trackpad"))
                        elif action == "set_settings":
                            self.gesture.set_settings(**msg)
                            if "debug_hud" in msg:
                                self.show_debug_hud = bool(msg["debug_hud"])
                            self.save_config()
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_volume":
                            res["vol_pct"] = self.stats.set_volume(msg.get("volume", 50))
                            self.logger.log(DebugCode.VOLUME_UPDATED, f"volume={res['vol_pct']}%")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "toggle_mute":
                            res["vol_muted"] = self.stats.toggle_mute()
                            self.logger.log(DebugCode.VOLUME_UPDATED, f"muted={res['vol_muted']}")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_top_brightness":
                            res["top_bright_pct"] = self.stats.set_top_brightness(msg.get("brightness", 100))
                            self.logger.log(DebugCode.BACKLIGHT_UPDATED, f"top={res['top_bright_pct']}%")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_bottom_brightness":
                            res["bot_bright_pct"] = self.stats.set_bottom_brightness(msg.get("brightness", 100))
                            self.logger.log(DebugCode.BACKLIGHT_UPDATED, f"bottom={res['bot_bright_pct']}%")
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
    # Cairo Drawing (AMOLED UI, Keyboard, Ribbon & Quick Controls)
    # -------------------------------------------------------------------------

    def on_draw(self, _, cr: cairo.Context) -> bool:
        self.frame_count += 1
        now = time.time()
        if now - self.last_fps_calc >= 1.0:
            self.fps = self.frame_count / (now - self.last_fps_calc)
            self.frame_count = 0
            self.last_fps_calc = now

        # Pure OLED Black Background
        cr.set_source_rgb(0, 0, 0)
        cr.paint()

        # Header Bar & Live Status Ribbon
        self._draw_header(cr)
        self._draw_status_ribbon(cr)

        # Mode Contents
        if self.mode == "trackpad":
            self._draw_trackpad_surface(cr, HEADER_HEIGHT, SCREEN_HEIGHT - HEADER_HEIGHT)
        elif self.mode == "keyboard":
            self._draw_keyboard(cr)
        elif self.mode == "split":
            split_y = 500.0
            self._draw_trackpad_surface(cr, HEADER_HEIGHT, split_y - HEADER_HEIGHT)
            self._draw_keyboard(cr)
        elif self.mode == "settings":
            self._draw_quick_settings(cr)

        # Live Debug HUD Overlay (when enabled)
        if self.show_debug_hud:
            self._draw_debug_hud(cr)

        return True

    def _draw_header(self, cr: cairo.Context) -> None:
        cr.set_source_rgb(0.10, 0.12, 0.16)
        cr.set_line_width(1.0)
        cr.move_to(0, HEADER_BUTTONS_H)
        cr.line_to(SCREEN_WIDTH, HEADER_BUTTONS_H)
        cr.stroke()
        cr.new_path()

        self._draw_button(cr, 12, 6, 120, 36, "Trackpad", self.mode == "trackpad")
        self._draw_button(cr, 140, 6, 100, 36, "Split", self.mode == "split")
        self._draw_button(cr, 248, 6, 120, 36, "Keyboard", self.mode == "keyboard")
        self._draw_button(cr, 376, 6, 150, 36, "Quick Controls", self.mode == "settings", accent_color=(0.20, 0.55, 0.90))

        # HUD Toggle Button
        hud_active = self.show_debug_hud
        self._draw_button(cr, 534, 6, 80, 36, "HUD", hud_active, accent_color=(0.15, 0.65, 0.45))

        # Click helper buttons
        left_active = self.held_ui_button == "left"
        right_active = self.held_ui_button == "right"
        self._draw_button(cr, 680, 6, 140, 36, "Left Click", left_active, accent_color=(0.3, 0.45, 0.95))
        self._draw_button(cr, 828, 6, 140, 36, "Right Click", right_active, accent_color=(0.85, 0.35, 0.35))
        self._draw_button(cr, 1120, 6, 100, 36, "✕ Close", False)

    def _draw_status_ribbon(self, cr: cairo.Context) -> None:
        """Render live system monitoring ribbon across top of AMOLED display."""
        st = self.stats.get_stats()
        ry = HEADER_BUTTONS_H
        rh = STATUS_RIBBON_H

        # Ribbon Background container
        cr.set_source_rgb(0.04, 0.05, 0.07)
        cr.rectangle(0, ry, SCREEN_WIDTH, rh)
        cr.fill()

        cr.set_source_rgb(0.14, 0.16, 0.22)
        cr.set_line_width(1.0)
        cr.move_to(0, ry + rh)
        cr.line_to(SCREEN_WIDTH, ry + rh)
        cr.stroke()
        cr.new_path()

        # Telemetry pills text
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(14.0)

        # Battery
        bat_icon = "⚡" if "charg" in st.get("bat_status", "").lower() else "🔋"
        bat_txt = f"{bat_icon} {st.get('bat_cap', 0)}% ({st.get('bat_watts', 0)}W)"
        # CPU
        cpu_txt = f"🧠 CPU {st.get('cpu_load', 0)}% · {st.get('cpu_temp', 0)}°C"
        # GPU
        gpu_txt = f"🎮 GPU {st.get('gpu_mhz', 0)}M · {st.get('gpu_temp', 0)}°C"
        # RAM
        ram_txt = f"💾 RAM {st.get('ram_used_gb', 0)}/{st.get('ram_total_gb', 0)}G"
        # Volume
        vol_txt = f"🔊 Muted" if st.get("vol_muted") else f"🔊 Vol {st.get('vol_pct', 0)}%"
        # Brightness
        brt_txt = f"☀️ Top {st.get('top_bright_pct', 100)}% · Bot {st.get('bot_bright_pct', 100)}%"

        pills = [
            (bat_txt, (0.3, 0.85, 0.5)),
            (cpu_txt, (0.4, 0.75, 1.0)),
            (gpu_txt, (0.95, 0.7, 0.3)),
            (ram_txt, (0.75, 0.6, 0.95)),
            (vol_txt, (0.9, 0.5, 0.5) if st.get("vol_muted") else (0.4, 0.85, 0.9)),
            (brt_txt, (1.0, 0.85, 0.4)),
        ]

        cur_x = 20.0
        for text, col in pills:
            cr.set_source_rgb(*col)
            cr.move_to(cur_x, ry + 27.0)
            cr.show_text(text)
            ext = cr.text_extents(text)
            cur_x += ext.width + 26.0

            # Divider dot
            if cur_x < SCREEN_WIDTH - 80:
                cr.set_source_rgb(0.25, 0.28, 0.35)
                cr.arc(cur_x - 13.0, ry + 22.0, 2.0, 0, 6.28)
                cr.fill()
                cr.new_path()

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
        radius = 10.0
        self._round_rect(cr, x, y, w, h, radius)
        if active:
            cr.set_source_rgb(*accent_color)
            cr.fill_preserve()
            cr.set_source_rgb(0.75, 0.65, 1.0)
            cr.set_line_width(1.5)
            cr.stroke()
            cr.set_source_rgb(1.0, 1.0, 1.0)
        else:
            cr.set_source_rgb(0.08, 0.09, 0.12)
            cr.fill_preserve()
            cr.set_source_rgb(0.2, 0.22, 0.28)
            cr.set_line_width(1.0)
            cr.stroke()
            cr.set_source_rgb(0.85, 0.88, 0.92)
        cr.new_path()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(15.0)
        extents = cr.text_extents(text)
        cr.move_to(x + (w - extents.width) / 2.0, y + (h + extents.height) / 2.0 - 2)
        cr.show_text(text)

    def _draw_trackpad_surface(self, cr: cairo.Context, y: float, h: float) -> None:
        margin = 20.0
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
        cr.new_path()

        # If Edge Scroll is toggled on, draw clean indicator rectangles for vertical and horizontal zones
        if self.gesture.edge_scroll_enabled:
            # 1. Vertical Scroll Zone (Right edge)
            zone_x = self.gesture.edge_scroll_x_min
            zone_y = self.gesture.edge_scroll_y_min
            zone_w = self.gesture.edge_scroll_x_max - self.gesture.edge_scroll_x_min
            zone_h = self.gesture.edge_scroll_y_max - self.gesture.edge_scroll_y_min
            is_v_active = (self.gesture.active_edge_scroll_axis == "v" and self.gesture.edge_scroll_thumb_y is not None)

            self._round_rect(cr, zone_x, zone_y, zone_w, zone_h, 12.0)
            if is_v_active:
                # Active touch highlight inside vertical scroll rectangle
                cr.set_source_rgba(0.15, 0.45, 0.85, 0.22)
                cr.fill_preserve()
                cr.set_source_rgba(0.25, 0.75, 1.0, 0.85)
                cr.set_line_width(1.5)
                cr.stroke()
                cr.new_path()

                # Subtle touch indicator pip at current drag position
                ty = max(zone_y + 8.0, min(zone_y + zone_h - 28.0, self.gesture.edge_scroll_thumb_y - 10.0))
                self._round_rect(cr, zone_x + 8.0, ty, zone_w - 16.0, 20.0, 6.0)
                cr.set_source_rgba(0.30, 0.80, 1.0, 0.90)
                cr.fill()
                cr.new_path()
            else:
                # Resting vertical indicator rectangle
                cr.set_source_rgba(0.06, 0.08, 0.12, 0.65)
                cr.fill_preserve()
                cr.set_source_rgba(0.22, 0.26, 0.35, 0.75)
                cr.set_line_width(1.0)
                cr.stroke()
                cr.new_path()

                cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(18.0)
                cr.set_source_rgba(0.35, 0.40, 0.52, 0.75)
                ext = cr.text_extents("↕")
                cr.move_to(zone_x + (zone_w - ext.width) / 2.0, zone_y + zone_h / 2.0 + ext.height / 2.0)
                cr.show_text("↕")
                cr.new_path()

            # 2. Horizontal Scroll Zone (Bottom edge)
            h_zone_x = self.gesture.edge_scroll_h_x_min
            h_zone_y = self.gesture.edge_scroll_h_y_min
            h_zone_w = self.gesture.edge_scroll_h_x_max - self.gesture.edge_scroll_h_x_min
            h_zone_h = self.gesture.edge_scroll_h_y_max - self.gesture.edge_scroll_h_y_min
            is_h_active = (self.gesture.active_edge_scroll_axis == "h" and self.gesture.edge_scroll_thumb_x is not None)

            self._round_rect(cr, h_zone_x, h_zone_y, h_zone_w, h_zone_h, 12.0)
            if is_h_active:
                # Active touch highlight inside horizontal scroll rectangle
                cr.set_source_rgba(0.15, 0.45, 0.85, 0.22)
                cr.fill_preserve()
                cr.set_source_rgba(0.25, 0.75, 1.0, 0.85)
                cr.set_line_width(1.5)
                cr.stroke()
                cr.new_path()

                # Subtle touch indicator pip at current drag position
                tx = max(h_zone_x + 8.0, min(h_zone_x + h_zone_w - 28.0, self.gesture.edge_scroll_thumb_x - 10.0))
                self._round_rect(cr, tx, h_zone_y + 8.0, 20.0, h_zone_h - 16.0, 6.0)
                cr.set_source_rgba(0.30, 0.80, 1.0, 0.90)
                cr.fill()
                cr.new_path()
            else:
                # Resting horizontal indicator rectangle
                cr.set_source_rgba(0.06, 0.08, 0.12, 0.65)
                cr.fill_preserve()
                cr.set_source_rgba(0.22, 0.26, 0.35, 0.75)
                cr.set_line_width(1.0)
                cr.stroke()
                cr.new_path()

                cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(18.0)
                cr.set_source_rgba(0.35, 0.40, 0.52, 0.75)
                ext = cr.text_extents("↔")
                cr.move_to(h_zone_x + (h_zone_w - ext.width) / 2.0, h_zone_y + h_zone_h / 2.0 + ext.height / 2.0)
                cr.show_text("↔")
                cr.new_path()

        # Center prompt hint
        cr.set_source_rgb(0.30, 0.34, 0.42)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(20.0)
        if self.gesture.edge_scroll_enabled:
            hint = "Touch Master: 1 finger moves · Right/bottom edges scroll · Tap clicks · Flick glides"
        else:
            hint = "Touch Master: 1 finger moves · Tap clicks · 2 fingers scroll · Flick glides"
        extents = cr.text_extents(hint)
        avail_w = pad_w - (80.0 if self.gesture.edge_scroll_enabled else 0.0)
        cr.move_to(pad_x + (avail_w - extents.width) / 2.0, pad_y + (pad_h + extents.height) / 2.0)
        cr.show_text(hint)

    def _draw_keyboard(self, cr: cairo.Context) -> None:
        """Render virtual keyboard with clean key highlighting and dual symbol labels."""
        shift_on = self.kb_layout.shift_active

        for row in self.kb_layout.rows:
            for k in row:
                is_active = self.active_key_press == k.code
                if k.special == "shift" and shift_on:
                    is_active = True
                elif k.special == "ctrl" and self.kb_layout.ctrl_active:
                    is_active = True
                elif k.special == "alt" and self.kb_layout.alt_active:
                    is_active = True
                elif k.special == "super" and getattr(self.kb_layout, "super_active", False):
                    is_active = True

                self._round_rect(cr, k.x, k.y, k.w, k.h, 10.0)
                if is_active:
                    # Highlighted active key
                    cr.set_source_rgb(0.48, 0.28, 0.95)
                    cr.fill_preserve()
                    cr.set_source_rgb(0.78, 0.60, 1.0)
                    cr.set_line_width(2.0)
                    cr.stroke()
                else:
                    if shift_on and k.is_letter:
                        # Subtle highlighted tint for letters when Shift is active
                        cr.set_source_rgb(0.15, 0.14, 0.22)
                    else:
                        cr.set_source_rgb(0.10, 0.11, 0.15)
                    cr.fill_preserve()
                    cr.set_source_rgb(0.22, 0.25, 0.32)
                    cr.set_line_width(1.0)
                    cr.stroke()
                cr.new_path()  # Path clean reset

                # Draw Labels
                if k.has_sub_symbol:
                    # Keys with dual symbols (e.g. 1 / !, - / _, [ / {)
                    prim = k.label
                    sub = k.shift_label

                    # Primary character (centered / lower)
                    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                    cr.set_font_size(18.0)
                    if shift_on:
                        cr.set_source_rgb(0.60, 0.64, 0.72)
                    else:
                        cr.set_source_rgb(1.0, 1.0, 1.0) if is_active else cr.set_source_rgb(0.92, 0.94, 0.96)
                    ext = cr.text_extents(prim)
                    cr.move_to(k.x + (k.w - ext.width) / 2.0 - 5, k.y + k.h - 13)
                    cr.show_text(prim)

                    # Secondary shifted symbol (upper-right corner)
                    cr.set_font_size(14.0)
                    if shift_on:
                        cr.set_source_rgb(0.35, 0.85, 1.0)  # Highlighted cyan!
                    else:
                        cr.set_source_rgb(0.42, 0.48, 0.58)  # Subtle secondary
                    sub_ext = cr.text_extents(sub)
                    cr.move_to(k.x + k.w - sub_ext.width - 10, k.y + 20)
                    cr.show_text(sub)
                else:
                    # Normal letter or modifier
                    label = k.shift_label if (shift_on and k.is_letter) else k.label
                    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                    cr.set_font_size(20.0 if len(label) == 1 else 16.0)

                    if is_active:
                        cr.set_source_rgb(1.0, 1.0, 1.0)
                    elif shift_on and k.is_letter:
                        cr.set_source_rgb(0.40, 0.85, 1.0)  # Bright cyan highlight for active uppercase!
                    else:
                        cr.set_source_rgb(0.92, 0.94, 0.96)
                    extents = cr.text_extents(label)
                    cr.move_to(k.x + (k.w - extents.width) / 2.0, k.y + (k.h + extents.height) / 2.0 - 1)
                    cr.show_text(label)

    def _draw_quick_settings(self, cr: cairo.Context) -> None:
        """Render full Quick Settings dashboard cards."""
        st = self.stats.get_stats()

        # Card 1: Master Audio Volume
        self._draw_slider_card(
            cr,
            x=20,
            y=120,
            w=SCREEN_WIDTH - 40,
            h=120,
            title=f"Master Audio Volume: {st.get('vol_pct', 0)}%" + (" [MUTED]" if st.get("vol_muted") else ""),
            pct=st.get("vol_pct", 0),
            track_w=820,
            has_mute=True,
            is_muted=st.get("vol_muted", False),
            accent_col=(0.35, 0.55, 0.95),
        )

        # Card 2: Top Display Brightness
        self._draw_slider_card(
            cr,
            x=20,
            y=270,
            w=SCREEN_WIDTH - 40,
            h=120,
            title=f"Top Screen Brightness: {st.get('top_bright_pct', 100)}%",
            pct=st.get("top_bright_pct", 100),
            track_w=960,
            has_mute=False,
            accent_col=(1.0, 0.80, 0.30),
        )

        # Card 3: Bottom AMOLED Brightness
        self._draw_slider_card(
            cr,
            x=20,
            y=420,
            w=SCREEN_WIDTH - 40,
            h=120,
            title=f"Bottom AMOLED Brightness: {st.get('bot_bright_pct', 100)}%",
            pct=st.get("bot_bright_pct", 100),
            track_w=960,
            has_mute=False,
            accent_col=(0.30, 0.85, 0.60),
        )

        # Card 4: Hardware Health Monitor Grid
        self._round_rect(cr, 20, 570, SCREEN_WIDTH - 40, 240, 18.0)
        cr.set_source_rgb(0.06, 0.07, 0.10)
        cr.fill_preserve()
        cr.set_source_rgb(0.18, 0.20, 0.26)
        cr.set_line_width(1.5)
        cr.stroke()
        cr.new_path()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(18.0)
        cr.set_source_rgb(0.85, 0.88, 0.95)
        cr.move_to(44, 608)
        cr.show_text("Live System Health & Power Telemetry")

        grid_items = [
            ("Battery Status", f"{st.get('bat_cap', 0)}% · {st.get('bat_status', 'N/A')} ({st.get('bat_watts', 0)} W)", (0.3, 0.85, 0.5)),
            ("CPU Processor", f"{st.get('cpu_load', 0)}% Load · {st.get('cpu_ghz', 0)} GHz · {st.get('cpu_temp', 0)}°C", (0.4, 0.75, 1.0)),
            ("GPU Adreno", f"{st.get('gpu_mhz', 0)} MHz · {st.get('gpu_temp', 0)}°C", (0.95, 0.7, 0.3)),
            ("System RAM", f"{st.get('ram_used_gb', 0)} / {st.get('ram_total_gb', 0)} GB ({st.get('ram_pct', 0)}%)", (0.75, 0.6, 0.95)),
        ]

        gx = 44.0
        gy = 650.0
        for i, (label, val, col) in enumerate(grid_items):
            rx = gx if (i % 2 == 0) else gx + 580.0
            ry = gy if (i < 2) else gy + 75.0

            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(15.0)
            cr.set_source_rgb(0.55, 0.60, 0.70)
            cr.move_to(rx, ry)
            cr.show_text(label)

            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(20.0)
            cr.set_source_rgb(*col)
            cr.move_to(rx, ry + 30.0)
            cr.show_text(val)

        # Action Buttons
        self._draw_button(cr, 30, 850, 350, 60, "Run Self-Test Diagnostics", False, accent_color=(0.2, 0.55, 0.9))
        self._draw_button(cr, 400, 850, 250, 60, "Toggle Glass HUD", self.show_debug_hud, accent_color=(0.2, 0.65, 0.4))
        self._draw_button(cr, 670, 850, 250, 60, "Back to Trackpad", False)

    def _draw_slider_card(
        self,
        cr: cairo.Context,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        pct: int,
        track_w: float,
        has_mute: bool = False,
        is_muted: bool = False,
        accent_col: tuple[float, float, float] = (0.35, 0.55, 0.95),
    ) -> None:
        self._round_rect(cr, x, y, w, h, 16.0)
        cr.set_source_rgb(0.06, 0.07, 0.10)
        cr.fill_preserve()
        cr.set_source_rgb(0.18, 0.20, 0.26)
        cr.set_line_width(1.5)
        cr.stroke()
        cr.new_path()

        # Title
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(17.0)
        cr.set_source_rgb(0.88, 0.90, 0.96)
        cr.move_to(x + 24, y + 32)
        cr.show_text(title)

        ctrl_y = y + 46.0
        # [-] button
        self._draw_button(cr, x + 10, ctrl_y, 90, 56, "–", False)

        # Slider track
        track_x = x + 110.0
        self._round_rect(cr, track_x, ctrl_y + 12.0, track_w, 32.0, 16.0)
        cr.set_source_rgb(0.12, 0.14, 0.18)
        cr.fill_preserve()
        cr.set_source_rgb(0.24, 0.27, 0.35)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.new_path()

        # Active filled portion
        fill_w = max(16.0, track_w * (pct / 100.0))
        self._round_rect(cr, track_x, ctrl_y + 12.0, fill_w, 32.0, 16.0)
        cr.set_source_rgb(*accent_col)
        cr.fill()
        cr.new_path()

        # [+] button
        plus_x = track_x + track_w + 10.0
        self._draw_button(cr, plus_x, ctrl_y, 90, 56, "+", False)

        # Optional Mute button
        if has_mute:
            mute_x = plus_x + 100.0
            mute_col = (0.85, 0.35, 0.35) if is_muted else (0.25, 0.28, 0.35)
            self._draw_button(cr, mute_x, ctrl_y, 140, 56, "Muted" if is_muted else "Mute", is_muted, accent_color=mute_col)

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
        cr.new_path()

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
