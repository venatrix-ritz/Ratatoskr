"""Thor Input Engine: handles /dev/uinput virtual devices and touch gesture processing with diagnostics."""
from __future__ import annotations

import fcntl
import math
import os
import struct
import sys
import threading
import time
from pathlib import Path

# Add parent directory for debug_codes import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from debug_codes import DebugCode, DebugLogger

# Linux input event constants
UINPUT = "/dev/uinput"
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503  # _IOW('U', 3, struct uinput_setup)
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

SYN_REPORT = 0
REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
REL_WHEEL_HI_RES = 11
REL_HWHEEL_HI_RES = 12

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112

ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39

BUS_VIRTUAL = 0x06
EVENT_STRUCT = struct.Struct("llHHi")
SETUP_STRUCT = struct.Struct("HHHH80sI")

# Screen dimensions (bottom screen)
SCREEN_WIDTH = 1240
SCREEN_HEIGHT = 1080

# Gesture thresholds
TAP_MAX_TIME_S = 0.22
TAP_MAX_DISTANCE_PX = 16.0
DRAG_TIMEOUT_S = 0.28
SCROLL_DIVISOR = 8.0
HI_RES_NOTCH = 120


def raw_to_screen(raw_x: int, raw_y: int) -> tuple[float, float]:
    """Convert raw 1080x1240 sensor coords (rotated 90 deg) to 1240x1080 screen space."""
    return float(raw_y), float(SCREEN_HEIGHT - 1 - raw_x)


