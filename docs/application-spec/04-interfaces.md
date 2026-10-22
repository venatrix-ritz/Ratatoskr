# 04 - Interfaces: inputs, outputs, CLI and IPC

## Inputs

| Input | Read by | Format | Notes | Source |
|---|---|---|---|---|
| Bottom touchscreen | `_reader_loop` in the driver | Linux `input_event` records (`llHHi`, 24 bytes on 64-bit), read in batches of up to 256 events | exclusive grab; `SYN_REPORT` closes a frame; `SYN_DROPPED` discards state | `bin/thor_app.py:533-570`, `bin/touch_frames.py:13-18`, `:47-70` |
| Other input devices (idle tracking only) | `IdleTracker` | same records | every `/dev/input/event*` except the touchscreen and names containing "haptics", "Jack", "lid", "Thor Virtual", "pmic_"; rescanned every 5 s | `bin/dim_mirror.py:62-63`, `:110-148` |
| Config file | driver at start, Decky backend and manager on every call | JSON object | see [05](05-configuration-requirements.md#configuration-file) | `bin/thor_app.py:209-223`, `main.py:137-146`, `bin/touch_master_manager.py:56-64` |
| Top backlight | `DimMirror`, `HardwareStats` | integers in sysfs files | read four times a second while the dim is on | `bin/dim_mirror.py:365-374`, `:379` |
| Bottom and top backlight, battery, GPU, thermal, `/proc/stat`, `/proc/meminfo` | `HardwareStats._sample` once a second | sysfs and proc text | | `bin/system_stats.py:250-359` |
| `wpctl get-volume` | `HardwareStats._sample` | `Volume: 0.40` with optional `[MUTED]` | timeout 0.4 s | `bin/system_stats.py:312-332` |
| `/proc/<pid>/cmdline` | `session_cursor.running_delay_ms` | NUL-separated arguments | cached 10 s | `bin/session_cursor.py:237-270` |
| `/etc/armada/bottom-screen-brightness` | `DimMirror._dim`, `read_saved_bottom_level` | integer 0 to 100 | | `bin/dim_mirror.py:69-76`, `:332` |
| Recovery file | `DimMirror.recover` | JSON `{"pct": int, "ts": float}` | `~/.local/state/thor-input/dim-restore.json` | `bin/dim_mirror.py:53`, `:280-311` |
| `gleipnir --status --json` | `gleipnir_view.read_status` | JSON object | timeout 3 s; `systemctl is-active --quiet gleipnir` timeout 2 s | `bin/gleipnir_view.py:30-47` |
| Gleipnir sysfs | `gleipnir_view.read_battery` | text values from `/sys/class/power_supply/battery` and `qcom-battmgr-usb` | | `bin/gleipnir_view.py:61-73` |
| Journal, tag `gleipnir` | `gleipnir_view.read_events` | `journalctl -t gleipnir -n 400 --no-pager -o short` | keeps the last two decisions | `bin/gleipnir_view.py:76-93` |
| IPC request | `_ipc_loop` in the driver, `ipc_util.read_json_request` | one JSON object per connection | see [IPC reference](#ipc-reference) | `bin/thor_app.py:920-1026` |
| Keyboard and mouse actions from the user | `_dispatch_frame` through `TouchGestureProcessor` and the keyboard handlers | touch frames | | `bin/thor_app.py:591-620` |

## Outputs

| Output | Written by | Format or effect | Source |
|---|---|---|---|
| Virtual pointer | `UInputBridge` on `/dev/uinput` | relative motion, wheel and hi-res wheel, `BTN_LEFT`, `BTN_RIGHT`, `BTN_MIDDLE` | `bin/engine.py:187-273` |
| Virtual keys | `UInputBridge.key` on `/dev/uinput` | `EV_KEY` press and release, key codes 1 to 247 | `bin/engine.py:275-300` |
| Bottom screen | GTK drawing | cairo drawing on the 1240 by 1080 window | `bin/thor_app.py:1032-1078` |
| IPC reply | driver | one JSON object, then close | `bin/thor_app.py:1015` |
| Driver log | `DebugLogger` | lines `[time] [DBG-nnn] [context] description - details` to stdout and `/tmp/thor-input-debug.log` | `debug_codes.py:120-137` |
| Config file | driver (`save_config`), Decky backend, manager | JSON, written by temp file and rename, owner and mode kept | `bin/thor_app.py:225-248`, `bin/atomic_json.py:18-49`, `main.py:149-190`, `bin/touch_master_manager.py:67-71` |
| Backlight writes | `HardwareStats.set_top_brightness`, `set_bottom_brightness` | integer text to the `brightness` file; `sudo -n tee` when the direct write is denied | `bin/system_stats.py:68-76`, `:403-426` |
| Armada saved bottom level | `set_bottom_brightness(persist=True)` and `DimMirror._dim` | integer text to `/etc/armada/bottom-screen-brightness`, also through `sudo -n tee` if needed | `bin/system_stats.py:415-426`, `bin/dim_mirror.py:337-347` |
| Volume and mute | `set_volume`, `set_mute` | `wpctl set-volume @DEFAULT_AUDIO_SINK@ <0.00 to 1.00>`, `wpctl set-mute @DEFAULT_AUDIO_SINK@ 0|1` | `bin/system_stats.py:363-393` |
| Pen + override | `session_cursor.set_stay_visible` | `~/.config/environment.d/50-ratatoskr-cursor.conf` with `HIDE_CURSOR_DELAY_MS=3600000`; deleted when Pen + is left | `bin/session_cursor.py:198-234` |
| Driver files in the home folder (release zip only) | `main.py` `_sync_driver` | copies of `bin/*.py`, `debug_codes.py`, the unit and the desktop entries | `main.py:60-106` |
| systemd service actions | `main.py` `_run_systemctl`, manager | `systemctl --user` and `systemctl --machine=armada@.host --user` | `main.py:214-238`, `bin/touch_master_manager.py:78-117` |
| Dim recovery file | `DimMirror._write_record` | JSON | `bin/dim_mirror.py:262-278` |
| Socket file | `_start_ipc_server` and `cleanup` | `/run/user/<uid>/thor-input.sock` created on start and removed on exit | `bin/thor_app.py:908-926`, `:497` |

## CLI reference

### `bin/touch_master_manager.py` (the standalone manager)

Run as `~/.local/share/thor-input/bin/touch_master_manager.py [flag]` on the Thor, or as `python3` with the same path.
With no flag it opens the GTK window (`bin/touch_master_manager.py:461`).

| Flag | Effect | Exit code | Source |
|---|---|---|---|
| `--start` | write `enabled: true`, disable `armada-bottom-screen.service`, enable and start `touch-master.service`; prints `Started` or `Failed to start` | 0 on success, 1 otherwise | `bin/touch_master_manager.py:92-102`, `:431-434` |
| `--stop` | write `enabled: false`, stop and disable `touch-master.service`, enable and start `armada-bottom-screen.service`; prints `Stopped` or `Failed to stop` | 0 or 1 | `bin/touch_master_manager.py:105-117`, `:435-438` |
| `--toggle` | `--stop` if the service is active, otherwise `--start`; prints `Toggled` or `Failed to toggle` | 0 or 1 | `bin/touch_master_manager.py:120-124`, `:439-442` |
| `--status` | prints JSON `{"service_active", "config", "ipc"}` with the driver's `get_status` reply | always 0 | `bin/touch_master_manager.py:447-452` |
| `--wake` | sends `{"action": "wake"}`, prints the reply | 0 if `ok`, else 1 | `bin/touch_master_manager.py:443-446` |
| `--mode {trackpad,keyboard,settings}` | saves `mode` in the config file and sends `set_mode`; prints the reply | always 0, even if the driver did not answer | `bin/touch_master_manager.py:453-459` |

`argparse` rejects other values for `--mode`. `split` is not offered (`bin/touch_master_manager.py:428`).

### `scripts/deploy.sh [host]`

Copies the driver, desktop entries, icon, user unit and Decky files to the Thor over `scp` and `ssh`, reloads the user
systemd, restarts `plugin_loader.service` and `touch-master.service`, and prints `is-active`. Host resolution, in order
(`scripts/deploy.sh:5-14`):

1. the first argument;
2. `THOR_HOST` in the environment;
3. `THOR_ENV_FILE`, then `local/thor.env` in the repo, then `../../local/thor.env`, each read for a `THOR_HOST=` line.

With none set it prints an error and exits 2. It uses `set -euo pipefail`. It runs no tests (see
[06](06-testing-limitations-glossary.md#documentation-and-code-mismatches-found-in-this-review)).

### `scripts/deploy-decky-panel.sh [host]`

Same host resolution. Copies only `plugin.json`, `package.json`, `debug_codes.py`, `main.py` and `dist/index.js`, moves
them into the plugin folder with `sudo`, and restarts `plugin_loader.service` (`scripts/deploy-decky-panel.sh:18-31`).
It does not touch the driver.

### `scripts/build-release.py [OUT.zip]`

Builds the Armada Store archive. Default output `release/Ratatoskr.zip` (`scripts/build-release.py:33`). The archive has
one top-level folder, `thor-input/`. Files are read from `HEAD`, not the working tree (`scripts/build-release.py:45`). It
exits with an error if a mapped file is not tracked by git (`:40-42`).

### `bin/thor_app.py`

Takes no arguments. `main()` installs signal handlers for SIGINT and SIGTERM and then runs the GTK main loop
(`bin/thor_app.py:1603-1620`). SIGTERM leaves the loop and runs `cleanup()`. The exit code is 1 after a lost touch device
and 0 otherwise.

### `debug_codes.py`

A module only. It has no command line. `run_self_diagnostics()` is called from the driver's IPC and the Decky backend.

### Other scripts (not part of the driver)

- `scripts/artemis-wrapper.sh` launches an Artemis client binary with a Gamescope X11 display. `docs/development.md`
  says it is not part of Ratatoskr's function. Not documented further here.
- `scripts/update-artemis-config.py` rewrites Artemis client settings files under `/var/home/armada/.config`. It takes no
  arguments. Not part of Ratatoskr's function.

## IPC reference

### Transport and framing

| Property | Value | Source |
|---|---|---|
| Socket | `/run/user/<uid>/thor-input.sock` (the driver uses `os.getuid()`; `main.py` hard-codes uid 1000) | `bin/thor_app.py:73`, `main.py:25`, `bin/touch_master_manager.py:28` |
| Type | UNIX stream | `bin/thor_app.py:915` |
| Requests per connection | one JSON object | `bin/ipc_util.py:18-43` |
| Request size limit | 64 KiB | `bin/ipc_util.py:14` |
| Request time limit | 2 s to complete | `bin/ipc_util.py:18`, `bin/thor_app.py:930` |
| Reply | one JSON object, then the driver closes; clients read to end of file | `bin/thor_app.py:1015`, `bin/ipc_util.py:46-64` |
| Reply size limit (clients) | 1 MiB | `bin/ipc_util.py:15`, `main.py` `_send_ipc` |
| Accept timeout | 0.5 s | `bin/thor_app.py:918` |
| Client timeouts | 2.0 s in `main.py` and `ipc_util.request`; 1.0 s in the manager | `main.py:35-57`, `bin/touch_master_manager.py:74` |

A connection that sends nothing and closes gets no reply (`bin/thor_app.py:931-932`). A request that is not a JSON object,
is malformed, is too large, or raises in its handler gets `{"ok": false, "code": 303, "error": "..."}` and is logged as
`DBG-303` (`bin/thor_app.py:1016-1021`, `debug_codes.py:38`). An unknown `action` gets the same code.

### Actions

Every successful reply contains `"ok": true` and `"code": 0`. Fields are added per action.

| `action` | Request fields | Reply fields added | Effect | Source |
|---|---|---|---|---|
| `get_status` | none | `mode`, `debug_hud`, `hardware_stats`, the gesture settings (see below), `mirror_dim`, `mirror_dim_floor_percent`, the keyboard timings, `gleipnir_ribbon`, `gleipnir_available`, `bottom_dimmed`, `cursor_stay_visible`, `cursor_hide_delay_ms`, `cursor_stay_visible_active`, `pen_mode` | reads state | `bin/thor_app.py:938-949` |
| `get_debug` | `reset` (optional boolean) | `telemetry`, `state`, `coords`, `touch_device`, `active_fingers`, `digitizer_contacts`, `engine_contacts`, `last_key`, `draws`, `draw_ms_avg`, `draw_ms_max`, `frame_lag_ms_max`, `hardware_stats`, gesture settings | counters are cleared only if `reset` is true | `bin/thor_app.py:950-966` |
| `set_mode` | `mode`: `trackpad`, `split`, `keyboard` or `settings` | none | other values are ignored and the reply is still `ok` | `bin/thor_app.py:967-968`, `:301-302` |
| `set_settings` | flat keys, for example `sensitivity`, `mirror_dim`, `keyboard_repeat_delay_ms`, `gleipnir_ribbon`, `debug_hud` | none | keys are applied and saved; a nested `{"settings": {...}}` is ignored | `bin/thor_app.py:969-978`, `bin/ipc_util.py:88-100` |
| `set_volume` | `volume`, default 50 | `vol_pct` | clamped 0 to 100, written asynchronously | `bin/thor_app.py:979-982`, `bin/system_stats.py:229-233` |
| `toggle_mute` | none | `vol_muted` | flips the displayed state and writes it | `bin/thor_app.py:983-986`, `bin/system_stats.py:395-401` |
| `set_top_brightness` | `brightness`, default 100 | `top_bright_pct` | clamped 1 to 100, written asynchronously | `bin/thor_app.py:987-990`, `bin/system_stats.py:235-239` |
| `set_bottom_brightness` | `brightness`, default 100 | `bot_bright_pct` | clamped 1 to 100, written asynchronously; also saved to Armada's level | `bin/thor_app.py:991-994`, `bin/system_stats.py:241-245` |
| `set_pen_mode` | `mode`: `off`, `pen` or `pen_plus` (other values become `off`) | `pen_mode` and the three `cursor_*` fields | writes or removes the Pen + override | `bin/thor_app.py:995-997`, `:250-266` |
| `wake` | none | none | taps F24 on the virtual keyboard, pokes the idle tracker and the burn-in timer | `bin/thor_app.py:998-1003` |
| `toggle_hud` | none | `debug_hud` | flips the HUD and saves | `bin/thor_app.py:1004-1008` |
| `run_diagnostics` | none | `diagnostics` | `run_self_diagnostics()` | `bin/thor_app.py:1009-1010` |
| `quit` | none | none | closes the window, which runs `cleanup()` | `bin/thor_app.py:1011-1012` |

Gesture settings returned by `get_status` and `get_debug` (`bin/engine.py:460-473`): `sensitivity`, `glide`, `friction`,
`scroll_speed`, `tap_to_click`, `long_press_right_click`, `long_press_delay_ms`, `two_finger_right_click`,
`three_finger_middle_click`, `three_finger_swipe_enabled`, `stylus_mode`.

`set_settings` only checks the types it needs. Values are clamped by `TouchGestureProcessor.set_settings` (`bin/engine.py:426-454`)
and by `keyboard_settings.clamp` (`bin/keyboard_settings.py:18-24`).

### Decky backend methods

`main.py` `Plugin` exposes these to the panel (`dist/index.js` calls them through `call`):

| Method | Arguments | Behaviour | Source |
|---|---|---|---|
| `get_status` | none | returns `enabled`, the settings, `telemetry`, `state`, `hardware_stats`, `pen_mode`, `gleipnir_available`, and `code` (0 when running, 4 `DBG-004` when stopped) | `main.py` `get_status` |
| `set_enabled` | `enabled` (bool) | saves `enabled`, starts or stops the service, polls up to 3 s for the socket to agree, then returns `get_status` | `main.py` `set_enabled` |
| `set_mode` | `mode` | saves `mode` and sends `set_mode` if running | `main.py` `set_mode` |
| `set_settings` | `settings` (dict) or keyword arguments | merges into the config and sends `set_settings` if running | `main.py` `set_settings` |
| `set_volume` | `volume` | sends `set_volume` if running, else `{"ok": false}` | `main.py` `set_volume` |
| `toggle_mute` | none | sends `toggle_mute` if running | `main.py` `toggle_mute` |
| `set_brightness` | `target` (`top` or other for bottom), `percent` | sends `set_top_brightness` or `set_bottom_brightness` | `main.py` `set_brightness` |
| `toggle_hud` | none | sends `toggle_hud` if running; otherwise flips `debug_hud` in the file | `main.py` `toggle_hud` |
| `set_pen_mode` | `mode` | sends `set_pen_mode` if running | `main.py` `set_pen_mode` |
| `run_diagnostics` | none | returns `run_self_diagnostics()` | `main.py` `run_diagnostics` |

The panel polls `get_status` every 2 s (`dist/index.js:139`). It merges the reply so that a value the user just changed
is held for 3 s (`dist/index.js:29`, `:34-49`).
