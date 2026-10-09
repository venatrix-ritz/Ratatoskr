#!/usr/bin/env python3
"""Tests for bin/gleipnir_view.py (no device). Run: python tests/test_gleipnir_view.py"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import gleipnir_view as gv  # noqa: E402

FAILED = []
# What `gleipnir --status --json` printed on the Thor on 2026-10-09 (on battery, released)
REAL = {"node": "/sys/class/power_supply/battery/constant_charge_current", "kind": "Armada constant_charge_current",
        "clamp_value": 0, "node_max": 9000000, "verified": True, "verified_why": "", "kernel": "7.2.6", "capacity": 78,
        "status": "Discharging", "usb_online": 0, "current_ua": -642716, "voltage_uv": 4044022, "temp_dc": 300,
        "health": "Good", "limit": 9000000, "sleep_floor": 0, "sleep_mode": "s2idle"}


def check(name, cond, got=None):
    print(("ok " if cond else "FAIL ") + name + ("" if cond else f"  got {got!r}"))
    if not cond:
        FAILED.append(name)


def st(**over):
    return {**REAL, "service_active": True, **over}


def test_states():
    check("on battery", gv.summary(st())[0] == "BAT 78% · cap 80% -0.6A", gv.summary(st()))
    t = gv.summary(st(current_ua=2400000, usb_online=1, capacity=74))[0]
    check("charging toward the cap", t == "CHG 74% to 80% +2.4A", t)
    held = gv.summary(st(limit=0, capacity=80, usb_online=1, current_ua=0))
    check("held at the cap", held[0] == "HELD 80% · cap 80%" and held[1] == gv.CYAN, held)
    check("daemon stopped", gv.summary(st(service_active=False))[0] == "BAT 78% · Gleipnir off")
    check("not verified", gv.summary(st(verified=False))[0] == "BAT 78% · Gleipnir unverified")
    check("no status keeps the plain battery text", gv.summary(None) is None)
    check("a target in the output is used", "cap 85%" in gv.summary(st(target=85))[0])


def test_detail_line():
    d = gv.detail(st())
    check("detail names the important facts", all(w in d for w in ("running", "verified", "charging allowed", "on battery", "hold the cap")), d)
    check("held shows in detail", "HELD at 80%" in gv.detail(st(limit=0)))
    check("missing gleipnir is said plainly", "not installed" in gv.detail(None))


def test_read_status_with_a_fake_runner():
    def run(cmd, **kw):
        if cmd[-1] == "--json":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(REAL), stderr="")
        return subprocess.CompletedProcess(cmd, 0)
    s = gv.read_status("/fake/gleipnir", run=run)
    check("status parsed and service flag added", s and s["capacity"] == 78 and s["service_active"] is True, s)

    def broken(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="not json", stderr="")
    check("garbage output gives None", gv.read_status("/fake/gleipnir", run=broken) is None)

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    check("a missing script gives None", gv.read_status("/fake/gleipnir", run=missing) is None)


def test_zz_junk_values_do_not_raise():
    check("junk numbers fall back", gv.summary(st(capacity="x", current_ua=None, limit="?")) is not None)
    check("junk detail does not raise", isinstance(gv.detail(st(temp_dc="hot", sleep_floor="?")), str))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
