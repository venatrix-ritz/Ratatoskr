"""Tests for the tray menu commands (run: python tests/test_tray_actions.py)."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import tray_actions as ta  # noqa: E402


def test_stop_runs_the_managers_stop_in_its_own_unit():
    cmd = ta.stop_command("/x/touch_master_manager.py", "/usr/bin/python3")
    assert cmd[:3] == ["systemd-run", "--user", "--collect"], cmd      # outside the service's cgroup
    assert cmd[-3:] == ["/usr/bin/python3", "/x/touch_master_manager.py", "--stop"], cmd


def test_the_managers_stop_hands_the_screen_back_to_the_stock_session():
    src = open(os.path.join(ROOT, "bin", "touch_master_manager.py"), encoding="utf-8").read()
    stop = src[src.index("def stop_service"):src.index("def toggle_service")]
    for needle in ('"stop", SERVICE_NAME', '"disable", SERVICE_NAME', '"enable", STOCK_BOTTOM_SERVICE', '"start", STOCK_BOTTOM_SERVICE'):
        assert needle in stop, needle


def test_the_tray_uses_that_command_and_no_longer_edits_the_config_or_systemctl_itself():
    src = open(os.path.join(ROOT, "bin", "thor_app.py"), encoding="utf-8").read()
    body = src[src.index("def _stop_via_indicator"):src.index("def _start_key_repeat")]
    assert "tray_actions.stop_command(" in body
    assert "systemctl" not in body and "CONFIG_PATH" not in body, body


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
