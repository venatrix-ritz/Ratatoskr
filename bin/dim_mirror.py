"""Mirror the top screen's idle dimming onto the bottom screen.

Steam dims only the top panel: Armada steers every Steam backlight write to the
primary panel (`steamos-priv-write`, `ARMADA_PRIMARY_BACKLIGHT`), so the bottom
panel keeps its brightness. The dim delay is a Steam setting, stored in
`~/.local/share/Steam/config/config.vdf` as `IdleBacklightDimBatterySeconds` and
`IdleBacklightDimACSeconds` (0 = never). This module reads that setting, tracks
input idle time itself, and dims/restores the bottom panel on the same schedule.

Sleep is not handled here: Armada's fake-suspend sends `drm_sleep_internal_screen` to every
gamescope instance in the session (falling back to `bl_power` on every backlight), which should
cover the bottom panel too (`/usr/libexec/armada/fake-suspend`, `display_off`; not yet confirmed by
a test on the Thor).
"""
from __future__ import annotations

import glob
import os
import re
import select
import struct
import threading
import time
from typing import Callable

from debug_codes import DebugCode

STEAM_CONFIG = os.path.expanduser("~/.local/share/Steam/config/config.vdf")
BATTERY_STATUS = "/sys/class/power_supply/battery/status"
TOP_BACKLIGHT = "/sys/class/backlight/ae96000.dsi.0"

EV_KEY, EV_REL, EV_ABS = 0x01, 0x02, 0x03
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11
ABS_MT_FIRST = 0x2F  # ABS_MT_SLOT; the multitouch axes start here

_EVENT = struct.Struct("llHHi")
_VDF_KEY = re.compile(r'"IdleBacklightDim(Battery|AC)Seconds"\s+"(\d+)"')

# Devices that are not the user: haptics, jack/lid switches, our own virtual devices.
_IGNORED_NAMES = ("haptics", "Jack", "lid", "Thor Virtual", "pmic_")
# Sticks and triggers count as activity only past this deflection (drift stays idle).
_STICK_THRESHOLD = 8000
_TRIGGER_THRESHOLD = 100