class UInputBridge:
    """Manages virtual mouse and keyboard via /dev/uinput with diagnostics."""

    def __init__(self, logger: DebugLogger | None = None) -> None:
        self.logger = logger or DebugLogger("uinput")
        self.lock = threading.Lock()
        self.mouse_fd = -1
        self.kb_fd = -1
        self.held_buttons: set[int] = set()
        self.held_keys: set[int] = set()

        # Telemetry counters
        self.count_mouse_moves = 0
        self.count_clicks_left = 0
        self.count_clicks_right = 0
        self.count_scrolls = 0
        self.count_keystrokes = 0

        self._init_devices()

    def _init_devices(self) -> None:
        try:
            self.mouse_fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as err:
            self.logger.log(DebugCode.ERR_UINPUT_OPEN, f"Mouse open failed: {err}")
            raise

        try:
            fcntl.ioctl(self.mouse_fd, UI_SET_EVBIT, EV_KEY)
            for b in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
                fcntl.ioctl(self.mouse_fd, UI_SET_KEYBIT, b)
            fcntl.ioctl(self.mouse_fd, UI_SET_EVBIT, EV_REL)
            for r in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES):
                fcntl.ioctl(self.mouse_fd, UI_SET_RELBIT, r)
            fcntl.ioctl(
                self.mouse_fd,
                UI_DEV_SETUP,
                SETUP_STRUCT.pack(BUS_VIRTUAL, 0x1234, 0x5678, 1, b"Thor Virtual Trackpad", 0),
            )
            fcntl.ioctl(self.mouse_fd, UI_DEV_CREATE)
            self.logger.log(DebugCode.UINPUT_OK, "Virtual Trackpad device registered")
        except OSError as err:
            self.logger.log(DebugCode.ERR_UINPUT_SETUP, f"Mouse setup failed: {err}")
            raise

        # 2. Virtual Keyboard
        try:
            self.kb_fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
            fcntl.ioctl(self.kb_fd, UI_SET_EVBIT, EV_KEY)
            for k in range(1, 248):
                try:
                    fcntl.ioctl(self.kb_fd, UI_SET_KEYBIT, k)
                except OSError:
                    pass
            fcntl.ioctl(
                self.kb_fd,
                UI_DEV_SETUP,
                SETUP_STRUCT.pack(BUS_VIRTUAL, 0x1234, 0x5679, 1, b"Thor Virtual Keyboard", 0),
            )
            fcntl.ioctl(self.kb_fd, UI_DEV_CREATE)
            self.logger.log(DebugCode.UINPUT_OK, "Virtual Keyboard device registered")
        except OSError as err:
            self.logger.log(DebugCode.ERR_UINPUT_SETUP, f"Keyboard setup failed: {err}")
            raise

    def emit_mouse_rel(self, dx: int, dy: int) -> None:
        if not dx and not dy:
            return
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        evs = [
            EVENT_STRUCT.pack(sec, usec, EV_REL, REL_X, dx),
            EVENT_STRUCT.pack(sec, usec, EV_REL, REL_Y, dy),
            EVENT_STRUCT.pack(sec, usec, EV_SYN, SYN_REPORT, 0),
        ]
        with self.lock:
            if self.mouse_fd >= 0:
                try:
                    os.write(self.mouse_fd, b"".join(evs))
                    self.count_mouse_moves += 1
                except OSError as err:
                    self.logger.log(DebugCode.ERR_UINPUT_WRITE, f"emit_mouse_rel: {err}")

    def emit_scroll(self, dx_units: int, dy_units: int) -> None:
        if not dx_units and not dy_units:
            return
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        evs = []
        if dy_units:
            evs.append(EVENT_STRUCT.pack(sec, usec, EV_REL, REL_WHEEL_HI_RES, dy_units))
            notches = dy_units // HI_RES_NOTCH
            if notches:
                evs.append(EVENT_STRUCT.pack(sec, usec, EV_REL, REL_WHEEL, notches))
        if dx_units:
            evs.append(EVENT_STRUCT.pack(sec, usec, EV_REL, REL_HWHEEL_HI_RES, dx_units))
            notches = dx_units // HI_RES_NOTCH
            if notches:
                evs.append(EVENT_STRUCT.pack(sec, usec, EV_REL, REL_HWHEEL, notches))
        evs.append(EVENT_STRUCT.pack(sec, usec, EV_SYN, SYN_REPORT, 0))
        with self.lock:
            if self.mouse_fd >= 0:
                try:
                    os.write(self.mouse_fd, b"".join(evs))
                    self.count_scrolls += 1
                except OSError as err:
                    self.logger.log(DebugCode.ERR_UINPUT_WRITE, f"emit_scroll: {err}")

    def mouse_button(self, button_code: int, down: bool) -> None:
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        val = 1 if down else 0
        evs = [
            EVENT_STRUCT.pack(sec, usec, EV_KEY, button_code, val),
            EVENT_STRUCT.pack(sec, usec, EV_SYN, SYN_REPORT, 0),
        ]
        with self.lock:
            if down:
                self.held_buttons.add(button_code)
                if button_code == BTN_LEFT:
                    self.count_clicks_left += 1
                    self.logger.log(DebugCode.STATUS_CLICK_LEFT)
                elif button_code == BTN_RIGHT:
                    self.count_clicks_right += 1
                    self.logger.log(DebugCode.STATUS_CLICK_RIGHT)
            else:
                self.held_buttons.discard(button_code)
            if self.mouse_fd >= 0:
                try:
                    os.write(self.mouse_fd, b"".join(evs))
                except OSError as err:
                    self.logger.log(DebugCode.ERR_UINPUT_WRITE, f"mouse_button: {err}")

    def key(self, key_code: int, down: bool) -> None:
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        val = 1 if down else 0
        evs = [
            EVENT_STRUCT.pack(sec, usec, EV_KEY, key_code, val),
            EVENT_STRUCT.pack(sec, usec, EV_SYN, SYN_REPORT, 0),
        ]
        with self.lock:
            if down:
                self.held_keys.add(key_code)
                self.count_keystrokes += 1
                self.logger.log(DebugCode.STATUS_KEY_PRESS, f"Key {key_code} DOWN")
            else:
                self.held_keys.discard(key_code)
            if self.kb_fd >= 0:
                try:
                    os.write(self.kb_fd, b"".join(evs))
                except OSError as err:
                    self.logger.log(DebugCode.ERR_UINPUT_WRITE, f"key: {err}")

    def tap_key(self, key_code: int, delay_s: float = 0.02) -> None:
        self.key(key_code, True)
        if delay_s > 0:
            time.sleep(delay_s)
        self.key(key_code, False)

    def release_all(self) -> None:
        with self.lock:
            for b in list(self.held_buttons):
                self.mouse_button(b, False)
            for k in list(self.held_keys):
                self.key(k, False)

    def get_telemetry(self) -> dict:
        with self.lock:
            return {
                "mouse_moves": self.count_mouse_moves,
                "clicks_left": self.count_clicks_left,
                "clicks_right": self.count_clicks_right,
                "scrolls": self.count_scrolls,
                "keystrokes": self.count_keystrokes,
                "held_buttons": list(self.held_buttons),
                "held_keys": list(self.held_keys),
            }

    def close(self) -> None:
        self.release_all()
        with self.lock:
            if self.mouse_fd >= 0:
                try:
                    fcntl.ioctl(self.mouse_fd, UI_DEV_DESTROY)
                except OSError:
                    pass
                os.close(self.mouse_fd)
                self.mouse_fd = -1
            if self.kb_fd >= 0:
                try:
                    fcntl.ioctl(self.kb_fd, UI_DEV_DESTROY)
                except OSError:
                    pass
                os.close(self.kb_fd)
                self.kb_fd = -1


