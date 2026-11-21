"""PS mode: the bottom screen as the PS5 touchpad and PS buttons while Chiaki-NG (PS Remote Play) has focus.

Chiaki-NG (https://github.com/streetpea/chiaki-ng) reads no touchpad from a second virtual controller here: its
Flatpak builds without setsu, SDL3 reads gamepad touchpads only through HIDAPI, and Steam hides Sony pads from it
(SDL_GAMECONTROLLER_IGNORE_DEVICES). It does turn input on its own window into DualSense input (v1.10.1):
- a left-button drag is a touchpad touch at that spot of the window (gui/src/streamsession.cpp HandleMouseMoveEvent),
  and real touch events are touches too (HandleTouchEvent);
- keys: Esc = PS, O = Options, F = Share/Create, T = touchpad click (gui/src/settings.cpp GetControllerMapping);
  Ctrl+M toggles the microphone (gui/src/qmlmainwindow.cpp);
- each button change goes to the console as its own history event (lib/src/feedbacksender.c), and a mouse release
  clears the touchpad click whatever set it (HandleMouseReleaseEvent), so a pad click goes up before the touch lifts.
So the pad drives a virtual touchscreen that gamescope hands to the focused window (in Steam's default touch mode a
touch is a pointer warp with the left button held, gamescope wlserver.cpp wlserver_touchdown), and the buttons are
those keys. Only one finger reaches Chiaki this way.
"""
from __future__ import annotations

import math
import os
import select
import subprocess
import threading
import time

from engine import LONG_PRESS_MAX_DIST_PX, TAP_MAX_DISTANCE_PX, TAP_MAX_TIME_S

KEY_ESC = 1
KEY_T = 20
KEY_O = 24
KEY_F = 33
KEY_LEFTCTRL = 29
KEY_M = 50

# Buttons that stay down while the finger is on them, and the keys they hold.
HOLD_KEYS = {"create": (KEY_F,), "ps": (KEY_ESC,), "options": (KEY_O,)}
MIC_CHORD = (KEY_LEFTCTRL, KEY_M)
PAD_CLICK_KEY = KEY_T  # a tap on the pad, or a long press, clicks the touchpad where the finger is
BUTTONS = (("create", "Create"), ("ps", "PS"), ("options", "Options"), ("mic", "Mic"))
# A tap's click is held this long before the touch lifts, so a game that reads buttons once a frame still sees it.
TAP_CLICK_S = 0.05

# Keep the touch this far inside the window: in touch passthrough Chiaki makes its outer 5 % a touchpad click, and a
# touch at the very edge of the top screen may start a gamescope edge gesture.
EDGE_INSET = 0.06
# A tap with no motion is no touch for Chiaki (the drag path needs a move with the button down): every touch starts
# with this small step sideways.
NUDGE = 0.004
ROTATIONS = (0, 90, 180, 270)

STEAM_DISPLAY = ":0"
FOCUS_ATOM = "GAMESCOPE_FOCUSED_APP"
CHIAKI_COMMS = ("chiaki",)
FOCUS_POLL_S = 1.0            # xprop polling, only when python-xlib cannot be imported
FOCUS_SETTLE_S = 0.2          # gamescope writes the focused app in bursts (27 writes in 3 s seen): read once it settles
# Inside such a burst 17 of the 27 writes were empty (no app) for about 2 s before the app came back: an empty value
# only counts once it has lasted this long, so a focused Chiaki does not drop out of PS mode and back.
EMPTY_GRACE_S = 3.0
LATE_START_S, LATE_RESCAN_S = 10.0, 1.0  # after a focus change, look for a late-starting Chiaki this long, this often
RECONNECT_MIN_S, RECONNECT_MAX_S = 1.0, 30.0
WATCH_WAIT_S = 30.0           # longest block on the X socket with no event


