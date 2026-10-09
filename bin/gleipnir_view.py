"""Read-only view of the Gleipnir charge limiter (github.com/venatrix-ritz/Gleipnir) for the status ribbon and Quick
Controls. Pure Python, no GTK, so it is unit-tested (tests/test_gleipnir_view.py).

Gleipnir's own `gleipnir --status --json` is the source: it runs as the normal user (about 80 ms on the Thor) and reports
whether the clamp is verified on this kernel, the charge level, charger, current, temperature, the limit node and the
sleep setting. Whether the daemon runs comes from `systemctl is-active gleipnir`. Nothing here writes anything.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

SCRIPT_CANDIDATES = ("/var/local/bin/gleipnir", "/usr/local/bin/gleipnir")
# Gleipnir's TARGET and RELEASE_AT (bin/gleipnir); used when its status output does not carry them
DEFAULT_TARGET, DEFAULT_RELEASE_AT = 80, 77
CLAMP_DETECT = 1000  # a limit at or below this is Gleipnir's clamp (same rule as its is_clamped)

GREEN, CYAN, AMBER, GREY = (0.3, 0.85, 0.5), (0.40, 0.85, 1.0), (0.95, 0.65, 0.20), (0.55, 0.60, 0.70)


def find_script() -> str | None:
    for path in SCRIPT_CANDIDATES:
        if os.access(path, os.X_OK):
            return path
    return shutil.which("gleipnir")


def read_status(script: str | None = None, run=subprocess.run) -> dict | None:
    """Gleipnir's JSON status plus `service_active`, or None when Gleipnir is not installed or does not answer."""
    script = script or find_script()
    if not script:
        return None
    try:
        res = run([script, "--status", "--json"], capture_output=True, text=True, timeout=3.0, check=False)
        status = json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(status, dict):
        return None
    try:
        active = run(["systemctl", "is-active", "--quiet", "gleipnir"], timeout=2.0, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        active = False
    status["service_active"] = active
    return status


def _num(status: dict, key: str, default: int = 0) -> int:
    try:
        return int(status.get(key, default))
    except (TypeError, ValueError):
        return default


def summary(status: dict | None) -> tuple[str, tuple[float, float, float]] | None:
    """Text and colour for the ribbon's battery cell, or None to keep the plain battery text."""
    if not status:
        return None
    cap = _num(status, "capacity")
    target = _num(status, "target", DEFAULT_TARGET)
    amps = _num(status, "current_ua") / 1e6
    if not status.get("service_active"):
        return f"BAT {cap}% · Gleipnir off", AMBER
    if not status.get("verified"):
        return f"BAT {cap}% · Gleipnir unverified", AMBER
    if _num(status, "limit", 1 << 30) <= CLAMP_DETECT:
        return f"HELD {cap}% · cap {target}%", CYAN
    if amps > 0.05:
        return f"CHG {cap}% to {target}% +{amps:.1f}A", GREEN  # no arrow: the Thor's fonts lack it
    return f"BAT {cap}% · cap {target}% {amps:.1f}A", GREEN


def detail(status: dict | None) -> str:
    """One line for Quick Controls."""
    if not status:
        return "Gleipnir: not installed or not answering"
    target = _num(status, "target", DEFAULT_TARGET)
    release = _num(status, "release_at", DEFAULT_RELEASE_AT)
    held = _num(status, "limit", 1 << 30) <= CLAMP_DETECT
    floor = _num(status, "sleep_floor")
    sleep = "hold the cap" if floor <= 0 else "off" if floor > 100 else f"hold from {floor}%"
    parts = [
        "running" if status.get("service_active") else "NOT running",
        "verified" if status.get("verified") else "NOT verified",
        f"HELD at {target}%" if held else f"charging allowed (holds at {target}%, resumes at {release}%)",
        f"{_num(status, 'current_ua') / 1e6:+.2f} A",
        f"{_num(status, 'temp_dc') / 10:.0f} °C",
        "charger in" if _num(status, "usb_online") else "on battery",
        f"asleep: {sleep}",
    ]
    return "Gleipnir: " + " · ".join(parts)
