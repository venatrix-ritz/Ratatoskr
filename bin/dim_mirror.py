"""Make the bottom panel follow the top panel's idle dim.

Steam dims only the top panel: Armada steers every Steam backlight write to the
primary panel (`steamos-priv-write`, `ARMADA_PRIMARY_BACKLIGHT`), so the bottom
panel keeps its brightness. This module watches the top panel's backlight and, when
it starts falling the way Steam's idle ramp does (about 260 writes over 30 s, 254 down
to 7), fades the bottom panel down; when the top comes back, or the bottom is touched,
it restores it. It does not read Steam's delay or track input to guess when Steam
will dim: the first version did, and on the Thor its idle clock ran up to 55 s ahead
of Steam's, because the physical controller (`/dev/input/event7`) is mode `c---------`
root:root and cannot be read (observed 2026-10-08). The top backlight is what Steam
actually decided.

Sleep is not handled here: Armada's fake-suspend sends `drm_sleep_internal_screen` to every
gamescope instance in the session (falling back to `bl_power` on every backlight), which should
cover the bottom panel too (`/usr/libexec/armada/fake-suspend`, `display_off`; not yet confirmed by
a test on the Thor).
"""
from __future__ import annotations

import glob
import json
import os
import select
import struct
import threading
import time
from typing import Callable

from debug_codes import DebugCode
from top_follower import TopFollower

TOP_BACKLIGHT = "/sys/class/backlight/ae96000.dsi.0"
# A fall of the top backlight only counts as Steam's idle dim after this long without input (a slider drag has input).
INPUT_QUIET_S = 5.0


def input_says_slider(idle: float, tracker_age: float) -> bool:
    """True when a falling top backlight is probably a slider drag: there was input within INPUT_QUIET_S. A tracker that
    has only just started has seen no input yet, so its idle time says nothing; then the guard does not apply (a restart
    during Steam's idle dim must still dim the bottom)."""
    return tracker_age >= INPUT_QUIET_S and idle < INPUT_QUIET_S


def _boot_now() -> float:
    """Seconds on a clock that keeps counting while the system sleeps (CLOCK_MONOTONIC stops). The follower must see
    the real gap across a suspend, or the last samples before it and the first after it look like one steep fall."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME") else time.monotonic()
# Armada's root service re-applies this saved level every 2 s whenever the backlight differs from it
# (armada-control: BOTTOM_SCREEN_BRIGHTNESS_RESTORE_INTERVAL), so a dim that does not change it is undone at once.
ARMADA_SAVED = "/etc/armada/bottom-screen-brightness"
STATE_DIR = os.path.expanduser("~/.local/state/thor-input")
RECOVERY_FILE = os.path.join(STATE_DIR, "dim-restore.json")  # the pre-dim level, so a crash cannot strand a dim

EV_KEY, EV_REL, EV_ABS = 0x01, 0x02, 0x03
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11
ABS_MT_FIRST = 0x2F  # ABS_MT_SLOT; the multitouch axes start here

_EVENT = struct.Struct("llHHi")

# Devices that are not the user: haptics, jack/lid switches, our own virtual devices.
_IGNORED_NAMES = ("haptics", "Jack", "lid", "Thor Virtual", "pmic_")
# Sticks and triggers count as activity only past this deflection (drift stays idle).
_STICK_THRESHOLD = 8000
_TRIGGER_THRESHOLD = 100


def read_saved_bottom_level(path: str = ARMADA_SAVED) -> int | None:
    """Armada's saved bottom-screen brightness (0-100), or None if absent or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            value = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def _is_activity(ev_type: int, code: int, value: int, name: str) -> bool:
    if ev_type == EV_KEY:
        return value == 1
    if ev_type == EV_REL:
        return True
    if ev_type != EV_ABS:
        return False
    if "touchscreen" in name:
        return code >= ABS_MT_FIRST or code in (ABS_X, ABS_Y)
    if code in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
        return abs(value) > _STICK_THRESHOLD
    if code in (ABS_Z, ABS_RZ):
        return value > _TRIGGER_THRESHOLD
    if code in (ABS_HAT0X, ABS_HAT0Y):
        return value != 0
    return False


