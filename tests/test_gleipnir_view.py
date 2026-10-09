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
    check("on battery without battery data", gv.summary(st())[0] == "BAT 78% · -0.6A", gv.summary(st()))
    t = gv.summary(st(current_ua=2400000, usb_online=1, capacity=74))[0]
    check("charging toward the cap", t == "CHG 74% to 80% +2.4A", t)
    held = gv.summary(st(limit=0, capacity=80, usb_online=1, current_ua=0))
    check("held at the cap shows the temperature", held[0] == "HELD 80% · 30°C" and held[1] == gv.CYAN, held)
    check("daemon stopped", gv.summary(st(service_active=False))[0] == "BAT 78% · Gleipnir off")
    check("not verified", gv.summary(st(verified=False))[0] == "BAT 78% · Gleipnir unverified")
    check("no status keeps the plain battery text", gv.summary(None) is None)
    t = gv.summary(st(current_ua=2400000, usb_online=1, capacity=74, target=85))[0]
    check("a target in the output is used", "to 85%" in t, t)


def test_detail_line():
    d = gv.detail(st())
    check("detail states the rules", d == "Gleipnir stops charging at 80% and resumes at 77% · asleep: holds the cap", d)
    check("sleep off is said", gv.detail(st(sleep_floor=101)).endswith("asleep: off"))
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


# sysfs as read on the Thor, 2026-10-09 15:3x, on battery
BATT = {"charge_now": "4856746", "charge_full": "6241000", "charge_full_design": "5938000", "cycle_count": "3",
        "voltage_now": "3994391", "current_now": "-1706951", "temp": "300", "health": "Good", "time_to_empty_avg": "12082",
        "time_to_full_avg": "-1", "capacity": "77", "usb_online": "0", "usb_type": "[Unknown] SDP DCP CDP ACA C PD PD_DRP PD_PPS BrickID"}


def test_time_left_and_richer_ribbon():
    check("kernel time to empty", gv.time_left(st(), BATT) == "3h21 left", gv.time_left(st(), BATT))
    charging = {**BATT, "current_now": "2400000", "charge_now": "4600000"}
    t = gv.time_left(st(current_ua=2400000), charging)  # (0.8 * 6.241 - 4.6) Ah / 2.4 A = 0.164 h
    check("time to the cap while charging", t == "0h10 to 80%", t)
    check("ribbon on battery uses time left", gv.summary(st(), BATT)[0] == "BAT 78% · 3h21 left", gv.summary(st(), BATT))


def test_read_battery_from_a_fake_sysfs():
    import tempfile
    root = tempfile.mkdtemp()
    for dev, vals in (("battery", {"charge_now": "1", "capacity": "50"}), ("qcom-battmgr-usb", {"online": "1"})):
        os.makedirs(os.path.join(root, dev))
        for k, v in vals.items():
            with open(os.path.join(root, dev, k), "w") as f:
                f.write(v + "\n")
    b = gv.read_battery(root)
    check("battery and usb attributes read, missing ones left out", b == {"charge_now": "1", "capacity": "50", "usb_online": "1"}, b)


def test_read_events_from_the_journal():
    journal = "\n".join([
        "Oct 09 10:54:31 armada gleipnir[1030979]: LATE CLAMP: the limit reads 0 but this daemon holds no clamp",
        "Oct 09 11:14:32 armada gleipnir[1051633]: heartbeat: armed=1 state=released; cap=73%",
        "Oct 09 11:24:36 armada gleipnir[1072282]: CLAMP at 80%: limit 9000000 -> 0; cap=80% status=Charging",
        "Oct 09 15:18:43 armada gleipnir[1205678]: RELEASE (charger unplugged): restored 9000000; cap=79%",
    ])

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=journal, stderr="")
    ev = gv.read_events(run=run)
    check("last two clamp/release events with times", ev == [("11:24", "CLAMP at 80%"), ("15:18", "RELEASE (charger unplugged)")], ev)


def test_card_items_from_real_readings():
    items = dict((k, v) for k, v, _ in gv.card_items(st(), BATT, [("15:18", "RELEASE (charger unplugged)")]))
    check("charge in Ah", items["Charge"] == "77% · 4.86 of 6.24 Ah", items["Charge"])
    check("flow uses volts x amps, not power_now", items["Flow"] == "-1.71 A · -6.8 W", items["Flow"])
    check("time", items["Time"] == "3h21 left", items["Time"])
    check("cell", items["Cell"] == "3.99 V · 30 °C · Good", items["Cell"])
    check("wear and cycles", items["Wear"] == "105% of design · 3 cycles", items["Wear"])
    check("charger unplugged", items["Charger"] == "unplugged", items["Charger"])
    check("gleipnir state", items["Gleipnir"] == "running · verified · released", items["Gleipnir"])
    plugged = dict((k, v) for k, v, _ in gv.card_items(st(), {**BATT, "usb_online": "1", "usb_type": "C [PD] PD_PPS",
                                                               "usb_voltage_now": "8376000", "usb_input_current_limit": "3000000"}, []))
    check("charger contract", plugged["Charger"] == "PD · 8.4 V · 3.0 A max", plugged["Charger"])
    check("no events said plainly", plugged["Last"] == "none in the journal", plugged["Last"])
    ev = dict((k, v) for k, v, _ in gv.card_items(st(), BATT, [("11:24", "CLAMP at 80%"), ("15:18", "RELEASE (charger unplugged)")]))
    check("events are short", ev["Last"] == "11:24 clamp 80% · 15:18 release: charger unplugged", ev["Last"])


def test_zz_junk_values_do_not_raise():
    check("junk numbers fall back", gv.summary(st(capacity="x", current_ua=None, limit="?")) is not None)
    check("junk detail does not raise", isinstance(gv.detail(st(temp_dc="hot", sleep_floor="?")), str))
    check("junk battery does not raise", len(gv.card_items(None, {"charge_now": "x", "current_now": "?"}, [])) == 8)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    sys.exit(1 if FAILED else 0)