class TouchGestureProcessor:
    """Interprets raw multi-touch contacts into pointer, scroll, and click actions."""

    def __init__(self, bridge: UInputBridge, logger: DebugLogger | None = None) -> None:
        self.bridge = bridge
        self.logger = logger or DebugLogger("gesture")
        self.sensitivity = 1.5
        self.glide_enabled = True
        self.tap_to_click = True
        self.two_finger_right_click = True

        # Touch tracking state
        self.active_contacts: dict[int, dict] = {}  # tid -> info
        self.start_time: float = 0.0
        self.last_move_time: float = 0.0
        self.accum_dist: float = 0.0
        self.max_fingers: int = 0
        self.is_dragging: bool = False
        self.last_tap_time: float = 0.0

        # Fractional accumulator for high-res subpixel delta
        self.rest_x: float = 0.0
        self.rest_y: float = 0.0

        # Glide velocity
        self.vel_x: float = 0.0
        self.vel_y: float = 0.0
        self.glide_thread: threading.Thread | None = None
        self.glide_stop = threading.Event()

        # Telemetry / HUD
        self.last_state_label = "IDLE"
        self.last_coords = (0.0, 0.0)

    def set_settings(self, sensitivity: float, glide: bool) -> None:
        self.sensitivity = max(0.2, min(5.0, float(sensitivity)))
        self.glide_enabled = bool(glide)

    def touch_down(self, tid: int, x: float, y: float, now: float) -> None:
        self.glide_stop.set()
        contact = {"id": tid, "start_x": x, "start_y": y, "last_x": x, "last_y": y, "start_t": now}
        self.active_contacts[tid] = contact
        count = len(self.active_contacts)
        self.max_fingers = max(self.max_fingers, count)
        self.last_coords = (x, y)
        self.last_state_label = f"DOWN ({count} finger{'s' if count > 1 else ''})"

        if count == 1:
            self.start_time = now
            self.last_move_time = now
            self.accum_dist = 0.0
            self.vel_x = 0.0
            self.vel_y = 0.0
            if (now - self.last_tap_time) < DRAG_TIMEOUT_S:
                self.is_dragging = True
                self.last_state_label = "DRAG LOCK"
                self.bridge.mouse_button(BTN_LEFT, True)

    def touch_move(self, tid: int, x: float, y: float, now: float) -> None:
        contact = self.active_contacts.get(tid)
        if not contact:
            return

        dx = x - contact["last_x"]
        dy = y - contact["last_y"]
        contact["last_x"] = x
        contact["last_y"] = y
        self.accum_dist += math.hypot(dx, dy)
        self.last_coords = (x, y)

        count = len(self.active_contacts)
        dt = max(0.001, now - self.last_move_time)
        self.last_move_time = now

        if count == 1:
            self.last_state_label = "DRAGGING" if self.is_dragging else "MOVE"
            speed = self.sensitivity
            mag = math.hypot(dx, dy)
            accel = 1.0 + min(1.5, mag / 30.0)
            target_dx = dx * speed * accel + self.rest_x
            target_dy = dy * speed * accel + self.rest_y

            ix = int(target_dx)
            iy = int(target_dy)
            self.rest_x = target_dx - ix
            self.rest_y = target_dy - iy

            if ix or iy:
                self.bridge.emit_mouse_rel(ix, iy)
                self.vel_x = (dx * speed * accel) / dt
                self.vel_y = (dy * speed * accel) / dt

        elif count == 2:
            self.last_state_label = "SCROLL"
            scroll_dy = int(-dy * (HI_RES_NOTCH / SCROLL_DIVISOR))
            scroll_dx = int(dx * (HI_RES_NOTCH / SCROLL_DIVISOR))
            if scroll_dx or scroll_dy:
                self.bridge.emit_scroll(scroll_dx, scroll_dy)

    def touch_up(self, tid: int, now: float) -> None:
        contact = self.active_contacts.pop(tid, None)
        if not contact:
            return

        if len(self.active_contacts) == 0:
            duration = now - self.start_time
            if self.is_dragging:
                self.is_dragging = False
                self.last_state_label = "DRAG END"
                self.bridge.mouse_button(BTN_LEFT, False)
            elif self.accum_dist < TAP_MAX_DISTANCE_PX and duration < TAP_MAX_TIME_S:
                if self.max_fingers == 1 and self.tap_to_click:
                    self.last_state_label = "TAP LEFT"
                    self.bridge.mouse_button(BTN_LEFT, True)
                    time.sleep(0.02)
                    self.bridge.mouse_button(BTN_LEFT, False)
                    self.last_tap_time = now
                elif self.max_fingers == 2 and self.two_finger_right_click:
                    self.last_state_label = "TAP RIGHT"
                    self.bridge.mouse_button(BTN_RIGHT, True)
                    time.sleep(0.02)
                    self.bridge.mouse_button(BTN_RIGHT, False)
            elif self.glide_enabled and self.max_fingers == 1:
                speed = math.hypot(self.vel_x, self.vel_y)
                if speed > 150.0:
                    self.last_state_label = "GLIDE"
                    self.logger.log(DebugCode.STATUS_GLIDE_START, f"velocity={speed:.1f}")
                    self._start_glide(self.vel_x, self.vel_y)

            self.max_fingers = 0
            if not self.glide_enabled or math.hypot(self.vel_x, self.vel_y) <= 150.0:
                self.last_state_label = "IDLE"

    def _start_glide(self, vx: float, vy: float) -> None:
        self.glide_stop.clear()

        def _glide_loop():
            cur_vx, cur_vy = vx, vy
            decay = 0.90
            dt = 0.016
            accum_x, accum_y = 0.0, 0.0
            while not self.glide_stop.is_set():
                cur_vx *= decay
                cur_vy *= decay
                if math.hypot(cur_vx, cur_vy) < 15.0:
                    break
                accum_x += cur_vx * dt
                accum_y += cur_vy * dt
                ix = int(accum_x)
                iy = int(accum_y)
                accum_x -= ix
                accum_y -= iy
                if ix or iy:
                    self.bridge.emit_mouse_rel(ix, iy)
                time.sleep(dt)
            self.last_state_label = "IDLE"

        self.glide_thread = threading.Thread(target=_glide_loop, daemon=True)
        self.glide_thread.start()