class PsLayout:
    """The touchpad (16:9, like the PS5 touchpad's 1920 x 1080 report range) with the button row under it."""

    def __init__(self, top: float, width: float, height: float, margin: float = 20.0, gap: float = 16.0,
                 button_h: float = 170.0) -> None:
        self.pad_x = margin
        self.pad_w = width - 2 * margin
        self.pad_y = top + gap
        self.pad_h = min(self.pad_w * 9.0 / 16.0, height - margin - button_h - 2 * gap - top)
        self.button_y = self.pad_y + self.pad_h + gap
        self.button_h = min(button_h, height - margin - self.button_y)
        n = len(BUTTONS)
        bw = (self.pad_w - (n - 1) * 12.0) / n
        self.buttons = [(name, label, self.pad_x + i * (bw + 12.0), bw) for i, (name, label) in enumerate(BUTTONS)]

    def hit(self, x: float, y: float) -> str | None:
        """'pad', a button name, or None."""
        if self.pad_x <= x <= self.pad_x + self.pad_w and self.pad_y <= y <= self.pad_y + self.pad_h:
            return "pad"
        if self.button_y <= y <= self.button_y + self.button_h:
            for name, _label, bx, bw in self.buttons:
                if bx <= x <= bx + bw:
                    return name
        return None

    def to_unit(self, x: float, y: float) -> tuple[float, float]:
        """Pad position as 0..1 across and down the pad, clamped."""
        u = (x - self.pad_x) / self.pad_w
        v = (y - self.pad_y) / self.pad_h
        return min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)


def to_device(u: float, v: float, rotation: int = 0, inset: float = EDGE_INSET) -> tuple[float, float]:
    """Pad unit position to the virtual touchscreen's 0..1 axes: inset from the edges, then turned by `rotation`
    degrees (clockwise) for a compositor that turns the device's axes."""
    span = 1.0 - 2.0 * inset
    x, y = inset + u * span, inset + v * span
    if rotation == 90:
        return 1.0 - y, x
    if rotation == 180:
        return 1.0 - x, 1.0 - y
    if rotation == 270:
        return y, 1.0 - x
    return x, y


def normalize_rotation(value) -> int:
    try:
        value = int(value) % 360
    except (TypeError, ValueError):
        return 0
    return value if value in ROTATIONS else 0


