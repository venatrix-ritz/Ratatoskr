"""Ratatoskr Decky Plugin Backend with diagnostic logging, telemetry & quick controls."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure plugin directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from debug_codes import DebugCode, DebugLogger, run_self_diagnostics

PLUGIN_DIR = Path(__file__).resolve().parent
# The user whose session the driver runs in. RATATOSKR_HOME exists so tests can point the installer at a temp directory.
HOME = Path(os.environ.get("RATATOSKR_HOME", "/var/home/armada"))
SOCKET_PATH = "/run/user/1000/thor-input.sock"
CONFIG_PATH = HOME / ".config/thor-input/config.json"
APP_DIR = HOME / ".local/share/thor-input"
APP_PATH = str(APP_DIR / "bin/thor_app.py")

# Release zip only (the Armada Store unpacks the plugin folder and nothing else): driver files shipped inside the plugin
# under driver/. With deploy.sh there is no driver/ folder and the installer does nothing.
DRIVER_SRC = PLUGIN_DIR / "driver"


def _send_ipc(request: dict) -> dict:
    if not os.path.exists(SOCKET_PATH):
        return {"ok": False, "code": int(DebugCode.ERR_SOCKET_CONNECT), "error": "socket not found"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(SOCKET_PATH)
            s.sendall(json.dumps(request).encode("utf-8"))
            chunks, total = [], 0
            while True:  # the driver closes the connection after replying, and a status reply is several KB
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > 1024 * 1024:
                    raise ValueError("reply too large")
            data = b"".join(chunks)
            if not data:
                return {"ok": False, "code": int(DebugCode.ERR_SOCKET_PROTOCOL), "error": "empty response"}
            return json.loads(data.decode("utf-8"))
    except Exception as err:
        return {"ok": False, "code": int(DebugCode.ERR_SOCKET_TIMEOUT), "error": str(err)}


def _driver_files() -> list[tuple[Path, Path, int]]:
    """(source, destination, mode) for every driver file the plugin ships. Empty when there is no driver/ folder."""
    if not DRIVER_SRC.is_dir():
        return []
    files: list[tuple[Path, Path, int]] = []
    for src in sorted((DRIVER_SRC / "bin").glob("*.py")):
        mode = 0o755 if src.name in ("thor_app.py", "touch_master_manager.py") else 0o644
        files.append((src, APP_DIR / "bin" / src.name, mode))
    files.append((PLUGIN_DIR / "debug_codes.py", APP_DIR / "debug_codes.py", 0o644))
    files.append((DRIVER_SRC / "systemd/touch-master.service", HOME / ".config/systemd/user/touch-master.service", 0o644))
    for name in ("touch-master.desktop", "touch-master-stop.desktop"):
        files.append((DRIVER_SRC / "share" / name, HOME / ".local/share/applications" / name, 0o755))
    files.append((DRIVER_SRC / "share/touch-master.svg", HOME / ".local/share/icons/hicolor/scalable/apps/touch-master.svg", 0o644))
    return [f for f in files if f[0].is_file()]


def _sync_driver() -> dict:
    """Copy the shipped driver files into the user's home when they are missing or differ. Returns what changed."""
    changed = {"bin": False, "unit": False, "any": False, "errors": []}
    try:
        st = HOME.stat()
    except OSError:
        return changed
    for src, dst, mode in _driver_files():
        try:
            data = src.read_bytes()
            if dst.is_file() and dst.read_bytes() == data:
                continue
            made = []
            p = dst.parent
            while not p.exists():
                made.append(p)
                p = p.parent
            dst.parent.mkdir(parents=True, exist_ok=True)
            for d in made:
                os.chown(d, st.st_uid, st.st_gid)
            tmp = dst.with_name(dst.name + ".tmp")
            tmp.write_bytes(data)
            os.chmod(tmp, mode)
            os.chown(tmp, st.st_uid, st.st_gid)
            os.replace(tmp, dst)
            changed["any"] = True
            changed["bin" if APP_DIR in dst.parents else "unit" if dst.suffix == ".service" else "any"] = True
        except Exception as exc:  # one bad file must not stop the plugin from loading
            changed["errors"].append(f"{dst}: {exc}")
    return changed


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
        "three_finger_swipe_enabled": False,
        "mirror_dim": False,
        "mirror_dim_floor_percent": 3,
        "keyboard_repeat_delay_ms": 350,
        "keyboard_repeat_interval_ms": 60,
        "keyboard_caps_window_ms": 350,
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


