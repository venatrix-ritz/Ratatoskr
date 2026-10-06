# Thor Input

A dedicated **Decky Loader plugin** and input driver for the **AYN Thor Max** (Snapdragon 8 Gen 2, dual-screen handheld running Armada OS).

Turns the lower 3.92" AMOLED screen into a zero-latency **Trackpad**, **Keyboard**, or **Split input device** for Steam Game Mode and desktop games on the primary 6" screen, with **zero launcher clutter**.

---

## Features

- **No Launcher Overhead:** Pure input surface—no tiles, cover art, or nested menus.
- **AMOLED-Optimized:** Pure black `#000000` aesthetic matching the Thor bezel. Unused pixels stay off.
- **Three Modes (Instant Glass Switch):**
  - **Trackpad:** 1-finger relative movement with smooth acceleration, tap-to-click, drag-lock, 2-finger scroll, 2-finger right click, and momentum glide ("Ball mode").
  - **Keyboard:** 5-row thumb-friendly QWERTY layout emitting real Linux hardware scan codes (`EV_KEY`) via `/dev/uinput`.
  - **Split Mode:** Top 40% is Trackpad, bottom 60% is Keyboard. Drive cursor targeting and hotkeys simultaneously (ideal for *FTL*, *Caves of Qud*, roguelikes, and terminal use).
- **Physical Click Helpers:** Dedicated on-glass buttons for Left Click and Right Click (can be held while steering).
- **Decky Quick Access Menu (QAM):**
  - Toggle input mode on/off.
  - Switch modes (`Trackpad`, `Split`, `Keyboard`).
  - Tune pointer sensitivity (0.5x – 3.5x).
  - Toggle momentum glide.
  - Real-time diagnostic telemetry and on-glass HUD overlay toggle.
- **Built-in Diagnostics (`debug_codes.py`):**
  - Standardized error codes for `/dev/uinput`, touch digitizer, and IPC socket.
  - Self-test diagnostic runner directly inside Decky.
  - Live on-glass HUD overlay showing FPS, touch coordinates, and event counters.

---

## Architecture

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
│               Decky Plugin Backend (main.py)           │
│  • Manages daemon lifecycle                            │
│  • Reports diagnostic codes and telemetry              │
└───────────────────────────▲────────────────────────────┘
                            │ Decky API
┌───────────────────────────┴────────────────────────────┐
│            Decky QAM Frontend (dist/index.js)          │
│  • User controls & settings in Steam (...) menu        │
└────────────────────────────────────────────────────────┘
```

---

## Deployment

```bash
# Deploy to Thor device over SSH
./scripts/deploy.sh armada@<thor-ip>
```

Or copy manually:
- Decky plugin files (`plugin.json`, `main.py`, `debug_codes.py`, `dist/index.js`) to `/home/armada/homebrew/plugins/thor-input/`
- Backend files (`bin/`, `debug_codes.py`) to `/var/home/armada/.local/share/thor-input/`
- Restart Decky: `sudo systemctl restart plugin_loader.service`

---

## Diagnostic Codes

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

---

## License

MIT
