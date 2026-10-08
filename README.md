# Ratatoskr

> **Ratatoskr** is the squirrel that runs messages up and down Yggdrasil: it carries your touches from the bottom screen to the game on the top one. It was called *Touch Master* until 2026-10-08; the service, config folder, socket and install paths still use the old `touch-master` / `thor-input` names so existing installs keep working.

A dedicated **Decky Loader plugin** and virtual input driver for the **AYN Thor Max** (Snapdragon 8 Gen 2, dual-screen handheld running Armada OS).

Turns the lower 3.92" AMOLED screen into a zero-latency, highly customizable **Trackpad**, **Keyboard**, **Split input device**, or **Quick Settings & Hardware Monitor** for Steam Game Mode and desktop games on the primary 6" screen, with **zero launcher clutter**.

---

## ✨ Features

- **No Launcher Overhead:** Pure input surface—no tiles, cover art, or nested menus.
- **AMOLED-Optimized:** Pure black `#000000` aesthetic matching the Thor bezel. Unused pixels stay completely unpowered.
- **Four Instant Modes:**
  - **Trackpad:** 1-finger relative movement with smooth acceleration, tap-to-click, drag-lock, momentum glide ("Ball mode"), and full multi-touch gestures.
  - **Keyboard:** 5-row thumb-friendly QWERTY layout emitting real Linux hardware scan codes (`EV_KEY`) via `/dev/uinput` with dual-symbol keys and active modifier glow.
  - **Split Mode:** Top half is Trackpad, bottom half is Keyboard. Drive cursor targeting and hotkeys simultaneously (ideal for *FTL*, *Caves of Qud*, roguelikes, and terminal use).
  - **Quick Controls:** On-glass interactive sliders for system volume (PipeWire/WirePlumber), top screen backlight (`ae96000.dsi.0`), and bottom AMOLED backlight (`ae94000.dsi.0`).
- **Bottom screen follows Steam's idle dim (opt-in):** Steam dims only the top panel (Armada steers Steam's backlight writes to it). Switch on *Dim bottom screen with the top* in the Decky menu and Ratatoskr reads Steam's own delay (`IdleBacklightDimBatterySeconds` / `IdleBacklightDimACSeconds` in `~/.local/share/Steam/config/config.vdf`, 0 = never), watches input on every readable device, and dims the bottom panel to `mirror_dim_floor_percent` (default 3 %) after that long without input, restoring it on the next input. It never writes Armada's saved bottom-screen level. Sleep needs nothing: Armada's fake-suspend already blanks every backlight. Needs the optional `systemd/touch-master-backlight.sudoers` (see the file). Log lines (`DBG-610` in `/tmp/thor-input-debug.log`) also record when the top backlight really drops, so the timer can be checked against Steam.
- **Live System Monitor Ribbon:** Always-visible status ribbon reporting Battery % & Watts, CPU Load & Temperature, GPU Frequency & Temperature, RAM usage, Volume, and dual Backlights.
- **Edge Scroll Mode:**
  - Toggle between 2-finger scroll and **Edge Scroll**.
  - When toggled on, draws an on-glass vertical scrollbar with gutter track, chevrons (▲/▼), and an active cyan thumb along the right edge of the trackpad. Single-finger drag in the gutter smoothly scrolls.
- **Customizable Dynamics & Gestures (Decky QAM):**
  - **Pointer Sensitivity:** 0.5x to 3.5x.
  - **Momentum Glide & Friction:** Adjustable deceleration friction (1 = slick coasting to 10 = heavy drag).
  - **Scroll Speed:** Precision to fast velocity (1 to 5).
  - **Tap to Click:** 1-finger tap primary click toggle.
  - **Long-Press Right Click:** Toggleable with adjustable duration (250ms – 900ms).
  - **Two-Finger Right Click:** 2-finger tap secondary click toggle.
  - **Three-Finger Middle Click:** 3-finger tap middle click toggle.
  - **Pinch-to-Zoom:** 2-finger pinch emits Ctrl + Wheel.
  - **Navigation Swipes:** 3-finger swipes (Up = Super/Steam, Down = Escape, Left/Right = Alt+Tab).
  - **Drag Lock:** Double-tap and drag holds the primary mouse button.
- **Built-in Diagnostics & Logging (`debug_codes.py`):**
  - Standardized diagnostic codes for `/dev/uinput`, touch digitizer, IPC socket, gestures, volume, and backlights.
  - Live on-glass HUD overlay showing FPS, touch coordinates, and event counters.
  - Structured logging written to `/tmp/thor-input-debug.log`.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│               Top Screen (Game / Steam)                │
└────────────────────────────────────────────────────────┘
                            ▲
                            │ /dev/uinput Events (zero lag)