class PsPad:
    """Touches on the PS screen to the virtual touchscreen and keys. Nothing goes out unless `active` (Chiaki has
    focus). The caller serialises calls with `lock` (thor_app's input_lock), which the click timers take too.

    `settings` is the trackpad's gesture processor: its `tap_to_click` and `long_press_delay_ms` apply here too."""

    def __init__(self, bridge, layout: PsLayout, lock=None, settings=None, clock=time.monotonic,
                 timer=threading.Timer) -> None:
        self.bridge = bridge
        self.layout = layout
        self.lock = lock if lock is not None else threading.RLock()
        self.settings = settings
        self._clock = clock
        self._timer = timer
        self.active = False
        self.rotation = 0
        self.finger: int | None = None  # the touch id that owns the virtual touch
        self.button_tids: dict[int, str] = {}  # touch id -> button it pressed
        self.blocked_touch_at = 0.0  # monotonic time of the last touch while Chiaki did not have focus
        self.clicking = False  # the pad click key is down (a tap's short click or a long press)
        self._down_at = 0.0
        self._down_xy = (0.0, 0.0)
        self._travel = 0.0  # furthest the owning finger got from where it landed, in screen px
        self._long_press = None  # timer that turns a still finger into a held click
        self._tap_release = None  # timer that ends a tap's click and lifts the touch
        self._touch_down = False  # the virtual touch is down (it outlives the finger during a tap's click)
        self.on_press = None  # called for each button press and pad click: the driver buzzes the haptics motor

    def set_active(self, active: bool) -> None:
        with self.lock:
            if not active:
                self.release_all()
            self.active = bool(active)

    def pressed(self, name: str) -> bool:
        return name in self.button_tids.values()

    def _tap_to_click(self) -> bool:
        return bool(getattr(self.settings, "tap_to_click", True))

    def _long_press_s(self) -> float:
        return float(getattr(self.settings, "long_press_delay_ms", 450)) / 1000.0

    def _device_point(self, x: float, y: float) -> tuple[float, float]:
        return to_device(*self.layout.to_unit(x, y), rotation=self.rotation)

    def _cancel(self, attr: str) -> None:
        t = getattr(self, attr)
        if t is not None:
            t.cancel()
            setattr(self, attr, None)

    def _buzz(self) -> None:
        if self.on_press is not None:
            self.on_press()

    def _click(self, down: bool) -> None:
        if down != self.clicking:
            self.bridge.key(PAD_CLICK_KEY, down)
            self.clicking = down
            if down:
                self._buzz()

    def _lift(self) -> None:
        """Click up first (a lift clears Chiaki's touchpad click anyway), then the touch."""
        self._click(False)
        if self._touch_down:
            self.bridge.ps_touch_up()
            self._touch_down = False

    def _finish_tap(self, timer=None) -> None:
        with self.lock:
            if timer is not None and timer is not self._tap_release:
                return  # an older tap that was already finished
            self._tap_release = None
            if self.finger is None:
                self._lift()

    def _on_long_press(self, timer=None) -> None:
        with self.lock:
            if timer is not self._long_press:
                return  # cancelled after it had already started waiting for the lock
            self._long_press = None
            if self.active and self.finger is not None and self._travel <= LONG_PRESS_MAX_DIST_PX:
                self._click(True)

    def touch_down(self, tid: int, x: float, y: float) -> str | None:
        hit = self.layout.hit(x, y)
        if hit is None:
            return None
        if not self.active:
            self.blocked_touch_at = self._clock()
            return hit
        if hit == "pad":
            if self.finger is None:
                if self._tap_release is not None:
                    self._cancel("_tap_release")
                    self._lift()  # the previous tap's click ends now, before this touch lands
                self.finger = tid
                self._down_at, self._down_xy, self._travel = self._clock(), (x, y), 0.0
                u, v = self.layout.to_unit(x, y)
                self.bridge.ps_touch(*to_device(u, v, self.rotation))
                nudged = u + NUDGE if u + NUDGE <= 1.0 else u - NUDGE
                self.bridge.ps_touch(*to_device(nudged, v, self.rotation))
                self._touch_down = True
                t = self._timer(self._long_press_s(), self._on_long_press)
                t.args = (t,)
                t.daemon = True
                self._long_press = t
                t.start()
            return hit
        self._buzz()
        if hit == "mic":
            for code in MIC_CHORD:
                self.bridge.key(code, True)
            for code in reversed(MIC_CHORD):
                self.bridge.key(code, False)
        elif not self.pressed(hit):
            for code in HOLD_KEYS[hit]:
                self.bridge.key(code, True)
        self.button_tids[tid] = hit
        return hit

    def touch_move(self, tid: int, x: float, y: float) -> None:
        if tid == self.finger:
            self._travel = max(self._travel, math.hypot(x - self._down_xy[0], y - self._down_xy[1]))
            if self._travel > LONG_PRESS_MAX_DIST_PX:
                self._cancel("_long_press")
            self.bridge.ps_touch(*self._device_point(x, y))

    def touch_up(self, tid: int) -> None:
        if tid == self.finger:
            self._cancel("_long_press")
            self.finger = None
            quick = self._clock() - self._down_at < TAP_MAX_TIME_S and self._travel <= TAP_MAX_DISTANCE_PX
            if not self.clicking and quick and self._tap_to_click():
                self._click(True)  # held for TAP_CLICK_S with the touch still down, then both go up
                t = self._timer(TAP_CLICK_S, self._finish_tap)
                t.args = (t,)
                t.daemon = True
                self._tap_release = t
                t.start()
            else:
                self._lift()
        name = self.button_tids.pop(tid, None)
        if name in HOLD_KEYS and not self.pressed(name):
            for code in HOLD_KEYS[name]:
                self.bridge.key(code, False)

    def release_all(self) -> None:
        """Lift the virtual touch and every held button key (focus lost, mode change, hidden UI, shutdown)."""
        self._cancel("_long_press")
        self._cancel("_tap_release")
        self.finger = None
        self._lift()
        held = set(self.button_tids.values())
        self.button_tids.clear()
        for name in held:
            for code in HOLD_KEYS.get(name, ()):
                self.bridge.key(code, False)


