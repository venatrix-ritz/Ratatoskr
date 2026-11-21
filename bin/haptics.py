"""Short vibration pulses on the Thor's haptics motor for taps, keys and on-screen buttons.

Linux force feedback (kernel Documentation/input/ff.rst): upload an effect with EVIOCSFF, play it by writing an
EV_FF event whose code is the effect id, erase it with EVIOCRMFF. The Thor's motor is the evdev device
"qcom-hv-haptics" (FF_RUMBLE, FF_PERIODIC, FF_CONSTANT, FF_GAIN), group `input`, and it has one effect slot
(EVIOCGEFFECTS returned 1 on 2026-11-20). So every pulse uploads, plays and erases its effect instead of holding the
only slot. A pulse runs on its own thread so a slow driver call never holds up a touch.
"""
from __future__ import annotations

import errno
import os
import struct
import threading
import time

from debug_codes import DebugCode

try:
    import fcntl
except ImportError:  # Windows, for the unit tests
    fcntl = None

DEVICE_NAME = "qcom-hv-haptics"
EV_FF = 0x15
FF_RUMBLE = 0x50
PULSE_MS = 15
STRENGTH = 0x4000  # rumble strong magnitude, of 0xFFFF

# struct ff_effect: type, id, direction, trigger {button, interval}, replay {length, delay}, then the effect union.
# The union holds ff_periodic_effect with a pointer, so on 64-bit it is 8-byte aligned and 32 bytes (48 in all);
# ff_rumble_effect is its first 4 bytes (strong, weak magnitude).
FF_EFFECT = struct.Struct("=HhHHHHH2xHH28x")
EVENT = struct.Struct("llHHi")


def _iow(nr: int, size: int) -> int:
    return (1 << 30) | (size << 16) | (ord("E") << 8) | nr


EVIOCSFF = _iow(0x80, FF_EFFECT.size)
EVIOCRMFF = _iow(0x81, struct.calcsize("i"))


def find_device(name: str = DEVICE_NAME, devices_path: str = "/proc/bus/input/devices") -> str | None:
    """/dev/input/eventN of the input device called `name`, or None."""
    try:
        with open(devices_path, encoding="utf-8", errors="replace") as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return None
    for block in blocks:
        if f'N: Name="{name}"' not in block:
            continue
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                for handler in line.split("=", 1)[1].split():
                    if handler.startswith("event"):
                        return f"/dev/input/{handler}"
    return None


class Haptics:
    """`pulse()` asks for one short buzz; pulses asked for while one plays become one more."""

    def __init__(self, logger=None, find=find_device, open_fn=os.open, ioctl=None, write=os.write, sleep=time.sleep,
                 close=os.close) -> None:
        self.logger = logger
        self.enabled = True  # the `haptics` setting
        self.path: str | None = None
        self.fd = -1
        self.pulses = 0
        self.failures = 0
        self.last_error = ""
        self._find, self._open, self._write, self._sleep, self._close = find, open_fn, write, sleep, close
        self._ioctl = ioctl if ioctl is not None else (fcntl.ioctl if fcntl else None)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self.fd >= 0

    def start(self) -> bool:
        self.path = self._find()
        if self.path is None or self._ioctl is None:
            self._note(f"no {DEVICE_NAME} device; taps stay silent")
            return False
        try:
            self.fd = self._open(self.path, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))  # no O_CLOEXEC on Windows (tests)
        except OSError as err:
            self._note(f"cannot open {self.path}: {err}")
            return False
        self._thread = threading.Thread(target=self._run, name="haptics", daemon=True)
        self._thread.start()
        return True

    def pulse(self) -> None:
        if self.enabled and self.fd >= 0:
            self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.fd >= 0:
            try:
                self._close(self.fd)
            except OSError:
                pass
            self.fd = -1

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                break
            self.play_once()

    def play_once(self) -> bool:
        """Upload, play and erase one rumble effect. False (and counted) if the driver refused."""
        effect = bytearray(FF_EFFECT.pack(FF_RUMBLE, -1, 0, 0, 0, PULSE_MS, 0, STRENGTH, 0))
        try:
            self._ioctl(self.fd, EVIOCSFF, effect, True)  # the kernel writes the new effect id back
        except OSError as err:
            # EBUSY/ENOSPC: something else holds the one slot (a game's rumble); that pulse is skipped
            return self._failed("upload", err, quiet=err.errno in (errno.ENOSPC, errno.EBUSY))
        effect_id = struct.unpack_from("=h", effect, 2)[0]
        try:
            now = time.time()
            self._write(self.fd, EVENT.pack(int(now), int((now % 1) * 1e6), EV_FF, effect_id, 1))
            self.pulses += 1
            self._sleep((PULSE_MS + 10) / 1000.0)  # erasing a playing effect stops it
            return True
        except OSError as err:
            return self._failed("play", err)
        finally:
            try:
                self._ioctl(self.fd, EVIOCRMFF, effect_id)
            except OSError as err:
                self._failed("erase", err)

    def _failed(self, what: str, err: OSError, quiet: bool = False) -> bool:
        self.failures += 1
        self.last_error = f"{what}: {err}"
        if not quiet and self.failures <= 3:
            self._note(f"haptics {what} failed: {err}")
        return False

    def _note(self, text: str) -> None:
        if self.logger is not None:
            self.logger.log(DebugCode.HAPTICS, text)