┌───────────────────────────┴────────────────────────────┐
│      Bottom Screen GTK 3 Application (thor_app.py)     │
│  • Fullscreen on Gamescope secondary display (:2)      │
│  • Reads /dev/input/event5 (bottom_touchscreen)        │
│  • Exclusive grab (EVIOCGRAB)                          │
│  • UNIX IPC Socket: /run/user/1000/thor-input.sock     │
└───────────────────────────▲────────────────────────────┘
                            │ UNIX Socket IPC
┌───────────────────────────┴────────────────────────────┐
│          Ratatoskr Decky Backend (main.py)          │
│  • Manages daemon lifecycle                            │
│  • Reports diagnostic codes, stats & telemetry         │
└───────────────────────────▲────────────────────────────┘
                            │ Decky API
┌───────────────────────────┴────────────────────────────┐
│            Decky QAM Frontend (dist/index.js)          │
│  • Sliders, toggles & telemetry in Steam (...) menu    │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Deployment

```bash
# Deploy to Thor device over SSH
./scripts/deploy.sh armada@<thor-ip>
```

Or copy manually:
- Decky plugin files (`plugin.json`, `package.json`, `main.py`, `debug_codes.py`, `dist/index.js`) to `/home/armada/homebrew/plugins/thor-input/`
- Backend files (`bin/`, `debug_codes.py`) to `/var/home/armada/.local/share/thor-input/`
- Restart Decky: `sudo systemctl restart plugin_loader.service`

---

## 🔍 Diagnostic Codes Registry

| Code | Label | Description |
|---|---|---|
| `DBG-000` | `OK` | System healthy and operational |
| `DBG-100` | `UINPUT_OK` | Virtual mouse and keyboard created |
| `DBG-101` | `ERR_UINPUT_OPEN` | Cannot open `/dev/uinput` |
| `DBG-200` | `TOUCH_OK` | `bottom_touchscreen` opened and grabbed |
| `DBG-201` | `ERR_TOUCH_MISSING` | `bottom_touchscreen` node missing |
| `DBG-203` | `ERR_TOUCH_GRAB` | `EVIOCGRAB` failed |
| `DBG-300` | `SOCKET_OK` | IPC socket `/run/user/1000/thor-input.sock` ready |
| `DBG-400` | `DISPLAY_OK` | Connected to secondary display `:2` |
| `DBG-510` | `STATUS_CLICK_LEFT` | Primary click emitted |
| `DBG-511` | `STATUS_CLICK_RIGHT` | Secondary click emitted |
| `DBG-512` | `STATUS_CLICK_MIDDLE`| Middle click emitted |
| `DBG-520` | `STATUS_SCROLL` | Scroll wheel emitted |
| `DBG-521` | `STATUS_EDGE_SCROLL` | Edge scrollbar active |
| `DBG-522` | `STATUS_PINCH_ZOOM` | Pinch zoom gesture emitted |
| `DBG-523` | `STATUS_SWIPE_NAV` | Multi-finger navigation swipe emitted |
| `DBG-524` | `STATUS_DRAG_LOCK` | Drag lock engaged |
| `DBG-525` | `STATUS_LONG_PRESS` | Long-press right click emitted |
| `DBG-530` | `STATUS_GLIDE_START` | Momentum glide coasting |
| `DBG-540` | `STATUS_KEY_PRESS` | Hardware keystroke emitted |
| `DBG-600` | `SETTINGS_UPDATED` | Settings applied and saved to config |
| `DBG-601` | `BACKLIGHT_UPDATED` | Top or bottom backlight brightness adjusted |
| `DBG-602` | `VOLUME_UPDATED` | Master volume adjusted or muted |
| `DBG-610` | `DIM_MIRROR` | Bottom screen dimmed/restored to follow Steam's idle dim; top backlight drops observed |

---

## 🙏 Credits & Acknowledgments

Credit where credit is due: this utility is deeply indebted to and builds upon the pioneering work of:

- **[Project Barry / Barry Launcher](https://github.com/project-barry/barry-launcher)** by **lavachemist** and the Project Barry community:
  - Dual-display Gamescope architecture on the AYN Thor.
  - Raw digitizer coordinate mapping (`raw_to_screen`) from the 90-degree rotated portrait AMOLED panel.
  - Trackpad multi-touch gesture processing algorithms and momentum physics.
  - Sensor discovery patterns in `/sys/class/thermal/`, `/sys/class/devfreq/`, and `/sys/class/power_supply/`.
- **[Armada OS](https://armadaos.dev)** by the Armada Linux team:
  - Dual-display Gamescope session runner (`/usr/bin/armada-run-bottom`).
  - Qualcomm SM8550 device tree and backlight driver bindings (`ae94000.dsi.0` and `ae96000.dsi.0`).
- **[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)** by the SteamDeckHomebrew community:
  - The standard Decky plugin architecture, sandboxed Python backend, and React/DFL Quick Access Menu (QAM) framework.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