def parse_focused_app(text: str) -> int | None:
    """`xprop -root GAMESCOPE_FOCUSED_APP` output ('GAMESCOPE_FOCUSED_APP(CARDINAL) = 3174227830') to the app id."""
    if "=" not in text:
        return None
    try:
        return int(text.split("=", 1)[1].split(",")[0].strip())
    except ValueError:
        return None


def read_focused_app(run=subprocess.run, display: str = STEAM_DISPLAY) -> int | None:
    """The Steam app id gamescope reports as focused on Game Mode's X display, or None."""
    try:
        res = run(["xprop", "-display", display, "-root", FOCUS_ATOM], capture_output=True, text=True, timeout=1.0)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return parse_focused_app(res.stdout)


def chiaki_app_ids(proc_root: str = "/proc", comms: tuple[str, ...] = CHIAKI_COMMS) -> set[int]:
    """SteamAppId of every running Chiaki process (Steam puts it in the environment of what it launches), so any
    shortcut name works."""
    ids: set[int] = set()
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return ids
    for pid in pids:
        try:
            with open(os.path.join(proc_root, pid, "comm"), encoding="utf-8", errors="replace") as f:
                if f.read().strip() not in comms:
                    continue
            with open(os.path.join(proc_root, pid, "environ"), "rb") as f:
                env = f.read()
        except OSError:
            continue
        for item in env.split(b"\0"):
            if item.startswith(b"SteamAppId="):
                try:
                    ids.add(int(item.split(b"=", 1)[1]))
                except ValueError:
                    pass
    return ids


class XFocusSource:
    """One X connection to Game Mode's display that hears every write of the root window's GAMESCOPE_FOCUSED_APP
    (PropertyNotify), so nothing is polled. Raises (Xlib's ConnectionClosedError, OSError) once the display is gone.
    Needs python-xlib (README: Dependencies)."""

    def __init__(self, display: str = STEAM_DISPLAY) -> None:
        from Xlib import X, display as xdisplay

        self._X = X
        self.d = xdisplay.Display(display)
        self.root = self.d.screen().root
        self.atom = self.d.intern_atom(FOCUS_ATOM)
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.d.flush()

    def read(self) -> int | None:
        prop = self.root.get_full_property(self.atom, self._X.AnyPropertyType)
        return int(prop.value[0]) if prop is not None and len(prop.value) else None

    def wait(self, timeout: float) -> bool:
        """Block up to timeout s; True when the focused app was written. Consumes every queued event."""
        if not self.d.pending_events():  # a reply may already have pulled events off the socket
            ready, _, _ = select.select([self.d.fileno()], [], [], timeout)
            if not ready:
                return False
        return self.drain()

    def drain(self) -> bool:
        hit = False
        while self.d.pending_events():
            ev = self.d.next_event()
            if ev.type == self._X.PropertyNotify and ev.atom == self.atom:
                hit = True
        return hit

    def close(self) -> None:
        try:
            self.d.close()
        except Exception:
            pass


