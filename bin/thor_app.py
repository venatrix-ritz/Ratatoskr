#!/usr/bin/env python3
"""Thor Input App: Bottom-screen AMOLED interface with trackpad, keyboard, system monitor & quick controls."""
from __future__ import annotations

import errno
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
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
    HAS_APP_INDICATOR = True
except Exception:
    HAS_APP_INDICATOR = False
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
    KEY_F24,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    STRIP_BOTTOM_H,
    STRIP_RIGHT_W,
    TouchGestureProcessor,
    UInputBridge,
    raw_to_screen,
)
from keyboard_layout import Key, KeyboardLayout
import key_render
import keyboard_settings
import gleipnir_view
from modifiers import ModifierState
from touch_frames import TouchFrameParser
from dim_mirror import DimMirror, IdleTracker
from system_stats import HardwareStats
import pen_mode as pm
import atomic_json
import ipc_util
import session_cursor
import tray_actions

SOCKET_PATH = f"/run/user/{os.getuid()}/thor-input.sock"
CONFIG_PATH = os.path.expanduser("~/.config/thor-input/config.json")
# The bottom panel is 3.92" at 1240x1080, about 16.5 px per mm: the old 48 px header (36 px buttons, 15 px text) was
# about 2 mm tall. 80 / 64 px buttons are about 4 mm, still leaving most of the screen to the trackpad and keyboard.
HEADER_BUTTONS_H = 80.0
STATUS_RIBBON_H = 88.0  # two rows of three status items
BUTTON_TEXT_MAX_PX = 26.0
RIBBON_TEXT_MAX_PX = 28.0
HEADER_HEIGHT = HEADER_BUTTONS_H + STATUS_RIBBON_H
SPLIT_Y = 500.0  # split mode: trackpad above, keyboard below

# Header buttons: (key, x, width). One table for drawing and for hit-testing.
HEADER_BUTTONS = (
    ("trackpad", 12, 150), ("split", 170, 110), ("keyboard", 288, 150), ("settings", 446, 190),
    ("hud", 644, 90), ("left", 750, 150), ("right", 908, 150), ("pen", 1066, 162),
)
HEADER_BUTTON_Y, HEADER_BUTTON_H = 8.0, 64.0

# Quick Controls layout, below the header
QC_CARD_Y = (HEADER_HEIGHT + 28.0, HEADER_HEIGHT + 178.0, HEADER_HEIGHT + 328.0)  # volume, top, bottom brightness
QC_CARD_H = 120.0
QC_CTRL_DY, QC_CTRL_H = 46.0, 56.0  # the -, slider, + row inside a card
QC_HEALTH_Y, QC_HEALTH_H = HEADER_HEIGHT + 478.0, 220.0
QC_BUTTONS_Y, QC_BUTTONS_H = HEADER_HEIGHT + 724.0, 64.0

# <linux/input.h> (include/uapi/linux/input.h): EVIOCGABS(abs) = _IOR('E', 0x40 + abs, struct input_absinfo), 24 bytes;
# EVIOCGMTSLOTS(len) = _IOC(_IOC_READ, 'E', 0x0a, len) with a buffer of one u32 code and one s32 per slot.
_IOC_READ = 2


def _eviocgabs(code: int) -> int:
    return (_IOC_READ << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code)


def _eviocgmtslots(length: int) -> int:
    return (_IOC_READ << 30) | (length << 16) | (ord("E") << 8) | 0x0A