# Copy of bin/atomic_json.py (only main.py is installed here). It runs as root, so it keeps the config file's owner and mode.
def _write_json_atomic(path, data, indent: int = 2) -> None:
    path = os.fspath(path)
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    payload = json.dumps(data, indent=indent)  # serialise first: a failure here leaves the file alone
    try:
        ref = os.stat(path)
    except OSError:
        ref = os.stat(folder)  # a new file takes the folder's owner
        ref_mode = None
    else:
        ref_mode = ref.st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, ref_mode if ref_mode is not None else 0o644)
        chown = getattr(os, "chown", None)
        if chown is not None:
            try:
                chown(tmp, ref.st_uid, ref.st_gid)
            except OSError:
                pass  # not allowed to (not root) or not needed: the owner is already the caller
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_config(data: dict) -> None:
    try:
        _write_json_atomic(CONFIG_PATH, data)
    except Exception:
        pass


class Plugin:
    def __init__(self) -> None:
        self.logger = DebugLogger("plugin")

    async def _main(self) -> None:
        """Called automatically by Decky Loader on startup."""
        self.logger.log(DebugCode.DAEMON_STARTING, "Decky initialized Ratatoskr plugin")
        changed = _sync_driver()
        for err in changed["errors"]:
            self.logger.log(DebugCode.ERR_SERVICE_START, f"driver install: {err}")
        if changed["any"]:
            self.logger.log(DebugCode.DAEMON_STARTING, "Installed or updated the shipped driver files in the user's home")
            if changed["unit"]:
                self._run_systemctl("daemon-reload", None)
        cfg = _read_config()
        if cfg.get("enabled", True):
            if not _is_running():
                self._start_service()
            elif changed["bin"] or changed["unit"]:
                self._run_systemctl("restart")
        else:
            if _is_running():
                self._stop_service()

    def _run_systemctl(self, action: str, unit: str | None = "touch-master.service") -> bool:
        env = dict(os.environ)
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"

        tail = [action] + ([unit] if unit else [])
        cmds = [
            ["systemctl", "--machine=armada@.host", "--user", *tail],
            ["systemctl", "--user", *tail],
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
                    "three_finger_swipe_enabled": cfg.get("three_finger_swipe_enabled", False),
                    "mirror_dim": cfg.get("mirror_dim", False),
                    "mirror_dim_floor_percent": cfg.get("mirror_dim_floor_percent", 3),
                    "keyboard_repeat_delay_ms": cfg.get("keyboard_repeat_delay_ms", 350),
                    "keyboard_repeat_interval_ms": cfg.get("keyboard_repeat_interval_ms", 60),
                    "keyboard_caps_window_ms": cfg.get("keyboard_caps_window_ms", 350),
                    "bottom_dimmed": res.get("bottom_dimmed", False),
                    "pen_mode": res.get("pen_mode", "off"),
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

    async def set_pen_mode(self, mode: str) -> dict:
        """off, pen or pen_plus. Pen + also keeps Game Mode's pointer visible, which applies when Game Mode next starts."""
        def _set():
            if _is_running():
                return _send_ipc({"action": "set_pen_mode", "mode": mode})
            return {"ok": False}

        return await asyncio.to_thread(_set)

    async def run_diagnostics(self) -> dict:
        return await asyncio.to_thread(run_self_diagnostics)