class FocusWatcher:
    """Calls on_change(bool) when Chiaki becomes, or stops being, the focused Game Mode app.

    Event-driven: an XFocusSource hears every write of GAMESCOPE_FOCUSED_APP, and a lost display (Game Mode
    restarting) counts as no focus at once and reconnects with backoff (RECONNECT_MIN_S doubling to RECONNECT_MAX_S);
    an empty value counts only after EMPTY_GRACE_S (gamescope writes short empty runs inside its bursts). Without
    python-xlib it polls xprop every FOCUS_POLL_S. Chiaki's app ids are read from /proc only when the focused app
    changes, then every `rescan` s for `late_start` s while that app is not yet a known Chiaki id."""

    def __init__(self, on_change, read_focus=read_focused_app, read_ids=chiaki_app_ids, connect=XFocusSource,
                 log=lambda msg: None, interval: float = FOCUS_POLL_S, rescan: float = LATE_RESCAN_S,
                 late_start: float = LATE_START_S, settle: float = FOCUS_SETTLE_S, empty_grace: float = EMPTY_GRACE_S,
                 clock=time.monotonic) -> None:
        self.on_change = on_change
        self.read_focus = read_focus
        self.read_ids = read_ids
        self.connect = connect
        self.log = log
        self.interval = interval
        self.rescan = rescan
        self.late_start = late_start
        self.settle = settle
        self.empty_grace = empty_grace
        self.clock = clock
        self.focused = False
        self.focused_app: int | None = None
        self.source = "starting"  # x11 | xprop | no display: shown in get_debug
        self.writes_heard = 0     # settled bursts of focus writes (x11 only)
        self.id_scans = 0
        self._seen: object = object()  # the app the ids were last looked up for; nothing matches it at first
        self._ids: set[int] = set()
        self._ids_at = float("-inf")
        self._late_until = float("-inf")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def update(self, app: int | None) -> bool:
        now = self.clock()
        if app != self._seen:
            self._seen = app
            self._late_until = now + self.late_start
            scan = app is not None
        else:
            scan = self._rescan_in(now) == 0.0
        if scan:
            self._ids, self._ids_at = self.read_ids(), now
            self.id_scans += 1
        self.focused_app = app
        focused = app is not None and app in self._ids
        if focused != self.focused:
            self.focused = focused
            self.on_change(focused)
        return focused

    def _rescan_in(self, now: float) -> float | None:
        """Seconds until the next late-start rescan of Chiaki's ids, or None when none is pending."""
        app = self._seen
        if not isinstance(app, int) or app in self._ids or now >= self._late_until:
            return None
        return max(0.0, self._ids_at + self.rescan - now)

    def poll_once(self) -> bool:
        return self.update(self.read_focus())

    def _settled_read(self, src) -> int | None:
        """The focused app; an empty value is read again until it has lasted empty_grace s."""
        app = src.read()
        deadline = self.clock() + self.empty_grace
        while app is None and self.focused_app is not None and not self._stop.is_set():
            left = deadline - self.clock()
            if left <= 0:
                break
            if src.wait(left):
                self._stop.wait(self.settle)
                src.drain()
            app = src.read()
        return app

    def _watch(self, src) -> None:
        self.update(src.read())
        while not self._stop.is_set():
            due = self._rescan_in(self.clock())
            if src.wait(WATCH_WAIT_S if due is None else due):
                self._stop.wait(self.settle)
                src.drain()
                self.writes_heard += 1
            self.update(self._settled_read(src))

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # a failed poll must not end the watcher
                pass
            self._stop.wait(self.interval)

    def _run(self) -> None:
        delay, failing = RECONNECT_MIN_S, False
        while not self._stop.is_set():
            try:
                src = self.connect()
            except ImportError as err:
                self.source = "xprop"
                self.log(f"python-xlib not importable ({err}); polling xprop every {self.interval:g} s instead")
                self._poll()
                return
            except Exception as err:
                self.source = "no display"
                self.update(None)  # no Game Mode display: Chiaki cannot have focus
                if not failing:
                    self.log(f"cannot open X display {STEAM_DISPLAY} ({type(err).__name__}: {err}); retrying with backoff")
                failing = True
                self._stop.wait(delay)
                delay = min(delay * 2, RECONNECT_MAX_S)
                continue
            failing = False
            self.source = "x11"
            self.log(f"watching {FOCUS_ATOM} on X display {STEAM_DISPLAY} (PropertyNotify, no polling)")
            began = self.clock()
            try:
                self._watch(src)
            except Exception as err:
                if not self._stop.is_set():
                    self.source = "no display"
                    self.log(f"lost X display {STEAM_DISPLAY} ({type(err).__name__}: {err}); reconnecting")
                    self.update(None)
            finally:
                src.close()
            if self.clock() - began >= RECONNECT_MAX_S:
                delay = RECONNECT_MIN_S  # it ran a while: a fresh failure starts the backoff over
            self._stop.wait(delay)
            delay = min(delay * 2, RECONNECT_MAX_S)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ps-focus", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