def _device_name(node: str) -> str:
    try:
        with open(f"/sys/class/input/{os.path.basename(node)}/device/name", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def list_input_devices() -> list[tuple[str, str]]:
    """(node, name) for every input node that currently has a name."""
    return [(node, _device_name(node)) for node in sorted(glob.glob("/dev/input/event*"))]


class IdleTracker:
    """Newest user-input time across every readable input node except the grabbed bottom touchscreen.

    Ratatoskr grabs the bottom touchscreen exclusively, so nothing else can read it; the app
    calls poke() for those touches instead. The device list is rescanned every few seconds,
    because controllers appear after this service starts (InputPlumber's virtual pads, Bluetooth
    and USB pads) and others disappear.
    """

    def __init__(self, logger, skip_names: tuple[str, ...] = ("bottom_touchscreen",), scan_interval: float = 5.0,
                 lister: Callable[[], list[tuple[str, str]]] = list_input_devices,
                 opener: Callable[[str], int] | None = None) -> None:
        self._logger = logger
        self._skip = skip_names
        self._scan_interval = scan_interval
        self._lister = lister
        self._opener = opener or (lambda node: os.open(node, os.O_RDONLY | os.O_NONBLOCK))
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fds: dict[int, tuple[str, str]] = {}
        self._announced: tuple[str, ...] = ()
        self.devices: list[str] = []

    def poke(self) -> None:
        self._last = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self._last

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="idle-tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _wanted(self, name: str) -> bool:
        return bool(name) and name not in self._skip and not any(tag in name for tag in _IGNORED_NAMES)

    def _scan(self) -> None:
        """Open nodes that appeared; forget nodes that went away."""
        try:
            present = self._lister()
        except Exception as err:  # a bad listing must not kill the tracker
            self._logger.log(DebugCode.DIM_MIRROR, f"idle tracker could not list input devices: {err}")
            return
        present_nodes = {node for node, name in present if self._wanted(name)}
        for fd, (node, _name) in list(self._fds.items()):
            if node not in present_nodes:
                self._drop(fd)
        have = {node for node, _name in self._fds.values()}
        for node, name in present:
            if node in have or not self._wanted(name):
                continue
            try:
                fd = self._opener(node)
            except OSError:
                continue
            self._fds[fd] = (node, name)
        self.devices = sorted(f"{name} ({node})" for node, name in self._fds.values())
        key = tuple(self.devices)
        if key != self._announced:
            self._announced = key
            self._logger.log(DebugCode.DIM_MIRROR, f"idle tracker watching {len(key)} input devices: {self.devices}")

    def _drop(self, fd: int) -> None:
        self._fds.pop(fd, None)
        try:
            os.close(fd)
        except OSError:
            pass

    def _run(self) -> None:
        next_scan = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_scan:
                    self._scan()
                    next_scan = now + self._scan_interval
                if not self._fds:
                    self._stop.wait(min(1.0, self._scan_interval))
                    continue
                try:
                    ready, _, _ = select.select(list(self._fds), [], [], min(1.0, self._scan_interval))
                except (OSError, ValueError):
                    for fd in list(self._fds):  # a stale descriptor: drop them all, the next scan reopens
                        self._drop(fd)
                    continue
                for fd in ready:
                    name = self._fds[fd][1]
                    try:
                        data = os.read(fd, _EVENT.size * 64)
                    except BlockingIOError:
                        continue
                    except OSError:
                        self._drop(fd)
                        continue
                    for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                        _, _, ev_type, code, value = _EVENT.unpack_from(data, off)
                        if _is_activity(ev_type, code, value, name):
                            self._last = time.monotonic()
                            break
        finally:
            for fd in list(self._fds):
                self._drop(fd)


class DimMirror:
    """Dims the bottom panel while the top panel's idle dim is on and restores it when it ends or the bottom is touched.

    The dimmed level is also written to Armada's saved level, otherwise armada-control puts the old
    level straight back. The pre-dim level is kept in a recovery file until it has been restored.
    """

    def __init__(self, stats, tracker: IdleTracker, logger, get_config: Callable[[], dict],
                 state_file: str = RECOVERY_FILE, saved_path: str = ARMADA_SAVED) -> None:
        self._stats = stats
        self._tracker = tracker
        self._logger = logger
        self._get_config = get_config
        self._state_file = state_file
        self._saved_path = saved_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._saved: int | None = None  # bottom brightness percent before the dim, None while not dimmed
        self._top_prev: int | None = None
        self._retry_after = 0.0
        self._restore_fail_logged = 0.0
        self._recover_pending = False
        self._next_recover = 0.0

    @property
    def dimmed(self) -> bool:
        return self._saved is not None

    def start(self) -> None:
        self._recover_pending = not self.recover()
        self._thread = threading.Thread(target=self._run, name="dim-mirror", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.restore("stopping")

    # -- recovery record -------------------------------------------------------------------------------
    def _write_record(self, pct: int) -> None:
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            tmp = self._state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pct": pct, "ts": time.time()}, f)
            os.replace(tmp, self._state_file)
        except OSError as err:
            self._logger.log(DebugCode.ERR_BACKLIGHT_SYSFS, f"could not write the dim recovery record: {err}")

    def _clear_record(self) -> None:
        try:
            os.remove(self._state_file)
        except FileNotFoundError:
            pass
        except OSError as err:
            self._logger.log(DebugCode.ERR_BACKLIGHT_SYSFS, f"could not remove the dim recovery record: {err}")

    def recover(self) -> bool:
        """A dim left over from a crash, kill or reboot: put the recorded level back.

        Returns True when there is nothing left to do (no record, or it is restored) and False when the write
        failed, so the caller retries. Does nothing while this instance is itself dimmed: the record is then its own.
        """
        if self._saved is not None:
            return True
        try:
            with open(self._state_file, encoding="utf-8") as f:
                pct = int(json.load(f)["pct"])
        except FileNotFoundError:
            return True
        except (OSError, ValueError, KeyError, TypeError):
            self._clear_record()  # unreadable or corrupt: it cannot be used
            return True
        if not 1 <= pct <= 100:
            self._clear_record()
            return True
        if read_saved_bottom_level(self._saved_path) == pct:
            self._clear_record()  # the saved level is already the recorded one: nothing was left dimmed
            return True
        self._stats.set_bottom_brightness(pct, persist=True, minimum=1)
        if not self._stats.last_write_ok:
            now = time.monotonic()
            if now - self._restore_fail_logged > 30:
                self._restore_fail_logged = now
                self._logger.log(DebugCode.ERR_BACKLIGHT_SYSFS, f"could not recover the bottom level {pct}% after an earlier dim ({getattr(self._stats, 'last_error', '')}); will retry")
            return False
        self._logger.log(DebugCode.DIM_MIRROR, f"recovered the bottom level {pct}% left by an earlier dim")
        self._clear_record()
        return True

    # -- dim and restore -------------------------------------------------------------------------------
    def restore(self, why: str) -> bool:
        """Put the pre-dim level back (backlight and Armada's saved level). Keeps the state if the write failed."""
        if self._saved is None:
            return True
        pct = self._saved
        self._stats.set_bottom_brightness(pct, persist=True, minimum=1)
        if not self._stats.last_write_ok:
            now = time.monotonic()
            if now - self._restore_fail_logged > 30:
                self._restore_fail_logged = now
                self._logger.log(DebugCode.ERR_BACKLIGHT_SYSFS, f"could not restore the bottom level {pct}% ({why}; {getattr(self._stats, 'last_error', '')}); will retry")
            return False
        self._saved = None
        self._clear_record()
        self._logger.log(DebugCode.DIM_MIRROR, f"bottom restored to {pct}% ({why})")
        return True

    def _dim(self, why: str, floor_pct: int) -> None:
        saved = read_saved_bottom_level(self._saved_path)
        current = saved if saved is not None else self._stats.get_stats().get("bot_bright_pct", 100)
        target = max(1, min(current, floor_pct))
        if target >= current:
            return  # already at or below the floor
        self._write_record(current)
        self._saved = current
        steps = 6
        for step in range(1, steps + 1):  # short fade so the change is not a hard cut
            last = step == steps
            # Only the last step changes Armada's saved level; the fade is shorter than its 2 s restore interval.
            self._stats.set_bottom_brightness(
                round(current + (target - current) * step / steps), persist=last, minimum=1
            )
            if not self._stats.last_write_ok:
                self._saved = None
                self._clear_record()
                self._retry_after = time.monotonic() + 60
                self._stats.set_bottom_brightness(current, persist=True, minimum=1)
                self._logger.log(
                    DebugCode.ERR_BACKLIGHT_SYSFS,
                    "bottom backlight is not writable (needs `sudo -n tee` on it and on Armada's saved level; see systemd/touch-master-backlight.sudoers)",
                )
                return
            if not last:
                time.sleep(0.15)
        self._logger.log(
            DebugCode.DIM_MIRROR,
            f"bottom dimmed {current}% -> {target}% ({why})",
        )

    def _read_top_level(self) -> float | None:
        """Top backlight as a fraction of its maximum, or None when it cannot be read."""
        try:
            with open(f"{TOP_BACKLIGHT}/brightness", encoding="utf-8") as f:
                top = int(f.read().strip())
            with open(f"{TOP_BACKLIGHT}/max_brightness", encoding="utf-8") as f:
                top_max = int(f.read().strip())
        except (OSError, ValueError):
            return None
        return top / top_max if top_max > 0 else None

    def _run(self) -> None:
        follower = TopFollower()
        started = time.monotonic()
        while not self._stop.wait(0.25):
            if self._recover_pending and time.monotonic() >= self._next_recover:
                self._recover_pending = not self.recover()
                self._next_recover = time.monotonic() + 5.0
            cfg = self._get_config()
            if not cfg.get("mirror_dim", False):
                self.restore("mirror off")
                follower.reset()
                continue
            level = self._read_top_level()
            if level is None:
                continue
            now = time.monotonic()
            action = follower.update(_boot_now(), level)
            if action == "dim" and input_says_slider(self._tracker.idle_seconds(), now - started):
                follower.reject()  # the user is dragging the brightness slider, not Steam's idle ramp (needs a minute of quiet)
            elif action == "dim" and now >= self._retry_after:
                self._dim(f"top backlight falling, now {level * 100:.0f}% of its maximum",
                          int(cfg.get("mirror_dim_floor_percent", 3)))
                if not self.dimmed:
                    follower.reset()  # the write failed; wait for the next ramp
            elif action == "restore":
                self.restore(f"top backlight {'rose' if level > 0.5 else 'stopped falling'}, now {level * 100:.0f}%")
            elif self.dimmed and self._tracker.idle_seconds() < 1.0:
                self.restore("input")
                follower.suppress()
