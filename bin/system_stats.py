"""System metrics & hardware control for Thor Input on Ayn Thor.

Hardware sysfs discovery, thermal nodes, and sensor paths credit to:
- Project Barry (https://github.com/project-barry/barry-launcher) by lavachemist.
- Armada OS (https://armadaos.dev).
"""
from __future__ import annotations

import glob
import os
import subprocess
import threading
import time
from typing import Any

TOP_BACKLIGHT_PATH = "/sys/class/backlight/ae96000.dsi.0"
BOTTOM_BACKLIGHT_PATH = "/sys/class/backlight/ae94000.dsi.0"
ARMADA_BOTTOM_BRIGHTNESS_FILE = "/etc/armada/bottom-screen-brightness"
BATTERY_PATH = "/sys/class/power_supply/battery"
GPU_PATH = "/sys/class/devfreq/3d00000.gpu"


def _read_str(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def _read_int(path: str, default: int = 0) -> int:
    try:
        val = _read_str(path)
        return int(val) if val else default
    except (ValueError, OSError):
        return default


SUDO_WRITE_TIMEOUT_S = 2.0
LAST_WRITE_ERROR = ""  # why the most recent write failed, for the logs


def _write_via_sudo(path: str, value: str, timeout: float = SUDO_WRITE_TIMEOUT_S) -> bool:
    """`sudo -n tee path`. A timeout leaves the outcome unknown (tee may have written before it was killed),
    so the value is read back instead of being reported as a failure."""
    global LAST_WRITE_ERROR
    try:
        res = subprocess.run(
            ["sudo", "-n", "tee", path],
            input=f"{value}\n",
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if res.returncode != 0:
            LAST_WRITE_ERROR = f"sudo tee {os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} exited {res.returncode}: {(res.stderr or '').strip()[:120]}"
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        ok = _read_str(path) == value.strip()
        if not ok:
            LAST_WRITE_ERROR = f"sudo tee {os.path.basename(path)} timed out after {timeout}s and the value was not written"
        return ok
    except Exception as err:
        LAST_WRITE_ERROR = f"sudo tee {os.path.basename(path)} raised {type(err).__name__}: {err}"
        return False


def _write_str(path: str, value: str) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value + "\n")
        return True
    except PermissionError:
        return _write_via_sudo(path, value)
    except OSError:
        return False


def _wpctl_env() -> dict[str, str]:
    env = os.environ.copy()
    if "XDG_RUNTIME_DIR" not in env:
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    return env


class _LatestWriter:
    """Runs fn(value) on its own thread. Values submitted while a write is in progress are folded into the
    newest one, so a fast slider drag costs one write per finished write instead of one per touch event."""

    def __init__(self, fn: Any, name: str) -> None:
        self._fn = fn
        self._name = name
        self._cond = threading.Condition()
        self._value: Any = None
        self._has_value = False
        self._busy = False
        self._thread: threading.Thread | None = None
        self.writes = 0

    def submit(self, value: Any) -> None:
        with self._cond:
            self._value = value
            self._has_value = True
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def wait_idle(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._has_value or self._busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True

    def _run(self) -> None:
        global LAST_WRITE_ERROR
        while True:
            with self._cond:
                while not self._has_value:
                    self._cond.wait()
                value, self._has_value = self._value, False
                self._busy = True
            try:
                self._fn(value)
            except Exception as err:  # a failed write must not end the writer
                LAST_WRITE_ERROR = f"{self._name} raised {type(err).__name__}: {err}"
            finally:
                with self._cond:
                    self._busy = False
                    self.writes += 1
                    self._cond.notify_all()


class HardwareStats:
    """Thread-safe cached sampler for system metrics and quick hardware controls.

    Slider writes go through request_* : they return at once, draw the requested value immediately (an overlay that
    lasts OPTIMISTIC_HOLD_S) and are written by a background thread. With start_sampler() running, get_stats()
    never samples on the caller's thread."""

    OPTIMISTIC_HOLD_S = 1.5

    def __init__(self, cache_ttl: float = 0.5, optimistic_hold: float = OPTIMISTIC_HOLD_S) -> None:
        self.cache_ttl = cache_ttl
        self.optimistic_hold = optimistic_hold
        self._last_sample_time = 0.0
        self.last_write_ok = True
        self.last_error = ""
        self._last_data: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._sample_lock = threading.Lock()
        self._optimistic: dict[str, tuple[Any, float]] = {}
        self._sampler: threading.Thread | None = None
        self._sampler_stop = threading.Event()
        self._writers = {
            "top": _LatestWriter(self.set_top_brightness, "write-top-backlight"),
            "bottom": _LatestWriter(self.set_bottom_brightness, "write-bottom-backlight"),
            "volume": _LatestWriter(self.set_volume, "write-volume"),
            "mute": _LatestWriter(self.set_mute, "write-mute"),
        }

        # Cache sensor paths
        self._cpu_policies = sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*"))
        self._thermal_zones = sorted(glob.glob("/sys/class/thermal/thermal_zone*"))
        self._cpu_thermal = [
            z for z in self._thermal_zones if _read_str(f"{z}/type").startswith("cpuss")
        ]
        self._gpu_thermal = [
            z for z in self._thermal_zones if "gpu" in _read_str(f"{z}/type")
        ]

        # CPU load tracking
        self._prev_cpu_idle = 0
        self._prev_cpu_total = 0

    def get_stats(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            have = bool(self._last_data)
            fresh = now - self._last_sample_time < self.cache_ttl
        if not have or (self._sampler is None and not fresh):
            self._refresh()
        with self._lock:
            data = dict(self._last_data)
            for key, (value, until) in list(self._optimistic.items()):
                if until > now:
                    data[key] = value
                else:
                    del self._optimistic[key]
            return data

    def _refresh(self) -> None:
        with self._sample_lock:
            data = self._sample()
        with self._lock:
            self._last_data = data
            self._last_sample_time = time.monotonic()

    def start_sampler(self, interval: float = 1.0) -> None:
        """Sample on a background thread so get_stats() (called from the draw and IPC threads) never blocks."""
        if self._sampler is not None:
            return
        self._refresh()
        self._sampler_stop.clear()

        def loop() -> None:
            while not self._sampler_stop.wait(interval):
                try:
                    self._refresh()
                except Exception:
                    pass

        self._sampler = threading.Thread(target=loop, name="stats-sampler", daemon=True)
        self._sampler.start()

    def stop_sampler(self) -> None:
        self._sampler_stop.set()
        self._sampler = None

    def _show(self, key: str, value: Any) -> None:
        with self._lock:
            self._optimistic[key] = (value, time.monotonic() + self.optimistic_hold)

    def request_volume(self, pct: int) -> int:
        target = max(0, min(100, int(pct)))
        self._show("vol_pct", target)
        self._writers["volume"].submit(target)
        return target

    def request_top_brightness(self, pct: int) -> int:
        target = max(5, min(100, int(pct)))
        self._show("top_bright_pct", target)
        self._writers["top"].submit(target)
        return target

    def request_bottom_brightness(self, pct: int) -> int:
        target = max(5, min(100, int(pct)))
        self._show("bot_bright_pct", target)
        self._writers["bottom"].submit(target)
        return target

    def wait_for_writes(self, timeout: float = 2.0) -> bool:
        return all(w.wait_idle(timeout) for w in self._writers.values())

    def _sample(self) -> dict[str, Any]:
        # 1. CPU
        cpu_load = 0
        try:
            with open("/proc/stat", encoding="utf-8") as f:
                first_line = f.readline()
                parts = [int(x) for x in first_line.split()[1:]]
                idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                total = sum(parts)
                if self._prev_cpu_total > 0:
                    diff_idle = idle - self._prev_cpu_idle
                    diff_total = total - self._prev_cpu_total
                    if diff_total > 0:
                        cpu_load = max(0, min(100, round(100 * (1.0 - diff_idle / diff_total))))
                self._prev_cpu_idle = idle
                self._prev_cpu_total = total
        except Exception:
            pass

        cpu_freqs = [_read_int(f"{p}/scaling_cur_freq") for p in self._cpu_policies]
        cpu_ghz = max(cpu_freqs, default=0) / 1e6

        cpu_temp = 0
        if self._cpu_thermal:
            t_sum = sum(_read_int(f"{z}/temp") for z in self._cpu_thermal)
            cpu_temp = round(t_sum / len(self._cpu_thermal) / 1000)

        # 2. GPU
        gpu_mhz = _read_int(f"{GPU_PATH}/cur_freq") // 1_000_000
        gpu_temp = 0
        if self._gpu_thermal:
            t_sum = sum(_read_int(f"{z}/temp") for z in self._gpu_thermal)
            gpu_temp = round(t_sum / len(self._gpu_thermal) / 1000)

        # 3. RAM
        ram_used_gb = 0.0
        ram_total_gb = 0.0
        ram_pct = 0
        try:
            mem: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    if k in ("MemTotal", "MemAvailable"):
                        mem[k] = int(v.split()[0])
            total_kb = mem.get("MemTotal", 0)
            avail_kb = mem.get("MemAvailable", 0)
            if total_kb > 0:
                ram_total_gb = round(total_kb / 1024**2, 1)
                ram_used_gb = round((total_kb - avail_kb) / 1024**2, 1)
                ram_pct = round((total_kb - avail_kb) * 100 / total_kb)
        except Exception:
            pass

        # 4. Battery
        bat_cap = _read_int(f"{BATTERY_PATH}/capacity")
        bat_status = _read_str(f"{BATTERY_PATH}/status", "Discharging")
        v_now = _read_int(f"{BATTERY_PATH}/voltage_now")
        c_now = _read_int(f"{BATTERY_PATH}/current_now")
        bat_watts = round(v_now * c_now / 1e12, 1)

        # 5. Audio (Volume)
        vol_pct = 0
        is_muted = False
        try:
            res = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=0.4,
                env=_wpctl_env(),
            )
            if res.returncode == 0:
                line = res.stdout.strip()
                is_muted = "[MUTED]" in line or "MUTED" in line
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        vol_pct = round(float(parts[1]) * 100)
                    except ValueError:
                        pass
        except Exception:
            pass

        # 6. Backlight
        top_b = _read_int(f"{TOP_BACKLIGHT_PATH}/brightness")
        top_max = _read_int(f"{TOP_BACKLIGHT_PATH}/max_brightness", 4096)
        top_pct = max(0, min(100, round(top_b * 100 / top_max))) if top_max > 0 else 0

        bot_b = _read_int(f"{BOTTOM_BACKLIGHT_PATH}/brightness")
        bot_max = _read_int(f"{BOTTOM_BACKLIGHT_PATH}/max_brightness", 255)
        bot_pct = max(0, min(100, round(bot_b * 100 / bot_max))) if bot_max > 0 else 0

        return {
            "cpu_load": cpu_load,
            "cpu_ghz": round(cpu_ghz, 2),
            "cpu_temp": cpu_temp,
            "gpu_mhz": gpu_mhz,
            "gpu_temp": gpu_temp,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "ram_pct": ram_pct,
            "bat_cap": bat_cap,
            "bat_status": bat_status,
            "bat_watts": bat_watts,
            "vol_pct": vol_pct,
            "vol_muted": is_muted,
            "top_bright_pct": top_pct,
            "bot_bright_pct": bot_pct,
        }

    # Control Methods

    def set_volume(self, pct: int) -> int:
        target = max(0, min(100, int(pct)))
        frac = target / 100.0
        try:
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{frac:.2f}"],
                check=False,
                timeout=0.5,
                env=_wpctl_env(),
            )
        except Exception:
            pass
        self._last_sample_time = 0.0  # Invalidate cache
        return target

    def adjust_volume(self, delta: int) -> int:
        cur = self.get_stats().get("vol_pct", 50)
        return self.request_volume(cur + delta)

    def set_mute(self, muted: bool) -> bool:
        try:
            subprocess.run(
                ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"],
                check=False,
                timeout=0.5,
                env=_wpctl_env(),
            )
        except Exception:
            pass
        self._last_sample_time = 0.0
        return muted

    def toggle_mute(self) -> bool:
        """Flip the mute state: the new state is drawn at once and a writer sets it explicitly (not 'toggle'),
        so fast repeated taps cannot get out of step with what is shown."""
        muted = not self.get_stats().get("vol_muted", False)
        self._show("vol_muted", muted)
        self._writers["mute"].submit(muted)
        return muted

    def set_top_brightness(self, pct: int) -> int:
        target = max(5, min(100, int(pct)))
        max_b = _read_int(f"{TOP_BACKLIGHT_PATH}/max_brightness", 4096)
        val = round(target * max_b / 100)
        _write_str(f"{TOP_BACKLIGHT_PATH}/brightness", str(val))
        self._last_sample_time = 0.0
        return target

    def adjust_top_brightness(self, delta: int) -> int:
        cur = self.get_stats().get("top_bright_pct", 100)
        return self.request_top_brightness(cur + delta)

    def set_bottom_brightness(self, pct: int, persist: bool = True, minimum: int = 5) -> int:
        """Write the bottom backlight. persist=False leaves Armada's saved level alone (idle dimming)."""
        target = max(minimum, min(100, int(pct)))
        max_b = _read_int(f"{BOTTOM_BACKLIGHT_PATH}/max_brightness", 255)
        val = max(1, round(target * max_b / 100))
        ok = _write_str(f"{BOTTOM_BACKLIGHT_PATH}/brightness", str(val))
        if persist:
            ok = _write_str(ARMADA_BOTTOM_BRIGHTNESS_FILE, str(target)) and ok
        self.last_write_ok = ok
        self.last_error = "" if ok else LAST_WRITE_ERROR
        self._last_sample_time = 0.0
        return target

    def adjust_bottom_brightness(self, delta: int) -> int:
        cur = self.get_stats().get("bot_bright_pct", 100)
        return self.request_bottom_brightness(cur + delta)