class ThorApp:
    def __init__(self) -> None:
        self.logger = DebugLogger("app")
        self.logger.log(DebugCode.DAEMON_STARTING)

        self.mode = "trackpad"  # 'trackpad', 'split', 'keyboard', 'settings'
        self.show_debug_hud = False
        self.touch_dev_node = ""
        self.exit_code = 0
        self._cleaned = False
        self._parser = None
        self._last_contacts = (0, 0)
        self._last_frame_ts = 0.0
        self._slider_drag: tuple[int, str] | None = None  # (touch id, 'vol' | 'top' | 'bot') while a slider is held
        self.pen_mode = "off"  # off | pen | pen_plus, see pen_mode.py
        self._cursor_status = {"cursor_stay_visible": False, "cursor_hide_delay_ms": None, "cursor_stay_visible_active": False}
        self._draw_ms_sum = 0.0
        self._draw_ms_max = 0.0
        self._draws = 0
        self._lag_ms_max = 0.0  # worst age of a touch frame when it was handled

        # Hardware stats & control sampler
        self.stats = HardwareStats(cache_ttl=0.4)

        # Bottom screen follows Steam's idle-dim timer (off until switched on)
        self.mirror_cfg: dict = {"mirror_dim": False, "mirror_dim_floor_percent": 3}
        # Keyboard timings (repeat delay, repeat interval, Caps Lock double-tap window), in milliseconds
        self.keyboard_cfg: dict = dict(keyboard_settings.DEFAULTS)
        # Gleipnir (the charge limiter) in the ribbon and Quick Controls: off until switched on; polled every 10 s
        self.gleipnir_cfg: dict = {"gleipnir_ribbon": False}
        self.gleipnir_status: dict | None = None
        self._gleipnir_wake = threading.Event()
        self.idle_tracker = IdleTracker(self.logger)
        self.dim_mirror = DimMirror(self.stats, self.idle_tracker, self.logger, lambda: self.mirror_cfg)

        # Bridge & processors
        self.bridge = UInputBridge(self.logger)
        self.gesture = TouchGestureProcessor(self.bridge, self.logger)
        self.kb_layout = KeyboardLayout(0, HEADER_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - HEADER_HEIGHT)
        self.held_ui_button: str | None = None
        self.held_ui_button_tid: int | None = None
        self.active_key_press: int | None = None
        self.active_key_tid: int | None = None  # the touch that pressed active_key_press; its lift clears the highlight
        self.last_key_label = ""
        self.last_event_time = time.time()
        self.fps = 60.0
        self.frame_count = 0
        self.last_fps_calc = time.time()

        # Continuous key repeat state
        self.held_key: Key | None = None
        self.held_key_tid: int | None = None
        self._repeat_stop = threading.Event()  # replaced for every repeat, so an old worker can never miss its stop
        self._repeat_thread: threading.Thread | None = None
        self.mods = ModifierState()  # Shift / Ctrl / Alt / Win: off, latched (one-shot) or locked
        self._touch_owner: dict[int, str] = {}  # touch id -> the area it landed in; a touch stays there until it lifts
        # Touch frames (reader thread) and settings / mode changes (IPC thread, GTK) all change the gesture and keyboard
        # state; one re-entrant lock keeps them from interleaving.
        self.input_lock = threading.RLock()

        self.load_config()

        # AppIndicator for desktop/plasma panel
        self.indicator = None
        self._setup_indicator()

        # Touch input thread
        self.touch_fd = -1
        self.touch_stop = threading.Event()
        self.touch_thread: threading.Thread | None = None

        # IPC server
        self.ipc_stop = threading.Event()
        self.ipc_thread: threading.Thread | None = None

        # UI Window
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Ratatoskr")
        self.window.set_decorated(False)
        self.window.set_resizable(False)
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
                    self._apply_mirror_settings(cfg)
                    keyboard_settings.apply(self.keyboard_cfg, cfg)
                    self._apply_gleipnir_settings(cfg)
                    self.pen_mode = pm.initial(cfg, session_cursor.is_configured())
                    self.gesture.set_settings(stylus_mode=pm.engine_flag(self.pen_mode))
            except Exception as err:
                self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"load_config: {err}")

    def save_config(self) -> None:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            # Start from what is on disk: the plugin's `enabled` and anything else the driver does not own must survive.
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    on_disk = json.load(f)
                if not isinstance(on_disk, dict):
                    on_disk = {}
            except (OSError, ValueError):
                on_disk = {}
            cfg = {
                **on_disk,
                "mode": self.mode,
                "debug_hud": self.show_debug_hud,
                "pen_mode": self.pen_mode,
                **self.gesture.get_settings(),
                **self.mirror_cfg,
                **self.keyboard_cfg,
                **self.gleipnir_cfg,
            }
            atomic_json.write_json_atomic(CONFIG_PATH, cfg)
        except Exception as err:
            self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"save_config: {err}")

    def set_pen_mode(self, mode) -> str:
        """Off, Pen, or Pen +. Pen + also writes Game Mode's pointer-visible override (it applies the next time Game
        Mode starts); leaving Pen + removes it. Until the override is running, the nudges stay on."""
        mode = pm.normalize(mode)
        with self.input_lock:
            self.pen_mode = mode
            self.gesture.set_settings(stylus_mode=pm.engine_flag(mode))
        ok = session_cursor.set_stay_visible(pm.wants_override(mode))
        self._refresh_cursor_status(fresh=True)
        self.logger.log(
            DebugCode.SETTINGS_UPDATED,
            f"pen mode {mode}; pointer-visible override {'on' if pm.wants_override(mode) else 'off'} "
            f"{'written' if ok else 'FAILED'}; it applies when Game Mode next starts",
        )
        self.save_config()
        GLib.idle_add(self.drawing_area.queue_draw)
        return mode

    def _apply_mirror_settings(self, msg: dict) -> None:
        if "mirror_dim" in msg:
            self.mirror_cfg["mirror_dim"] = bool(msg["mirror_dim"])
        if "mirror_dim_floor_percent" in msg:
            try:
                self.mirror_cfg["mirror_dim_floor_percent"] = max(1, min(50, int(msg["mirror_dim_floor_percent"])))
            except (TypeError, ValueError):
                pass

    def _apply_gleipnir_settings(self, msg: dict) -> None:
        if "gleipnir_ribbon" in msg:
            self.gleipnir_cfg["gleipnir_ribbon"] = bool(msg["gleipnir_ribbon"])
            if not self.gleipnir_cfg["gleipnir_ribbon"]:
                self.gleipnir_status = None
            self._gleipnir_wake.set()  # read it now instead of in up to 10 s

    def _gleipnir_loop(self) -> None:
        """Read Gleipnir's status every 10 s while the view is on (about 80 ms each, off the draw and touch threads)."""
        while not self.touch_stop.is_set():
            if self.gleipnir_cfg["gleipnir_ribbon"]:
                self.gleipnir_status = gleipnir_view.read_status()
                GLib.idle_add(self.drawing_area.queue_draw)
            self._gleipnir_wake.wait(10.0)
            self._gleipnir_wake.clear()

    def set_mode(self, mode: str) -> None:
        if mode not in ("trackpad", "split", "keyboard", "settings"):
            return
        with self.input_lock:
            self._slider_drag = None
            if mode not in ("keyboard", "split"):
                # Without a keyboard on screen a latched or locked modifier would turn every click into Ctrl/Shift-click.
                self._end_key_press()
                self._send_keys(self.mods.release_all())
            self.mode = mode
            self.update_mode_bounds()
        self.save_config()
        GLib.idle_add(self.drawing_area.queue_draw)

    def update_mode_bounds(self) -> None:
        if self.mode == "keyboard":
            self.kb_layout.update_bounds(0, HEADER_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - HEADER_HEIGHT)
        elif self.mode == "split":
            self.kb_layout.update_bounds(0, SPLIT_Y, SCREEN_WIDTH, SCREEN_HEIGHT - SPLIT_Y)

    def _setup_indicator(self) -> None:
        if not HAS_APP_INDICATOR:
            return
        try:
            self.indicator = AppIndicator3.Indicator.new(
                "touch-master",
                "touch-master",
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

            menu = Gtk.Menu()

            hdr = Gtk.MenuItem(label="Ratatoskr")
            hdr.set_sensitive(False)
            menu.append(hdr)
            menu.append(Gtk.SeparatorMenuItem())

            for mode_key, mode_name in [
                ("trackpad", "Trackpad Mode"),
                ("split", "Split Mode"),
                ("keyboard", "Keyboard Mode"),
                ("settings", "Quick Controls"),
            ]:
                item = Gtk.MenuItem(label=mode_name)
                item.connect("activate", lambda _, m=mode_key: self.set_mode(m))
                menu.append(item)

            menu.append(Gtk.SeparatorMenuItem())

            mgr_item = Gtk.MenuItem(label="Ratatoskr Manager...")
            mgr_item.connect("activate", self._launch_manager)
            menu.append(mgr_item)

            menu.append(Gtk.SeparatorMenuItem())

            stop_item = Gtk.MenuItem(label="Stop Ratatoskr")
            stop_item.connect("activate", self._stop_via_indicator)
            menu.append(stop_item)

            menu.show_all()
            self.indicator.set_menu(menu)
        except Exception as err:
            self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"AppIndicator init: {err}")

    def _launch_manager(self, *_) -> None:
        try:
            import subprocess

            mgr_script = str(SCRIPT_DIR / "touch_master_manager.py")
            env = os.environ.copy()
            if env.get("DISPLAY") == ":1":
                env["DISPLAY"] = ":0"
            subprocess.Popen([sys.executable, mgr_script], env=env)
        except Exception as err:
            self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"launch manager: {err}")

    def _stop_via_indicator(self, *_) -> None:
        """Stop the driver and give the bottom screen back to Armada's stock session. The steps after stopping
        the service would die with this process, so the manager does them from its own transient unit."""
        try:
            import subprocess

            subprocess.Popen(
                tray_actions.stop_command(str(SCRIPT_DIR / "touch_master_manager.py"), sys.executable),
                start_new_session=True,
            )
        except Exception as err:
            self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"stop via indicator: {err}")

    def _start_key_repeat(self, key: Key) -> None:
        self._stop_key_repeat()
        stop = threading.Event()
        self._repeat_stop = stop

        def _worker():
            # Initial hold delay before repeating, then the repeat interval (both are settings). Modifiers are already
            # down (self.mods), so a repeat is just the key.
            if stop.wait(self.keyboard_cfg["keyboard_repeat_delay_ms"] / 1000.0):
                return
            while not stop.is_set() and self.held_key is key:
                self.bridge.tap_key(key.code)
                if stop.wait(self.keyboard_cfg["keyboard_repeat_interval_ms"] / 1000.0):
                    break

        self._repeat_thread = threading.Thread(target=_worker, daemon=True)
        self._repeat_thread.start()

    def _stop_key_repeat(self) -> None:
        self._repeat_stop.set()
        self._repeat_thread = None

    def start(self) -> None:
        self.stats.start_sampler()
        self._refresh_cursor_status()
        self._start_touch_reader()
        self._start_ipc_server()
        self.idle_tracker.start()
        self.dim_mirror.start()
        threading.Thread(target=self._gleipnir_loop, name="gleipnir-view", daemon=True).start()
        self.window.show_all()
        # Periodic 1-second refresh for live system monitor ribbon
        GLib.timeout_add(1000, self._on_stats_tick)
        self.logger.log(DebugCode.DAEMON_READY, f"Mode={self.mode}, Device={self.touch_dev_node}")

    def _refresh_cursor_status(self, fresh: bool = False) -> None:
        """Is the running Game Mode keeping the pointer visible? If so the pre-scroll and pre-press nudges are off."""
        self._cursor_status = session_cursor.status(ttl=0 if fresh else 10.0)
        self.bridge.wake_pointer = not self._cursor_status["cursor_stay_visible_active"]

    def _on_stats_tick(self) -> bool:
        if not self.touch_stop.is_set():
            self._refresh_cursor_status()
            self.drawing_area.queue_draw()
            return True
        return False

    def on_destroy(self, *_) -> None:
        self.cleanup()
        Gtk.main_quit()

    def request_quit(self, signum: int = 0) -> bool:
        """Leave the main loop so that cleanup() runs. Used for SIGTERM (what systemd sends on stop and restart) and SIGINT."""
        name = signal.Signals(signum).name if signum else "quit request"
        self.logger.log(DebugCode.DAEMON_STOPPING, f"{name} received")
        Gtk.main_quit()
        return False  # remove the signal source

    def _release_touch_device(self) -> None:
        if self.touch_fd < 0:
            return
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

    def cleanup(self) -> None:
        """Stop everything and give the hardware back: restore a dimmed bottom screen, release the touchscreen grab and
        any held button or key, remove the IPC socket. Safe to call more than once, and each step is guarded so that one
        failure cannot skip the rest."""
        if self._cleaned:
            return
        self._cleaned = True
        self.logger.log(DebugCode.DAEMON_STOPPING)

        def step(name: str, fn) -> None:
            try:
                fn()
            except Exception as err:
                self.logger.log(DebugCode.ERR_SERVICE_STOP, f"cleanup step '{name}' failed: {type(err).__name__}: {err}")

        step("restore the bottom screen", self.dim_mirror.stop)
        step("idle tracker", self.idle_tracker.stop)
        step("stats sampler", self.stats.stop_sampler)
        step("key repeat", self._stop_key_repeat)
        self.touch_stop.set()
        self._gleipnir_wake.set()
        self.ipc_stop.set()
        step("ipc socket", lambda: os.path.exists(SOCKET_PATH) and os.remove(SOCKET_PATH))
        step("touchscreen grab", self._release_touch_device)
        step("virtual devices", self.bridge.close)
        self.logger.log(DebugCode.DAEMON_STOPPED)

    # -------------------------------------------------------------------------
    # Touch Input Processing (Raw Digitizer Thread)
    # -------------------------------------------------------------------------

    def _start_touch_reader(self) -> None:
        node = self._find_bottom_touchscreen()
        if not node:
            self.logger.log(DebugCode.ERR_TOUCH_MISSING, "No bottom touchscreen digitizer located; looking again in 5 s")
            GLib.timeout_add_seconds(5, self._retry_touch_reader)
            return

        self.touch_dev_node = node
        try:
            self.touch_fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
            EVIOCGRAB = (1 << 30) | (struct.calcsize("i") << 16) | (ord("E") << 8) | 0x90
            fcntl.ioctl(self.touch_fd, EVIOCGRAB, 1)
            self.logger.log(DebugCode.TOUCH_OK, f"Exclusively grabbed {node}")
        except (PermissionError, OSError) as err:
            if self.touch_fd >= 0:
                try:
                    os.close(self.touch_fd)
                except OSError:
                    pass
                self.touch_fd = -1
            if isinstance(err, PermissionError):
                self.logger.log(DebugCode.ERR_TOUCH_OPEN, f"Permission denied accessing {node}; trying again in 5 s")
            else:
                self.logger.log(DebugCode.ERR_TOUCH_GRAB, f"Failed grabbing {node}: {err}; trying again in 5 s")
            GLib.timeout_add_seconds(5, self._retry_touch_reader)
            return

        def _reader_loop():
            parser = TouchFrameParser(raw_to_screen)
            self._parser = parser
            last_error_log = 0.0
            while not self.touch_stop.is_set():
                try:
                    r, _, _ = select.select([self.touch_fd], [], [], 0.1)
                except (OSError, ValueError) as err:
                    if self.touch_stop.is_set():
                        return  # cleanup() closed the descriptor under us: shutting down, not a lost device
                    # Ending this thread silently would leave the grab held and the bottom screen dead: restart instead.
                    self.logger.log(DebugCode.ERR_TOUCH_READ, f"select on the touch device failed ({err}); restarting")
                    GLib.idle_add(self._device_lost)
                    return
                if not r:
                    with self.input_lock:
                        self.gesture.expire_stale(time.time())  # kernel event timestamps are wall-clock
                    continue
                try:
                    data = os.read(self.touch_fd, EVENT_STRUCT.size * 256)
                except BlockingIOError:
                    continue
                except OSError as err:
                    if self.touch_stop.is_set():
                        return  # shutting down: cleanup() closed the descriptor
                    if err.errno in (errno.ENODEV, errno.EIO, errno.EBADF, errno.ENOENT):
                        # The digitizer went away (resume, re-enumeration). Exit so systemd restarts the service,
                        # which finds and grabs it again; spinning on a dead descriptor would burn a core.
                        self.logger.log(DebugCode.ERR_TOUCH_READ, f"touch device lost ({err}); restarting")
                        GLib.idle_add(self._device_lost)
                        return
                    self.logger.log(DebugCode.ERR_TOUCH_READ, f"read failed: {err}")
                    time.sleep(0.05)
                    continue
                if not data:
                    time.sleep(0.05)
                    continue
                self.idle_tracker.poke()  # the grabbed bottom touchscreen is invisible to the tracker
                try:
                    with self.input_lock:
                        for frame in parser.feed(data):
                            self._dispatch_frame(frame)
                except Exception as err:  # one bad frame must not end touch input while the grab is still held
                    now = time.monotonic()
                    if now - last_error_log > 5.0:
                        last_error_log = now
                        self.logger.log(DebugCode.ERR_TOUCH_READ, f"touch handler error: {type(err).__name__}: {err}")

        self.touch_thread = threading.Thread(target=_reader_loop, daemon=True)
        self.touch_thread.start()

    def _retry_touch_reader(self) -> bool:
        """One-shot GLib timeout: try again; _start_touch_reader schedules the next try if this one fails."""
        if not self.touch_stop.is_set() and self.touch_fd < 0:
            self._start_touch_reader()
        return False

    def _dispatch_frame(self, frame) -> None:
        self._lag_ms_max = max(self._lag_ms_max, (time.time() - frame.ts) * 1000.0)
        self.gesture.expire_stale(frame.ts)
        if frame.dropped:
            self.logger.log(
                DebugCode.ERR_TOUCH_READ,
                f"SYN_DROPPED: the kernel's touch buffer overflowed; contact state discarded (engine held {len(self.gesture.active_contacts)})",
            )
            self.gesture.reset_all()
            self._end_key_press()
            self._release_ui_button()
            self._touch_owner.clear()
            self._resync_contacts()
            return
        for tid in frame.ups:
            self._handle_touch_up(tid, frame.ts)
        for tid, x, y in frame.downs:
            self._handle_touch_down(tid, x, y, frame.ts)
        for tid, x, y in frame.moves:
            self._handle_touch_move(tid, x, y, frame.ts)
        if frame.live == 0 and not frame.downs:
            self.gesture.reset_all()
        self._last_frame_ts = frame.ts
        counts = (frame.live, len(self.gesture.active_contacts))
        if (frame.downs or frame.ups) and counts != self._last_contacts:
            self.logger.log(
                DebugCode.STATUS_TOUCH_DOWN if frame.downs else DebugCode.STATUS_TOUCH_UP,
                f"digitizer reports {counts[0]} contact(s), gesture engine holds {counts[1]}; downs={[(t, round(x), round(y)) for t, x, y in frame.downs]} ups={frame.ups} mode={self.mode}",
            )
        self._last_contacts = counts

    def _read_mt_slots(self) -> dict[int, tuple[int, int, int]]:
        """Current kernel state of every touch slot: {slot: (tracking id, raw x, raw y)}, live slots only."""
        absinfo = bytearray(24)
        fcntl.ioctl(self.touch_fd, _eviocgabs(ABS_MT_SLOT), absinfo)
        n = struct.unpack("6i", absinfo)[2] + 1  # maximum slot index + 1
        values = {}
        for code in (ABS_MT_TRACKING_ID, ABS_MT_POSITION_X, ABS_MT_POSITION_Y):
            buf = bytearray(struct.pack("I", code) + bytes(4 * n))
            fcntl.ioctl(self.touch_fd, _eviocgmtslots(len(buf)), buf)
            values[code] = struct.unpack(f"{n}i", bytes(buf[4:]))
        return {
            slot: (values[ABS_MT_TRACKING_ID][slot], values[ABS_MT_POSITION_X][slot], values[ABS_MT_POSITION_Y][slot])
            for slot in range(n) if values[ABS_MT_TRACKING_ID][slot] >= 0
        }

    def _resync_contacts(self) -> None:
        """After SYN_DROPPED the parser knows nothing; read the slots back so fingers already down are not lost."""
        if self._parser is None or self.touch_fd < 0:
            return
        try:
            slots = self._read_mt_slots()
        except (OSError, struct.error) as err:
            self.logger.log(DebugCode.ERR_TOUCH_READ, f"could not read the touch slots after SYN_DROPPED: {err}")
            return
        frame = self._parser.resync(slots, time.time())
        self.logger.log(DebugCode.STATUS_TOUCH_DOWN, f"resynced {len(frame.downs)} contact(s) after SYN_DROPPED")
        for tid, x, y in frame.downs:
            self._handle_touch_down(tid, x, y, frame.ts)

    def _device_lost(self) -> bool:
        self.exit_code = 1
        Gtk.main_quit()
        return False

    def _find_bottom_touchscreen(self) -> str | None:
        for node in sorted(glob.glob("/dev/input/event*")):
            try:
                with open(f"/sys/class/input/{os.path.basename(node)}/device/name", encoding="utf-8") as f:
                    name = f.read().strip().lower()
                    if "bottom" in name and "touchscreen" in name:
                        return node
            except OSError:
                pass
        return None

    # -------------------------------------------------------------------------
    # Touch Event Routing
    # -------------------------------------------------------------------------

    def _owner_at(self, x: float, y: float) -> str:
        """The area a touch belongs to, decided where it lands. It keeps that owner until it lifts, so a drag that
        crosses into another area (the split line, the header) is not cut off or handed to the wrong handler."""
        if y < HEADER_BUTTONS_H:
            return "header"
        if y < HEADER_HEIGHT:
            return "ribbon"
        if self.mode == "settings":
            return "settings"
        if self.mode == "keyboard" or (self.mode == "split" and y >= SPLIT_Y):
            return "keyboard"
        return "trackpad"

    def _send_keys(self, events) -> None:
        for code, down in events:
            self.bridge.key(code, down)
        self._sync_modifier_flags()

    def _sync_modifier_flags(self) -> None:
        """The keyboard drawing reads these flags from the layout."""
        kb = self.kb_layout
        kb.shift_active = self.mods.latched("shift")
        kb.caps_lock = self.mods.locked("shift")
        for mod in ("ctrl", "alt", "super"):
            setattr(kb, f"{mod}_active", self.mods.active(mod))

    def _end_key_press(self) -> None:
        """The held (non-modifier) key is over: stop its repeat and use up one-shot modifiers."""
        if self.held_key is None and self.held_key_tid is None:
            return
        self._stop_key_repeat()
        self._send_keys(self.mods.key_released())
        self.held_key = None
        self.held_key_tid = None
        self.active_key_press = None
        GLib.idle_add(self.drawing_area.queue_draw)

    def _release_ui_button(self) -> None:
        if self.held_ui_button == "left":
            self.bridge.mouse_button(BTN_LEFT, False)
        elif self.held_ui_button == "right":
            self.bridge.mouse_button(BTN_RIGHT, False)
        if self.held_ui_button:
            self.held_ui_button = None
            self.held_ui_button_tid = None
            GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_touch_down(self, tid: int, x: float, y: float, now: float) -> None:
        self.last_event_time = time.time()
        owner = self._owner_at(x, y)
        self._touch_owner[tid] = owner
        if owner == "header":
            self._handle_header_touch(tid, x, y, True)
        elif owner == "ribbon":  # the status ribbon toggles Quick Controls
            self.set_mode("trackpad" if self.mode == "settings" else "settings")
        elif owner == "settings":
            self._handle_settings_touch(tid, x, y)
        elif owner == "keyboard":
            self._keyboard_down(tid, x, y)
        else:
            self.gesture.touch_down(tid, x, y, now)
            if self.show_debug_hud:
                GLib.idle_add(self.drawing_area.queue_draw)

    def _keyboard_down(self, tid: int, x: float, y: float) -> None:
        key = self.kb_layout.hit_test(x, y)
        if not key:
            return
        if key.special in ("shift", "ctrl", "alt", "super"):
            window_s = self.keyboard_cfg["keyboard_caps_window_ms"] / 1000.0
            self._send_keys(self.mods.press(key.special, tid, time.monotonic(), window_s))
            self.active_key_press = key.code
            self.active_key_tid = tid
        else:
            if self.held_key is not None:
                self._end_key_press()  # a second finger types while the first still holds a key
            self.mods.key_typed()
            self.active_key_press = key.code
            self.active_key_tid = tid
            self.held_key = key
            self.held_key_tid = tid
            self.last_key_label = key.shift_label if self.mods.active("shift") else key.label
            self.bridge.tap_key(key.code)
            self._start_key_repeat(key)
        GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_touch_move(self, tid: int, x: float, y: float, now: float) -> None:
        self.last_event_time = time.time()
        owner = self._touch_owner.get(tid)
        if owner == "keyboard":
            k = self.held_key
            if k is not None and tid == self.held_key_tid and not (k.x <= x <= k.x + k.w and k.y <= y <= k.y + k.h):
                self._end_key_press()  # slid off the key: stop repeating
        elif owner == "settings":
            self._handle_settings_drag(tid, x, y)
        elif owner == "trackpad" or (owner is None and self.mode != "settings"):
            # None: a contact from before a restart or a dropped frame; the engine ignores ids it does not hold
            self.gesture.touch_move(tid, x, y, now)
            if self.show_debug_hud:
                GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_touch_up(self, tid: int, now: float) -> None:
        self.last_event_time = time.time()
        owner = self._touch_owner.pop(tid, None)
        if self._slider_drag and self._slider_drag[0] == tid:
            self._slider_drag = None
        if self.held_ui_button and tid == self.held_ui_button_tid:
            self._release_ui_button()
        if owner == "keyboard":
            if self.mods.is_modifier_touch(tid):
                self._send_keys(self.mods.release(tid))
            elif tid == self.held_key_tid:
                self._end_key_press()
            # A tap that turns a modifier off is no longer a modifier touch, so clear the pressed look by touch id
            if tid == self.active_key_tid:
                self.active_key_press = None
                self.active_key_tid = None
            GLib.idle_add(self.drawing_area.queue_draw)
        elif owner == "trackpad" or (owner is None and self.mode != "settings"):
            self.gesture.touch_up(tid, now)
            if self.show_debug_hud:
                GLib.idle_add(self.drawing_area.queue_draw)

    def _handle_header_touch(self, tid: int, x: float, y: float, down: bool) -> None:
        key = next((k for k, bx, bw in HEADER_BUTTONS if bx <= x <= bx + bw), None)
        if key in ("trackpad", "split", "keyboard", "settings"):
            self.set_mode(key)
        elif key == "hud":
            self.show_debug_hud = not self.show_debug_hud
            self.save_config()
            GLib.idle_add(self.drawing_area.queue_draw)
        elif key in ("left", "right"):
            self.held_ui_button = key
            self.held_ui_button_tid = tid
            self.bridge.mouse_button(BTN_LEFT if key == "left" else BTN_RIGHT, True)
            GLib.idle_add(self.drawing_area.queue_draw)
        elif key == "pen":
            self.set_pen_mode(pm.cycle(self.pen_mode))

    def _handle_settings_touch(self, tid: int, x: float, y: float) -> None:
        def in_ctrl_row(card: int) -> bool:
            top = QC_CARD_Y[card] + QC_CTRL_DY
            return top - 6 <= y <= top + QC_CTRL_H + 6

        # Card 1: Volume
        if in_ctrl_row(0):
            if 30 <= x <= 120:
                self.stats.adjust_volume(-5)
            elif 130 <= x <= 950:
                pct = round((x - 130) / (950 - 130) * 100)
                self.stats.request_volume(pct)
                self._slider_drag = (tid, "vol")
            elif 960 <= x <= 1050:
                self.stats.adjust_volume(5)
            elif 1060 <= x <= 1210:
                self.stats.toggle_mute()
            GLib.idle_add(self.drawing_area.queue_draw)
            return

        # Card 2: Top Brightness
        if in_ctrl_row(1):
            if 30 <= x <= 120:
                self.stats.adjust_top_brightness(-10)
            elif 130 <= x <= 1090:
                pct = round((x - 130) / (1090 - 130) * 100)
                self.stats.request_top_brightness(pct)
                self._slider_drag = (tid, "top")
            elif 1100 <= x <= 1210:
                self.stats.adjust_top_brightness(10)
            GLib.idle_add(self.drawing_area.queue_draw)
            return

        # Card 3: Bottom Brightness
        if in_ctrl_row(2):
            if 30 <= x <= 120:
                self.stats.adjust_bottom_brightness(-10)
            elif 130 <= x <= 1090:
                pct = round((x - 130) / (1090 - 130) * 100)
                self.stats.request_bottom_brightness(pct)
                self._slider_drag = (tid, "bot")
            elif 1100 <= x <= 1210:
                self.stats.adjust_bottom_brightness(10)
            GLib.idle_add(self.drawing_area.queue_draw)
            return

        # Bottom Action Buttons
        if QC_BUTTONS_Y - 6 <= y <= QC_BUTTONS_Y + QC_BUTTONS_H + 6:
            if 30 <= x <= 310:
                self.gesture.tap_to_click = not self.gesture.tap_to_click
                self.save_config()
            elif 330 <= x <= 610:
                # Toggle right-click mode between 2-finger and long-press (mutually exclusive)
                if self.gesture.two_finger_right_click:
                    self.gesture.two_finger_right_click = False
                    self.gesture.long_press_right_click = True
                else:
                    self.gesture.two_finger_right_click = True
                    self.gesture.long_press_right_click = False
                self.save_config()
            elif 630 <= x <= 910:
                self.show_debug_hud = not self.show_debug_hud
                self.save_config()
            elif 930 <= x <= 1210:
                self.set_mode("trackpad")
            GLib.idle_add(self.drawing_area.queue_draw)


    SLIDER_SPAN = {"vol": (130.0, 950.0), "top": (130.0, 1090.0), "bot": (130.0, 1090.0)}

    def _handle_settings_drag(self, tid: int, x: float, y: float) -> None:
        """A slider keeps following the finger that grabbed it, wherever that finger goes: only x matters."""
        drag = self._slider_drag
        if drag is None or drag[0] != tid:
            return
        lo, hi = self.SLIDER_SPAN[drag[1]]
        pct = round((min(max(x, lo), hi) - lo) / (hi - lo) * 100)
        if drag[1] == "vol":
            self.stats.request_volume(pct)
        elif drag[1] == "top":
            self.stats.request_top_brightness(pct)
        else:
            self.stats.request_bottom_brightness(pct)
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
                        msg = ipc_util.read_json_request(conn)
                        if msg is None:
                            continue
                        if not isinstance(msg, dict):
                            raise ValueError("a request must be a JSON object")
                        action = msg.get("action")
                        res = {"ok": True, "code": int(DebugCode.OK)}

                        if action == "get_status":
                            res["mode"] = self.mode
                            res["debug_hud"] = self.show_debug_hud
                            res["hardware_stats"] = self.stats.get_stats()
                            res.update(self.gesture.get_settings())
                            res.update(self.mirror_cfg)
                            res.update(self.keyboard_cfg)
                            res.update(self.gleipnir_cfg)
                            res["gleipnir_available"] = gleipnir_view.find_script() is not None
                            res["bottom_dimmed"] = self.dim_mirror.dimmed
                            res.update(self._cursor_status)
                            res["pen_mode"] = self.pen_mode
                        elif action == "get_debug":
                            res["telemetry"] = self.bridge.get_telemetry()
                            res["state"] = self.gesture.last_state_label
                            res["coords"] = self.gesture.last_coords
                            res["touch_device"] = self.touch_dev_node
                            res["active_fingers"] = len(self.gesture.active_contacts)
                            res["digitizer_contacts"] = len(self._parser.active) if self._parser else 0
                            res["engine_contacts"] = {str(t): [round(c["last_x"]), round(c["last_y"]), round(self._last_frame_ts - c["start_t"], 1)] for t, c in self.gesture.active_contacts.items()}
                            res["last_key"] = self.last_key_label
                            res["draws"] = self._draws
                            res["draw_ms_avg"] = round(self._draw_ms_sum / self._draws, 1) if self._draws else 0.0
                            res["draw_ms_max"] = round(self._draw_ms_max, 1)
                            res["frame_lag_ms_max"] = round(self._lag_ms_max, 1)
                            if msg.get("reset"):  # the Decky panel polls every 2 s; it must not wipe the window
                                self._draws, self._draw_ms_sum, self._draw_ms_max, self._lag_ms_max = 0, 0.0, 0.0, 0.0
                            res["hardware_stats"] = self.stats.get_stats()
                            res.update(self.gesture.get_settings())
                        elif action == "set_mode":
                            self.set_mode(msg.get("mode", "trackpad"))
                        elif action == "set_settings":
                            with self.input_lock:  # the touch thread may be in the gesture engine right now
                                self.gesture.set_settings(**msg)
                                self._apply_mirror_settings(msg)
                                keyboard_settings.apply(self.keyboard_cfg, msg)
                                self._apply_gleipnir_settings(msg)
                                if "debug_hud" in msg:
                                    self.show_debug_hud = bool(msg["debug_hud"])
                            self.save_config()
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_volume":
                            res["vol_pct"] = self.stats.request_volume(msg.get("volume", 50))
                            self.logger.log(DebugCode.VOLUME_UPDATED, f"volume={res['vol_pct']}%")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "toggle_mute":
                            res["vol_muted"] = self.stats.toggle_mute()
                            self.logger.log(DebugCode.VOLUME_UPDATED, f"muted={res['vol_muted']}")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_top_brightness":
                            res["top_bright_pct"] = self.stats.request_top_brightness(msg.get("brightness", 100))
                            self.logger.log(DebugCode.BACKLIGHT_UPDATED, f"top={res['top_bright_pct']}%")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_bottom_brightness":
                            res["bot_bright_pct"] = self.stats.request_bottom_brightness(msg.get("brightness", 100))
                            self.logger.log(DebugCode.BACKLIGHT_UPDATED, f"bottom={res['bot_bright_pct']}%")
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "set_pen_mode":
                            res["pen_mode"] = self.set_pen_mode(msg.get("mode"))
                            res.update(self._cursor_status)
                        elif action == "wake":
                            # A harmless key tap on the virtual keyboard: Steam and the compositor see it as input,
                            # so the sleep and dim timers restart and a dimmed top screen wakes.
                            self.bridge.tap_key(KEY_F24)
                            self.idle_tracker.poke()
                        elif action == "toggle_hud":
                            self.show_debug_hud = not self.show_debug_hud
                            self.save_config()
                            res["debug_hud"] = self.show_debug_hud
                            GLib.idle_add(self.drawing_area.queue_draw)
                        elif action == "run_diagnostics":
                            res["diagnostics"] = run_self_diagnostics()
                        elif action == "quit":
                            GLib.idle_add(self.window.close)
                        else:
                            res.update(ok=False, code=int(DebugCode.ERR_SOCKET_PROTOCOL), error=f"unknown action: {action!r}")
                        conn.sendall(json.dumps(res).encode("utf-8"))
                    except Exception as err:
                        self.logger.log(DebugCode.ERR_SOCKET_PROTOCOL, f"{type(err).__name__}: {err}")
                        try:  # answer instead of leaving the client to time out
                            conn.sendall(json.dumps({"ok": False, "code": int(DebugCode.ERR_SOCKET_PROTOCOL), "error": f"{type(err).__name__}: {err}"}).encode("utf-8"))
                        except OSError:
                            pass

            server_sock.close()

        self.ipc_thread = threading.Thread(target=_ipc_loop, daemon=True)
        self.ipc_thread.start()

    # -------------------------------------------------------------------------
    # Cairo Drawing (AMOLED UI, Keyboard, Ribbon & Quick Controls)
    # -------------------------------------------------------------------------

    def on_draw(self, _, cr: cairo.Context) -> bool:
        started = time.perf_counter()
        try:
            return self._paint(cr)
        finally:
            took = (time.perf_counter() - started) * 1000.0
            self._draw_ms_sum += took
            self._draw_ms_max = max(self._draw_ms_max, took)
            self._draws += 1

    def _paint(self, cr: cairo.Context) -> bool:
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
            self._draw_trackpad_surface(cr, HEADER_HEIGHT, SPLIT_Y - HEADER_HEIGHT)
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

        for key, x, w in HEADER_BUTTONS:
            label, active, accent = self._header_button_look(key)
            self._draw_button(cr, x, HEADER_BUTTON_Y, w, HEADER_BUTTON_H, label, active, accent_color=accent)

    def _header_button_look(self, key: str):
        """(label, active, accent colour) of a header button."""
        if key in ("trackpad", "split", "keyboard"):
            return key.capitalize(), self.mode == key, (0.38, 0.25, 0.85)
        if key == "settings":
            return "Quick Controls", self.mode == "settings", (0.20, 0.55, 0.90)
        if key == "hud":
            return "HUD", self.show_debug_hud, (0.15, 0.65, 0.45)
        if key == "left":
            return "Left Click", self.held_ui_button == "left", (0.3, 0.45, 0.95)
        if key == "right":
            return "Right Click", self.held_ui_button == "right", (0.85, 0.35, 0.35)
        return pm.label(self.pen_mode), self.pen_mode != "off", (0.95, 0.65, 0.20)

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

        # Telemetry pills text: one size for all, as large as fits across the screen
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

        # Battery
        # Plain-text labels: the Thor's fonts have no emoji, which drew as empty boxes (seen in tests/render_screens.py)
        bat_icon = "CHG" if "charg" in st.get("bat_status", "").lower() else "BAT"
        bat_txt = f"{bat_icon} {st.get('bat_cap', 0)}% ({st.get('bat_watts', 0)}W)"
        # CPU
        cpu_txt = f"CPU {st.get('cpu_load', 0)}% · {st.get('cpu_temp', 0)}°C"
        # GPU
        gpu_txt = f"GPU {st.get('gpu_mhz', 0)}M · {st.get('gpu_temp', 0)}°C"
        # RAM
        ram_txt = f"RAM {st.get('ram_used_gb', 0)}/{st.get('ram_total_gb', 0)}G"
        # Volume
        vol_txt = "Muted" if st.get("vol_muted") else f"Vol {st.get('vol_pct', 0)}%"
        # Brightness
        brt_txt = f"Top {st.get('top_bright_pct', 100)}% · Bot {st.get('bot_bright_pct', 100)}%"

        bat_col = (0.3, 0.85, 0.5)
        if self.gleipnir_cfg["gleipnir_ribbon"]:
            view = gleipnir_view.summary(self.gleipnir_status)
            if view:
                bat_txt, bat_col = view
        pills = [
            (bat_txt, bat_col),
            (cpu_txt, (0.4, 0.75, 1.0)),
            (gpu_txt, (0.95, 0.7, 0.3)),
            (ram_txt, (0.75, 0.6, 0.95)),
            (vol_txt, (0.9, 0.5, 0.5) if st.get("vol_muted") else (0.4, 0.85, 0.9)),
            (brt_txt, (1.0, 0.85, 0.4)),
        ]

        # Two rows of three cells; one font size for all, as large as the widest text allows
        cols, pad = 3, 20.0
        cell_w = (SCREEN_WIDTH - 2 * pad) / cols
        cr.set_font_size(RIBBON_TEXT_MAX_PX)
        widest = max(cr.text_extents(t).x_advance for t, _ in pills)
        cr.set_font_size(RIBBON_TEXT_MAX_PX * min(1.0, (cell_w - 16.0) / widest))
        cap = cr.text_extents("H").height
        row_h = rh / 2.0
        for i, (text, col) in enumerate(pills):
            cx = pad + cell_w * (i % cols) + cell_w / 2.0
            cy = ry + row_h * (i // cols) + row_h / 2.0
            ext = cr.text_extents(text)
            cr.set_source_rgb(*col)
            cr.move_to(cx - ext.x_advance / 2.0, cy + cap / 2.0)
            cr.show_text(text)

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

        key_render._fit(cr, text, min(h * 0.40, BUTTON_TEXT_MAX_PX), w - 16.0)
        key_render._show_centered(cr, text, x + w / 2.0, y + h / 2.0)

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

        # Center prompt hint (clean, no scrollbar clutter)
        cr.set_source_rgb(0.30, 0.34, 0.42)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(22.0)
        hint = "Ratatoskr: 1 finger moves · Tap clicks · 2 fingers scroll · Flick glides"
        if self.gesture.stylus_mode:
            hint = "Pen: touch moves · Double-tap clicks · Hold right-clicks · Edge strips scroll"
            if self.pen_mode == "pen_plus" and not self._cursor_status["cursor_stay_visible_active"]:
                hint = "Pen +: restart Game Mode to keep the pointer visible (until then Pen's nudges stay on)"
        extents = cr.text_extents(hint)
        cr.move_to(pad_x + (pad_w - extents.width) / 2.0, pad_y + (pad_h + extents.height) / 2.0)
        cr.show_text(hint)

        if self.gesture.stylus_mode:
            self._draw_scroll_strips(cr, pad_y, pad_h, show_bottom=(y + h) >= SCREEN_HEIGHT - 1)

    def _draw_scroll_strips(self, cr: cairo.Context, pad_y: float, pad_h: float, show_bottom: bool) -> None:
        """Pen mode's scroll strips: drag along the right edge to scroll up and down, along the bottom to scroll sideways."""
        right_x = SCREEN_WIDTH - STRIP_RIGHT_W
        bottom_y = SCREEN_HEIGHT - STRIP_BOTTOM_H
        strips = [(right_x, pad_y + 8.0, STRIP_RIGHT_W - 28.0, (bottom_y - pad_y - 16.0) if show_bottom else (pad_h - 16.0), "▲  scroll  ▼")]
        if show_bottom:
            strips.append((28.0, bottom_y + 8.0, right_x - 40.0, STRIP_BOTTOM_H - 28.0, "◀  scroll  ▶"))
        for sx, sy, sw, sh, label in strips:
            self._round_rect(cr, sx, sy, sw, sh, 14.0)
            cr.set_source_rgb(0.09, 0.10, 0.14)
            cr.fill_preserve()
            cr.set_source_rgb(0.95, 0.65, 0.20)
            cr.set_line_width(1.2)
            cr.stroke()
            cr.new_path()
            cr.set_source_rgb(0.95, 0.65, 0.20)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(20.0)
            ext = cr.text_extents(label)
            if sh > sw:  # vertical strip: write the label sideways
                cr.save()
                cr.translate(sx + sw / 2.0 + ext.height / 2.0, sy + sh / 2.0 + ext.width / 2.0)
                cr.rotate(-1.5707963)
                cr.show_text(label)
                cr.restore()
            else:
                cr.move_to(sx + (sw - ext.width) / 2.0, sy + (sh + ext.height) / 2.0)
                cr.show_text(label)

    def _draw_keyboard(self, cr: cairo.Context) -> None:
        """Render virtual keyboard with clean key highlighting, vector arrows, and dual symbol labels."""
        shift_on = self.kb_layout.shift_active or self.kb_layout.caps_lock

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

                # Draw Labels / Glyphs
                if k.has_sub_symbol:
                    # Two-symbol keys (1 / !, - / _, [ / {): the symbol that will be typed is large and centred
                    key_render.draw_dual_label(cr, k, shift_on, is_active)

                elif k.code in (105, 103, 108, 106):  # Left, Up, Down, Right arrows
                    cx = k.x + k.w / 2.0
                    cy = k.y + k.h / 2.0
                    sz = 6.5
                    if is_active:
                        cr.set_source_rgb(1.0, 1.0, 1.0)
                    else:
                        cr.set_source_rgb(0.92, 0.94, 0.96)

                    if k.code == 105:  # KEY_LEFT
                        cr.move_to(cx - sz, cy)
                        cr.line_to(cx + sz * 0.8, cy - sz)
                        cr.line_to(cx + sz * 0.8, cy + sz)
                    elif k.code == 106:  # KEY_RIGHT
                        cr.move_to(cx + sz, cy)
                        cr.line_to(cx - sz * 0.8, cy - sz)
                        cr.line_to(cx - sz * 0.8, cy + sz)
                    elif k.code == 103:  # KEY_UP
                        cr.move_to(cx, cy - sz)
                        cr.line_to(cx - sz, cy + sz * 0.8)
                        cr.line_to(cx + sz, cy + sz * 0.8)
                    elif k.code == 108:  # KEY_DOWN
                        cr.move_to(cx, cy + sz)
                        cr.line_to(cx - sz, cy - sz * 0.8)
                        cr.line_to(cx + sz, cy - sz * 0.8)
                    cr.close_path()
                    cr.fill()
                    cr.new_path()

                else:
                    # Normal letter or modifier
                    if k.special == "shift" and self.kb_layout.caps_lock:
                        label = "CAPS"
                    elif shift_on and k.is_letter:
                        label = k.shift_label
                    else:
                        label = k.label

                    key_render.draw_plain_label(cr, k, label, is_active, shift_on and k.is_letter)

    def _draw_quick_settings(self, cr: cairo.Context) -> None:
        """Render full Quick Settings dashboard cards."""
        st = self.stats.get_stats()

        # Card 1: Master Audio Volume
        self._draw_slider_card(
            cr,
            x=20,
            y=QC_CARD_Y[0],
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
            y=QC_CARD_Y[1],
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
            y=QC_CARD_Y[2],
            w=SCREEN_WIDTH - 40,
            h=120,
            title=f"Bottom AMOLED Brightness: {st.get('bot_bright_pct', 100)}%",
            pct=st.get("bot_bright_pct", 100),
            track_w=960,
            has_mute=False,
            accent_col=(0.30, 0.85, 0.60),
        )

        # Card 4: Hardware Health Monitor Grid
        self._round_rect(cr, 20, QC_HEALTH_Y, SCREEN_WIDTH - 40, QC_HEALTH_H, 18.0)
        cr.set_source_rgb(0.06, 0.07, 0.10)
        cr.fill_preserve()
        cr.set_source_rgb(0.18, 0.20, 0.26)
        cr.set_line_width(1.5)
        cr.stroke()
        cr.new_path()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(22.0)
        cr.set_source_rgb(0.85, 0.88, 0.95)
        cr.move_to(44, QC_HEALTH_Y + 38.0)
        cr.show_text("Live System Health & Power Telemetry")

        grid_items = [
            ("Battery Status", f"{st.get('bat_cap', 0)}% · {st.get('bat_status', 'N/A')} ({st.get('bat_watts', 0)} W)", (0.3, 0.85, 0.5)),
            ("CPU Processor", f"{st.get('cpu_load', 0)}% Load · {st.get('cpu_ghz', 0)} GHz · {st.get('cpu_temp', 0)}°C", (0.4, 0.75, 1.0)),
            ("GPU Adreno", f"{st.get('gpu_mhz', 0)} MHz · {st.get('gpu_temp', 0)}°C", (0.95, 0.7, 0.3)),
            ("System RAM", f"{st.get('ram_used_gb', 0)} / {st.get('ram_total_gb', 0)} GB ({st.get('ram_pct', 0)}%)", (0.75, 0.6, 0.95)),
        ]

        gx = 44.0
        gy = QC_HEALTH_Y + 82.0
        for i, (label, val, col) in enumerate(grid_items):
            rx = gx if (i % 2 == 0) else gx + 580.0
            ry = gy if (i < 2) else gy + 75.0

            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(18.0)
            cr.set_source_rgb(0.62, 0.67, 0.78)
            cr.move_to(rx, ry)
            cr.show_text(label)

            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(22.0)
            cr.set_source_rgb(*col)
            cr.move_to(rx, ry + 30.0)
            cr.show_text(val)

        # Action Buttons
        tap_active = self.gesture.tap_to_click
        tap_label = "Tap Click: ON" if tap_active else "Tap Click: OFF"
        self._draw_button(cr, 30, QC_BUTTONS_Y, 280, QC_BUTTONS_H, tap_label, tap_active, accent_color=(0.15, 0.55, 0.95))

        right_2f = self.gesture.two_finger_right_click
        right_label = "Right: 2-Finger" if right_2f else "Right: Press-Hold"
        self._draw_button(cr, 330, QC_BUTTONS_Y, 280, QC_BUTTONS_H, right_label, right_2f, accent_color=(0.2, 0.75, 0.65))

        hud_label = "Glass HUD: ON" if self.show_debug_hud else "Glass HUD: OFF"
        self._draw_button(cr, 630, QC_BUTTONS_Y, 280, QC_BUTTONS_H, hud_label, self.show_debug_hud, accent_color=(0.2, 0.65, 0.4))

        self._draw_button(cr, 930, QC_BUTTONS_Y, 280, QC_BUTTONS_H, "Back to Trackpad", False, accent_color=(0.38, 0.25, 0.85))

        if self.gleipnir_cfg["gleipnir_ribbon"]:
            line = gleipnir_view.detail(self.gleipnir_status)
            key_render._fit(cr, line, 22.0, SCREEN_WIDTH - 60.0)
            cr.set_source_rgb(0.75, 0.80, 0.90)
            cr.move_to(30.0, QC_BUTTONS_Y + QC_BUTTONS_H + 48.0)
            cr.show_text(line)


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
        cr.set_font_size(22.0)
        cr.set_source_rgb(0.88, 0.90, 0.96)
        cr.move_to(x + 24, y + 34)
        cr.show_text(title)

        ctrl_y = y + QC_CTRL_DY
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
        hud_w, hud_h = 400.0, 190.0
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
        cr.set_font_size(15.0)
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
    app = ThorApp()
    # systemd stops the service with SIGTERM. The default action ends the process on the spot and skips cleanup(), which
    # left a dimmed bottom screen dim and held buttons held. Leave the main loop instead.
    try:
        from gi.repository import GLibUnix  # GLib.unix_signal_add is deprecated in favour of this

        signal_add = GLibUnix.signal_add
    except (ImportError, AttributeError):
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal_add(GLib.PRIORITY_HIGH, sig, app.request_quit, sig)
    app.start()
    try:
        Gtk.main()
    finally:
        app.cleanup()
    sys.exit(app.exit_code)


if __name__ == "__main__":
    main()
