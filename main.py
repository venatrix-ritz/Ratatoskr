"""Ratatoskr Decky Plugin Backend with diagnostic logging, telemetry & quick controls."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

# Ensure plugin directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from debug_codes import DebugCode, DebugLogger, run_self_diagnostics

SOCKET_PATH = "/run/user/1000/thor-input.sock"
CONFIG_PATH = Path("/var/home/armada/.config/thor-input/config.json")
APP_PATH = "/var/home/armada/.local/share/thor-input/bin/thor_app.py"


def _send_ipc(request: dict) -> dict:
    if not os.path.exists(SOCKET_PATH):
        return {"ok": False, "code": int(DebugCode.ERR_SOCKET_CONNECT), "error": "socket not found"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(SOCKET_PATH)
            s.sendall(json.dumps(request).encode("utf-8"))
            data = s.recv(4096)
            if not data:
                return {"ok": False, "code": int(DebugCode.ERR_SOCKET_PROTOCOL), "error": "empty response"}
            return json.loads(data.decode("utf-8"))
    except Exception as err:
        return {"ok": False, "code": int(DebugCode.ERR_SOCKET_TIMEOUT), "error": str(err)}


def _is_running() -> bool:
    res = _send_ipc({"action": "get_status"})
    return bool(res.get("ok"))


def _default_config() -> dict:
    return {
        "mode": "trackpad",
        "sensitivity": 1.5,
        "glide": True,
        "friction": 5,
        "scroll_speed": 3,
        "tap_to_click": True,
        "long_press_right_click": False,
        "long_press_delay_ms": 450,
        "two_finger_right_click": True,
        "three_finger_middle_click": False,
        "pinch_zoom_enabled": False,
        "three_finger_swipe_enabled": False,
        "drag_lock_enabled": False,
        "mirror_dim": False,
        "mirror_dim_floor_percent": 3,
        "debug_hud": False,
    }



def _read_config() -> dict:
    cfg = _default_config()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def _save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


class Plugin:
    def __init__(self) -> None:
        self.logger = DebugLogger("plugin")

    async def _main(self) -> None:
        """Called automatically by Decky Loader on startup."""
        self.logger.log(DebugCode.DAEMON_STARTING, "Decky initialized Ratatoskr plugin")
        cfg = _read_config()
        if cfg.get("enabled", True):
            if not _is_running():
                self._start_service()
        else:
            if _is_running():
                self._stop_service()

    def _run_systemctl(self, action: str, unit: str = "touch-master.service") -> bool:
        env = dict(os.environ)
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

        cmds = [
            ["systemctl", "--machine=armada@.host", "--user", action, unit],
            ["systemctl", "--user", action, unit],
        ]
        success = False
        for cmd in cmds:
            try:
                res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=5.0)
                if res.returncode == 0:
                    success = True
                    break
            except Exception:
                pass
        if not success:
            self.logger.log(
                DebugCode.ERR_SERVICE_STOP if "stop" in action else DebugCode.ERR_SERVICE_START,
                f"systemctl {action} {unit} failed",
            )
        return success

    def _start_service(self) -> None:
        self._run_systemctl("disable", "armada-bottom-screen.service")
        self._run_systemctl("enable", "touch-master.service")
        self._run_systemctl("start", "touch-master.service")

    def _stop_service(self) -> None:
        self._run_systemctl("stop", "touch-master.service")
        self._run_systemctl("disable", "touch-master.service")
        self._run_systemctl("enable", "armada-bottom-screen.service")
        self._run_systemctl("start", "armada-bottom-screen.service")

    async def get_status(self) -> dict:
        def _get():
            running = _is_running()
            cfg = _read_config()
            if running:
                res = _send_ipc({"action": "get_status"})
                debug_info = _send_ipc({"action": "get_debug"})
                cfg.update(res)
                return {
                    "enabled": True,
                    "code": int(DebugCode.OK),
                    "mode": cfg.get("mode", "trackpad"),
                    "sensitivity": cfg.get("sensitivity", 1.5),
                    "glide": cfg.get("glide", True),
                    "friction": cfg.get("friction", 5),
                    "scroll_speed": cfg.get("scroll_speed", 3),
                    "tap_to_click": cfg.get("tap_to_click", True),
                    "long_press_right_click": cfg.get("long_press_right_click", False),
                    "long_press_delay_ms": cfg.get("long_press_delay_ms", 450),
                    "two_finger_right_click": cfg.get("two_finger_right_click", True),
                    "three_finger_middle_click": cfg.get("three_finger_middle_click", False),
                    "pinch_zoom_enabled": cfg.get("pinch_zoom_enabled", False),
                    "three_finger_swipe_enabled": cfg.get("three_finger_swipe_enabled", False),
                    "drag_lock_enabled": cfg.get("drag_lock_enabled", False),
                    "mirror_dim": cfg.get("mirror_dim", False),
                    "mirror_dim_floor_percent": cfg.get("mirror_dim_floor_percent", 3),
                    "bottom_dimmed": res.get("bottom_dimmed", False),
                    "cursor_stay_visible": res.get("cursor_stay_visible", False),
                    "cursor_stay_visible_active": res.get("cursor_stay_visible_active", False),
                    "debug_hud": cfg.get("debug_hud", False),
                    "telemetry": debug_info.get("telemetry", {}),
                    "touch_device": debug_info.get("touch_device", ""),
                    "state": debug_info.get("state", "IDLE"),
                    "hardware_stats": res.get("hardware_stats", {}),
                }
            return {
                "enabled": False,
                "code": int(DebugCode.DAEMON_STOPPED),
                **cfg,
                "telemetry": {},
                "touch_device": "",
                "state": "STOPPED",
                "hardware_stats": {},
            }

        return await asyncio.to_thread(_get)

    async def set_enabled(self, enabled: bool) -> dict:
        def _set():
            cfg = _read_config()
            cfg["enabled"] = enabled
            _save_config(cfg)

            running = _is_running()
            if enabled:
                self.logger.log(DebugCode.DAEMON_STARTING, "Starting touch-master.service via systemd")
                self._start_service()
            else:
                self.logger.log(DebugCode.DAEMON_STOPPING, "Stopping touch-master.service via systemd")
                self._stop_service()
            return {"ok": True, "enabled": enabled}

        await asyncio.to_thread(_set)

        # Polling loop up to 3.0s waiting for socket state to synchronize
        for _ in range(30):
            await asyncio.sleep(0.1)
            running = await asyncio.to_thread(_is_running)
            if running == enabled:
                break

        return await self.get_status()


    async def set_mode(self, mode: str) -> dict:
        def _set():
            cfg = _read_config()
            cfg["mode"] = mode
            _save_config(cfg)
            if _is_running():
                _send_ipc({"action": "set_mode", "mode": mode})
            return {"ok": True, "mode": mode}

        return await asyncio.to_thread(_set)

    async def set_settings(self, settings: dict | None = None, **kwargs) -> dict:
        def _set():
            cfg = _read_config()
            merged = {}
            if settings and isinstance(settings, dict):
                merged.update(settings)
            merged.update(kwargs)
            cfg.update(merged)
            _save_config(cfg)
            self.logger.log(DebugCode.SETTINGS_UPDATED, f"updated={list(merged.keys())}")
            if _is_running():
                payload = {"action": "set_settings"}
                payload.update(merged)
                _send_ipc(payload)
            return {"ok": True, "settings": cfg}

        return await asyncio.to_thread(_set)

    async def set_volume(self, volume: int) -> dict:
        def _set():
            if _is_running():
                return _send_ipc({"action": "set_volume", "volume": int(volume)})
            return {"ok": False}

        return await asyncio.to_thread(_set)

    async def toggle_mute(self) -> dict:
        def _set():
            if _is_running():
                return _send_ipc({"action": "toggle_mute"})
            return {"ok": False}

        return await asyncio.to_thread(_set)

    async def set_brightness(self, target: str, percent: int) -> dict:
        def _set():
            if _is_running():
                action = "set_top_brightness" if target == "top" else "set_bottom_brightness"
                return _send_ipc({"action": action, "brightness": int(percent)})
            return {"ok": False}

        return await asyncio.to_thread(_set)

    async def toggle_hud(self) -> dict:
        def _toggle():
            if _is_running():
                return _send_ipc({"action": "toggle_hud"})
            cfg = _read_config()
            cfg["debug_hud"] = not cfg.get("debug_hud", False)
            _save_config(cfg)
            return {"ok": True, "debug_hud": cfg["debug_hud"]}

        return await asyncio.to_thread(_toggle)

    async def set_cursor_override(self, enabled: bool) -> dict:
        """Keep Game Mode's pointer visible (or restore the 3 s auto-hide). Takes effect when Game Mode next starts."""
        def _set():
            if _is_running():
                return _send_ipc({"action": "set_cursor_override", "enabled": bool(enabled)})
            return {"ok": False}

        return await asyncio.to_thread(_set)

    async def run_diagnostics(self) -> dict:
        return await asyncio.to_thread(run_self_diagnostics)
