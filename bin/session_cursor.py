"""Game Mode's pointer auto-hide: read and set the HIDE_CURSOR_DELAY_MS override.

gamescope hides the pointer after --hide-cursor-delay ms without pointer motion (3000 on the Thor). On the Thor,
/usr/share/gamescope-session-plus/gamescope-session-plus sources /etc/environment.d/*.conf and
~/.config/environment.d/*.conf, then applies `HIDE_CURSOR_DELAY_MS:=3000` as a default and passes the result to
gamescope as --hide-cursor-delay (read on the device 2026-10-08, lines 134-139, 175 and 302). The delay is a launch
argument and gamescope has no setter for it at run time, so a change applies the next time Game Mode starts.
"""
from __future__ import annotations

import os
import time

CONF_PATH = os.path.expanduser("~/.config/environment.d/50-ratatoskr-cursor.conf")
KEY = "HIDE_CURSOR_DELAY_MS"
STAY_VISIBLE_MS = 3_600_000  # one hour: effectively never
_HEADER = (
    "# Written by Ratatoskr's \"Keep the pointer visible\" switch in its Decky panel.\n"
    "# Delete this file (or turn the switch off) to go back to Game Mode's default of 3000 ms.\n"
)

_cache: dict[str, tuple[float, int | None]] = {}


def is_configured(path: str = CONF_PATH) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            return f"{KEY}={STAY_VISIBLE_MS}" in f.read()
    except OSError:
        return False


def set_stay_visible(on: bool, path: str = CONF_PATH) -> bool:
    """Write (on) or remove (off) the override file. Returns False if the file system refused."""
    try:
        if on:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(f"{_HEADER}{KEY}={STAY_VISIBLE_MS}\n")
            os.replace(tmp, path)
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        _cache.clear()
        return True
    except OSError:
        return False


def running_delay_ms(proc_root: str = "/proc", ttl: float = 10.0) -> int | None:
    """The --hide-cursor-delay of the gamescope that is running now, or None if none carries one.
    Cached for ttl seconds: scanning /proc costs a few milliseconds."""
    now = time.monotonic()
    hit = _cache.get(proc_root)
    if hit and now - hit[0] < ttl:
        return hit[1]
    found: int | None = None
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        try:
            with open(f"{proc_root}/{pid}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        for i, arg in enumerate(args):
            value = None
            if arg == b"--hide-cursor-delay" and i + 1 < len(args):
                value = args[i + 1]
            elif arg.startswith(b"--hide-cursor-delay="):
                value = arg.split(b"=", 1)[1]
            if value is not None:
                try:
                    found = int(value)
                except ValueError:
                    pass
                break
        if found is not None:
            break
    _cache[proc_root] = (now, found)
    return found


def status(path: str = CONF_PATH, proc_root: str = "/proc", ttl: float = 10.0) -> dict:
    ms = running_delay_ms(proc_root, ttl)
    return {
        "cursor_stay_visible": is_configured(path),
        "cursor_hide_delay_ms": ms,
        "cursor_stay_visible_active": ms is not None and ms >= STAY_VISIBLE_MS,
    }
