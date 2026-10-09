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


PS_ROOT = "/sys/class/power_supply"
EVENT_PATTERNS = ("PRE-SLEEP CLAMP at", "CLAMP at", "RELEASE (", "LATE CLAMP")


def read_battery(root: str = PS_ROOT) -> dict:
    """The battery and charger attributes the card uses, as raw strings (missing ones are left out)."""
    out: dict = {}
    for dev, names in (("battery", ("charge_now", "charge_full", "charge_full_design", "cycle_count", "voltage_now",
                                    "current_now", "temp", "health", "time_to_empty_avg", "time_to_full_avg", "capacity")),
                       ("qcom-battmgr-usb", ("online", "usb_type", "voltage_now", "input_current_limit"))):
        for name in names:
            try:
                with open(f"{root}/{dev}/{name}", encoding="utf-8") as f:
                    out[f"{'usb_' if dev != 'battery' else ''}{name}"] = f.read().strip()
            except OSError:
                pass
    return out


def read_events(run=subprocess.run, lines: int = 400) -> list[tuple[str, str]]:
    """The last clamp / release decisions from Gleipnir's journal: [(HH:MM, what)], newest last."""
    try:
        res = run(["journalctl", "-t", "gleipnir", "-n", str(lines), "--no-pager", "-o", "short"],
                  capture_output=True, text=True, timeout=3.0, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    events = []
    for line in res.stdout.splitlines():
        msg = line.split(": ", 1)[1] if ": " in line else ""
        if not msg.startswith(EVENT_PATTERNS):
            continue
        when = line[7:12] if len(line) > 12 else "?"  # "Oct 09 11:24:36 host tag[pid]: ..." -> "11:24"
        what = msg.split(";", 1)[0].split(":", 1)[0]
        if what.startswith("RELEASE"):
            what = msg.split(":", 1)[0]  # keep the reason: "RELEASE (charger unplugged)"
        events.append((when, what))
    return events[-2:]


def _f(batt: dict, key: str) -> float | None:
    try:
        return float(batt[key])
    except (KeyError, TypeError, ValueError):
        return None


def _hm(hours: float) -> str:
    total = max(0, int(round(hours * 60)))
    return f"{total // 60}h{total % 60:02d}"


def time_left(status: dict | None, batt: dict) -> str | None:
    """'3h21 left' on battery, '0h40 to 80%' while charging toward the cap, None when unknown."""
    cur = _f(batt, "current_now")
    if cur is None:
        return None
    if cur < -50_000:
        tte = _f(batt, "time_to_empty_avg")
        if tte and tte > 0:
            return f"{_hm(tte / 3600)} left"
        now = _f(batt, "charge_now")
        return f"{_hm(now / -cur)} left" if now else None
    if cur > 50_000 and status:
        target = _num(status, "target", DEFAULT_TARGET)
        now, full = _f(batt, "charge_now"), _f(batt, "charge_full")
        if now is not None and full:
            need = full * target / 100 - now
            return f"{_hm(need / cur)} to {target}%" if need > 0 else None
    return None


def summary(status: dict | None, batt: dict | None = None) -> tuple[str, tuple[float, float, float]] | None:
    """Text and colour for the ribbon's battery cell, or None to keep the plain battery text."""
    if not status:
        return None
    batt = batt or {}
    left = time_left(status, batt)
    cap = _num(status, "capacity")
    target = _num(status, "target", DEFAULT_TARGET)
    amps = _num(status, "current_ua") / 1e6
    if not status.get("service_active"):
        return f"BAT {cap}% · Gleipnir off", AMBER
    if not status.get("verified"):
        return f"BAT {cap}% · Gleipnir unverified", AMBER
    if _num(status, "limit", 1 << 30) <= CLAMP_DETECT:
        return f"HELD {cap}% · {_num(status, 'temp_dc') / 10:.0f}°C", CYAN
    if amps > 0.05:  # no arrow: the Thor's fonts lack it
        return (f"CHG {cap}% · {left}" if left else f"CHG {cap}% to {target}% +{amps:.1f}A"), GREEN
    return (f"BAT {cap}% · {left}" if left else f"BAT {cap}% · {amps:.1f}A"), GREEN


def detail(status: dict | None) -> str:
    """One line for Quick Controls under the buttons: Gleipnir's rules (the card above shows its state)."""
    if not status:
        return "Gleipnir: not installed or not answering"
    target = _num(status, "target", DEFAULT_TARGET)
    release = _num(status, "release_at", DEFAULT_RELEASE_AT)
    floor = _num(status, "sleep_floor")
    sleep = "holds the cap" if floor <= 0 else "off" if floor > 100 else f"holds from {floor}%"
    return f"Gleipnir stops charging at {target}% and resumes at {release}% · asleep: {sleep}"


def _short(what: str) -> str:
    """'CLAMP at 80%' -> 'clamp 80%', 'RELEASE (charger unplugged)' -> 'release: charger unplugged'."""
    w = what.replace("PRE-SLEEP CLAMP at ", "sleep clamp ").replace("LATE CLAMP", "late clamp").replace("CLAMP at ", "clamp ")
    if w.startswith("RELEASE (") and w.endswith(")"):
        w = "release: " + w[len("RELEASE ("):-1]
    return w


def card_items(status: dict | None, batt: dict, events: list[tuple[str, str]]) -> list[tuple[str, str, tuple]]:
    """Eight (label, value, colour) rows for the Quick Controls Battery & Gleipnir card."""
    white, dim = (0.88, 0.90, 0.96), GREY
    cap = batt.get("capacity", "?")
    now, full, design = _f(batt, "charge_now"), _f(batt, "charge_full"), _f(batt, "charge_full_design")
    volt, cur, temp = _f(batt, "voltage_now"), _f(batt, "current_now"), _f(batt, "temp")
    charge = f"{cap}%" + (f" · {now / 1e6:.2f} of {full / 1e6:.2f} Ah" if now and full else "")
    # power_now on this kernel disagrees with volts x amps (docs/hardware/device-observed.md), so compute it
    flow = (f"{cur / 1e6:+.2f} A · {volt * cur / 1e12:+.1f} W" if volt and cur is not None else "?")
    left = time_left(status, batt) or ("held at the cap" if status and _num(status, "limit", 1 << 30) <= CLAMP_DETECT else "-")
    cell = " · ".join(x for x in (f"{volt / 1e6:.2f} V" if volt else "", f"{temp / 10:.0f} °C" if temp is not None else "",
                                  batt.get("health", "")) if x)
    wear = (f"{full / design * 100:.0f}% of design" if full and design else "?") + (f" · {batt['cycle_count']} cycles" if batt.get("cycle_count") else "")
    if batt.get("usb_online") == "1":
        kind = next((t.strip("[]") for t in batt.get("usb_type", "").split() if t.startswith("[")), "?")
        uv, lim = _f(batt, "usb_voltage_now"), _f(batt, "usb_input_current_limit")
        charger = " · ".join(x for x in (kind, f"{uv / 1e6:.1f} V" if uv and uv > 0 else "", f"{lim / 1e6:.1f} A max" if lim else "") if x)
    else:
        charger = "unplugged"
    if not status:
        gl, gl_col = "not installed or not answering", AMBER
    else:
        held = _num(status, "limit", 1 << 30) <= CLAMP_DETECT
        gl = " · ".join(("running" if status.get("service_active") else "NOT running",
                         "verified" if status.get("verified") else "NOT verified",
                         "holding" if held else "released"))
        gl_col = CYAN if held else GREEN if status.get("service_active") and status.get("verified") else AMBER
    last = " · ".join(f"{when} {_short(what)}" for when, what in events) or "none in the journal"
    return [("Charge", charge, white), ("Flow", flow, white), ("Time", left, white), ("Cell", cell, white),
            ("Wear", wear, white), ("Charger", charger, white), ("Gleipnir", gl, gl_col), ("Last", last, dim)]
