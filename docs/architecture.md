# Architecture

```
 Steam UI (top screen)                  Bottom screen (separate gamescope, DRM-leased panel)
 ┌──────────────────────┐               ┌────────────────────────────────────────────┐
 │ Decky panel          │  Decky call   │ thor_app.py  (GTK 3 + cairo, DISPLAY :2)   │
 │ dist/index.js        │──────────────▶│  • touch reader thread (grabs the digitizer)│
 └──────────┬───────────┘               │  • gesture engine → UInputBridge            │
            │                           │  • IPC server  /run/user/<uid>/thor-input.sock
 ┌──────────▼───────────┐  JSON / UNIX  │  • stats sampler, idle tracker, dim mirror │
 │ Decky backend        │──────────────▶│                                            │
 │ main.py              │  socket       └───────────────┬────────────────────────────┘
 └──────────┬───────────┘                               │ /dev/uinput
            │ systemctl --user                          ▼
            ▼                              virtual mouse + keyboard → game on the top screen
   touch-master.service  ──runs──▶  armada-run-bottom -- python3 thor_app.py
```

## Pieces
- **`bin/thor_app.py`** is the whole driver: it finds the bottom touchscreen, grabs it exclusively (`EVIOCGRAB`) so touches do not reach the desktop, draws the UI, runs the gesture engine, serves the IPC socket and starts the idle tracker and dim mirror. It runs inside the bottom screen's gamescope through Armada's `armada-run-bottom` helper, which loads that session's environment.
- **`bin/engine.py`** holds `UInputBridge` (creates the virtual devices) and `TouchGestureProcessor` (turns finger contacts into pointer, scroll, click and key events).
- **`bin/keyboard_layout.py`** is the on-glass keyboard: key geometry and hit testing.
- **`bin/system_stats.py`** reads battery, CPU, GPU, RAM, backlights and volume (PipeWire through `wpctl`), and writes volume and brightness. A background thread samples once a second, so drawing and IPC never wait on a sample (a sample took about 29 ms on the Thor, 2026-10-08). Slider writes go through `request_*`: the requested value is drawn at once and a writer thread per control writes only the newest value (each `sudo tee` write took about 25 ms, and the bottom slider needs two).
- **`bin/dim_mirror.py`** is the optional idle-dim follower ([dim-mirror.md](dim-mirror.md)).
- **`bin/touch_master_manager.py`** is the standalone GTK window and CLI.
- **`main.py`** is the Decky backend; **`dist/index.js`** is the panel (plain JavaScript written for Decky's `DFL` and `SP_REACT` globals, no build step).
- **`debug_codes.py`** is the diagnostic code registry and logger shared by all of them.

## Touch path
The digitizer node is the input device whose name contains "bottom" and "touchscreen" (fallback `/dev/input/event5`). Raw coordinates are mapped to the 1240 by 1080 drawing space with `raw_to_screen` (the panel is mounted rotated, so `x = raw_y`, `y = height - 1 - raw_x`). Because the node is grabbed, nothing else can read it: the idle tracker is told about touches by the app instead.

## Virtual devices
Two uinput devices on the virtual bus: **Thor Virtual Trackpad** (vendor `0x1234`, product `0x5678`) and **Thor Virtual Keyboard** (`0x5679`).

## IPC protocol
One request per connection on the stream socket `/run/user/<uid>/thor-input.sock`: the client sends one JSON object (at most 64 KiB, in as many pieces as it likes, complete within 2 s) and reads one JSON reply, `{"ok": true, "code": 0, ...}`, until the driver closes the connection. A bad request, a failing handler or an unknown action gets `{"ok": false, "code": 303, "error": ...}` and is logged (`DBG-303`). Helpers for both sides are in `bin/ipc_util.py`; the Decky backend carries its own small copy of the read loop because only `main.py` is installed in the plugin folder.

| `action` | Request fields | Reply adds |
|---|---|---|
| `get_status` | | `mode`, `debug_hud`, `hardware_stats`, every gesture setting, `mirror_dim`, `mirror_dim_floor_percent`, `bottom_dimmed`, `pen_mode`, `cursor_stay_visible`, `cursor_hide_delay_ms`, `cursor_stay_visible_active` |
| `get_debug` | | `telemetry`, `state`, `coords`, `touch_device`, `active_fingers`, `last_key`, `hardware_stats`, gesture settings |
| `set_mode` | `mode` | |
| `set_pen_mode` | `mode`: `off`, `pen` or `pen_plus` | `pen_mode` and the `cursor_*` fields; `pen_plus` also writes Game Mode's pointer-visible override, which applies when Game Mode next starts |
| `set_settings` | flat keys, e.g. `sensitivity`, `mirror_dim` | |
| `set_volume` | `volume` (0 to 100) | `vol_pct` |
| `toggle_mute` | | `vol_muted` |
| `set_top_brightness` | `brightness` (percent) | `top_bright_pct` |
| `set_bottom_brightness` | `brightness` (percent) | `bot_bright_pct` |
| `wake` | | taps `KEY_F24` on the virtual keyboard (no default binding anywhere) and counts as input for the dim mirror. Steam and the compositor treat it as input: a Steam-dimmed top screen is restored within about a second and the idle and sleep timers restart (verified on the Thor 2026-10-08) |
| `toggle_hud` | | `debug_hud` |
| `run_diagnostics` | | `diagnostics` |
| `quit` | | |

The Decky backend wraps these as `get_status`, `set_enabled`, `set_mode`, `set_settings`, `set_pen_mode`, `set_volume`, `toggle_mute`, `set_brightness(target, percent)`, `toggle_hud` and `run_diagnostics`. It starts and stops the service with `systemctl --user` (first trying `--machine=armada@.host`, which works from Decky's root context).

## Threads in the driver
GTK main thread (drawing, 1 s ribbon refresh), touch reader (`select` on the grabbed node), IPC server (0.5 s accept timeout, 2 s per request), key repeat, momentum glide, idle tracker, dim mirror. Hardware stats are sampled with a 0.4 s cache.

## Logging
Every component logs `[time] [DBG-nnn] [context] description - details` to stdout (the service journal) and to `/tmp/thor-input-debug.log`. The codes are listed in the README and defined in `debug_codes.py`; `DBG-610` is the dim mirror.