def read_dim_seconds(on_ac: bool, path: str = STEAM_CONFIG) -> int:
    """Steam's idle-dim delay for the current power source, in seconds (0 = never or unreadable)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            found = {k: int(v) for k, v in _VDF_KEY.findall(f.read())}
    except OSError:
        return 0
    return found.get("AC" if on_ac else "Battery", 0)


def on_ac_power(status_path: str = BATTERY_STATUS) -> bool:
    try:
        with open(status_path, encoding="utf-8") as f:
            return f.read().strip() in ("Charging", "Full")
    except OSError:
        return False


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


class IdleTracker:
    """Newest user-input time across every readable input node except the grabbed bottom touchscreen.

    Ratatoskr grabs the bottom touchscreen exclusively, so nothing else can read it; the app
    calls poke() for those touches instead.
    """

    def __init__(self, logger, skip_names: tuple[str, ...] = ("bottom_touchscreen",)) -> None:
        self._logger = logger
        self._skip = skip_names
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
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

    def _open_all(self) -> dict[int, tuple[str, str]]:
        fds: dict[int, tuple[str, str]] = {}
        for node in sorted(glob.glob("/dev/input/event*")):
            name = _device_name(node)
            if not name or name in self._skip or any(tag in name for tag in _IGNORED_NAMES):
                continue
            try:
                fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            fds[fd] = (node, name)
        self.devices = [f"{n} ({node})" for node, n in fds.values()]
        return fds

    def _run(self) -> None:
        fds = self._open_all()
        self._logger.log(DebugCode.DIM_MIRROR, f"idle tracker watching {len(fds)} input devices: {self.devices}")
        try:
            while not self._stop.is_set() and fds:
                ready, _, _ = select.select(list(fds), [], [], 1.0)
                for fd in ready:
                    name = fds[fd][1]
                    try:
                        data = os.read(fd, _EVENT.size * 64)
                    except BlockingIOError:
                        continue
                    except OSError:
                        fds.pop(fd, None)
                        continue
                    for off in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                        _, _, ev_type, code, value = _EVENT.unpack_from(data, off)
                        if _is_activity(ev_type, code, value, name):
                            self._last = time.monotonic()
                            break
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass


class DimMirror:
    """Dims the bottom panel after Steam's idle-dim delay and restores it on the next input."""

    def __init__(self, stats, tracker: IdleTracker, logger, get_config: Callable[[], dict]) -> None:
        self._stats = stats
        self._tracker = tracker
        self._logger = logger
        self._get_config = get_config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._saved: int | None = None  # bottom brightness percent before the dim, None while not dimmed
        self._top_prev: int | None = None
        self._retry_after = 0.0

    @property
    def dimmed(self) -> bool:
        return self._saved is not None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="dim-mirror", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.restore("stopping")

    def restore(self, why: str) -> None:
        if self._saved is None:
            return
        pct, self._saved = self._saved, None
        self._stats.set_bottom_brightness(pct, persist=False, minimum=1)
        self._logger.log(DebugCode.DIM_MIRROR, f"bottom restored to {pct}% ({why})")

    def _dim(self, delay: int, idle: float, floor_pct: int) -> None:
        current = self._stats.get_stats().get("bot_bright_pct", 100)
        target = max(1, min(current, floor_pct))
        if target >= current:
            return  # already at or below the floor
        self._saved = current
        for step in range(1, 7):  # short fade so the change is not a hard cut
            self._stats.set_bottom_brightness(
                round(current + (target - current) * step / 6), persist=False, minimum=1
            )
            if not self._stats.last_write_ok:
                self._saved = None
                self._retry_after = time.monotonic() + 60
                self._logger.log(
                    DebugCode.ERR_BACKLIGHT_SYSFS,
                    "bottom backlight is not writable (needs `sudo -n tee` on it; see systemd/touch-master-backlight.sudoers)",
                )
                return
            time.sleep(0.15)
        self._logger.log(
            DebugCode.DIM_MIRROR,
            f"bottom dimmed {current}% -> {target}% (idle {idle:.0f}s >= Steam dim delay {delay}s)",
        )

    def _watch_top(self, idle: float, delay: int) -> None:
        """Diagnostic only: log when the top backlight really drops, to compare with the timer above."""
        try:
            with open(f"{TOP_BACKLIGHT}/brightness", encoding="utf-8") as f:
                top = int(f.read().strip())
        except (OSError, ValueError):
            return
        prev, self._top_prev = self._top_prev, top
        if prev is not None and prev > 0 and top < prev * 0.7:
            self._logger.log(
                DebugCode.DIM_MIRROR,
                f"top backlight dropped {prev} -> {top} at idle {idle:.0f}s (Steam delay {delay}s)",
            )
        elif prev is not None and top > prev * 1.5 and prev > 0:
            self._logger.log(DebugCode.DIM_MIRROR, f"top backlight rose {prev} -> {top} at idle {idle:.0f}s")

    def _run(self) -> None:
        delay, last_read, was_ac = 0, 0.0, None
        while not self._stop.wait(0.25 if self.dimmed else 1.0):
            cfg = self._get_config()
            idle = self._tracker.idle_seconds()
            ac = on_ac_power()
            now = time.monotonic()
            if ac != was_ac or now - last_read > 10:
                delay, last_read, was_ac = read_dim_seconds(ac), now, ac
            self._watch_top(idle, delay)
            if not cfg.get("mirror_dim", False) or delay <= 0:
                self.restore("mirror off or Steam dim delay is 0")
                continue
            if self.dimmed:
                if idle < 1.0:
                    self.restore("input")
            elif idle >= delay and time.monotonic() >= self._retry_after:
                self._dim(delay, idle, int(cfg.get("mirror_dim_floor_percent", 3)))
