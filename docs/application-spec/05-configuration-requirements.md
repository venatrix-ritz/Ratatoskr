# 05 - Configuration and requirements

## Configuration file

| Property | Value | Source |
|---|---|---|
| Path | `~/.config/thor-input/config.json` (on the Thor: `/var/home/armada/.config/thor-input/config.json`) | `bin/thor_app.py:76`, `bin/touch_master_manager.py:29`, `main.py:26` |
| Override for the Decky backend | environment variable `RATATOSKR_HOME` replaces the home folder (tests only, `main.py:23`) | `main.py:23-24` |
| Format | one JSON object, UTF-8, indent 2, LF newlines | `bin/atomic_json.py:18-49`, `main.py:151-182` |
| Missing file | defaults apply; the file is not created until something is saved | `bin/thor_app.py:239-256`, `main.py:139-148` |
| Unknown keys | kept. The driver merges its keys into the file as it is on disk, so keys written by the plugin (`enabled`) and unknown keys survive (`bin/thor_app.py:258-283`) | `bin/thor_app.py:261-280` |
| Bad values | clamped to the range in the table, or replaced with the default if they are not numbers | `bin/engine.py:530-558`, `bin/keyboard_settings.py:18-24`, `bin/thor_app.py:305-310`, `:316-317` |
| Writes | atomic: temp file in the same folder, `fsync`, rename; owner and mode of the old file kept | `bin/atomic_json.py`, `main.py:151-182` |
| Concurrent writers | the driver, the Decky backend (root) and the manager each write the file. Each one reads, changes and writes the whole file, so a write by one can overwrite a key the other changed in between. The atomic write prevents torn files, not lost updates | `bin/atomic_json.py` header; `bin/thor_app.py:258-283` |

Driver read happens once at start (`bin/thor_app.py:208`). Panel and IPC changes are applied live and written back.

## Configuration keys

Defaults are the values in the driver (`bin/engine.py`, `bin/thor_app.py`, `bin/keyboard_settings.py`) and the Decky
backend (`main.py` `_default_config`). The standalone manager has the same defaults in `DEFAULT_CONFIG`
(`bin/touch_master_manager.py:33-55`).

| Key | Default | Range (driver clamp) | Meaning | Source |
|---|---|---|---|---|
| `enabled` | `true` | bool | the Decky backend starts the service when it loads only if this is true; written by the plugin and the manager | `main.py:_main`, `set_enabled`; `bin/touch_master_manager.py:94-119` |
| `mode` | `"trackpad"` | `trackpad`, `split`, `keyboard`, `settings` | the mode the driver starts in | `bin/thor_app.py:142`, `:244`, `:366-368` |
| `sensitivity` | `1.5` | 0.2 to 5.0 | pointer speed | `bin/engine.py:460`, `:530-531` |
| `glide` | `true` | bool | momentum after a flick | `bin/engine.py:461` |
| `friction` | `5` | 1 to 10 | glide decay (0.97 at 1, 0.74 at 10) | `bin/engine.py:462`, `:535-536`, `:925` |
| `scroll_speed` | `3` | 1 to 5 | two-finger scroll speed | `bin/engine.py:463`, `:536-537` |
| `tap_to_click` | `true` | bool | one-finger tap clicks | `bin/engine.py:464` |
| `two_finger_right_click` | `true` | bool | two-finger tap right-clicks; turning it on turns long press off | `bin/engine.py:467`, `:540-544` |
| `long_press_right_click` | `false` | bool | press and hold right-clicks; turning it on turns two-finger right click off | `bin/engine.py:465`, `:545-548` |
| `long_press_delay_ms` | `450` | 200 to 1200 (Decky slider 250 to 900) | hold time for the long press | `bin/engine.py:466`, `:549-550` |
| `three_finger_middle_click` | `false` | bool | three-finger tap middle-clicks | `bin/engine.py:468`, `:551-552` |
| `three_finger_swipe_enabled` | `false` | bool | three-finger swipes send Super, Escape, Alt+Tab | `bin/engine.py:469`, `:553-554` |
| `pen_mode` | `"off"` | `off`, `pen`, `pen_plus` | Pen mode; any other value is read as `off` | `bin/pen_mode.py:13-19`, `bin/thor_app.py:253` |
| `stylus_mode` | `false` | bool | the engine half of Pen mode. Written by the driver as part of the gesture settings; older files use only this key | `bin/engine.py:470`, `:555-558`; `bin/pen_mode.py:22-30` |
| `mirror_dim` | `false` | bool | dim the bottom screen with the top | `bin/thor_app.py:162`, `:303-306` |
| `mirror_dim_floor_percent` | `3` | 1 to 50 | the level the bottom dims to | `bin/thor_app.py:162`, `:306-310` |
| `keyboard_repeat_delay_ms` | `350` | 150 to 800 | hold time before a key repeats | `bin/keyboard_settings.py:9-16` |
| `keyboard_repeat_interval_ms` | `60` | 20 to 200 | time between repeats | `bin/keyboard_settings.py:9-16` |
| `keyboard_caps_window_ms` | `350` | 150 to 800 | second Shift tap within this time locks Caps Lock; also the window for the other modifiers | `bin/keyboard_settings.py:9-16`, `bin/thor_app.py:829` |
| `haptics` | `true` | bool | a short buzz for tap clicks, keys and on-screen buttons | `_apply_haptics_settings` `bin/thor_app.py`; `bin/haptics.py` |
| `ps_mode_auto` | `true` | bool | PS mode while Chiaki-NG has focus | `bin/thor_app.py:189`, `:326-331`, `:337-340` |
| `ps_touch_rotation` | `0` | 0, 90, 180, 270; anything else is 0 | turns PS mode's touch axes | `normalize_rotation` `bin/ps_pad.py:102`; `bin/thor_app.py:329-331` |
| `gleipnir_ribbon` | `false` | bool | show Gleipnir in the ribbon and in Quick Controls (read-only) | `bin/thor_app.py:166`, `:312-317` |

Keys the driver writes but the table does not list: `pen_mode` and `stylus_mode` above. `save_config` writes the full set
of driver keys every time (`bin/thor_app.py:270-280`).

### Notes on the defaults and ranges

- The panel's slider limits are narrower than the driver's clamp: sensitivity 0.5 to 3.5, long-press delay 250 to 900,
  keyboard timings within the same ranges as the driver (`src/index.tsx:370-376`, `:441-444`, `:511-539`).
- The manager's sensitivity slider is 0.2 to 3.0 (`bin/touch_master_manager.py:208`). Three different ranges exist.
- `keyboard_settings.LIMITS` and `_apply_mirror_settings` clamp the values on every change, so a value outside a range
  is accepted and then changed (`bin/keyboard_settings.py:23-24`, `bin/thor_app.py:308`).

## Paths and runtime files

| Path | What | Created or changed by | Source |
|---|---|---|---|
| `~/.config/thor-input/config.json` | settings | driver, Decky backend, manager | see above |
| `/run/user/<uid>/thor-input.sock` | IPC socket | driver (created on start, removed on exit) | `bin/thor_app.py:75`, `:1000-1018` |
| `/tmp/thor-input-debug.log` | log lines | every component | `debug_codes.py:9` |
| `~/.config/environment.d/50-ratatoskr-cursor.conf` | Pen + override, `HIDE_CURSOR_DELAY_MS=3600000` | driver when Pen + is on; removed when it is off | `bin/session_cursor.py:198-234` |
| `~/.local/state/thor-input/dim-restore.json` | pre-dim bottom level `{"pct", "ts"}` | driver while the bottom is dimmed | `bin/dim_mirror.py:52-53`, `:262-278` |
| `/etc/armada/bottom-screen-brightness` | Armada's saved bottom level (written by the driver on a brightness change and a dim) | driver through `sudo -n tee` when needed | `bin/system_stats.py:18`, `bin/dim_mirror.py:51` |
| `~/.local/share/thor-input/` | driver app: `bin/*.py`, `debug_codes.py` | `scripts/deploy.sh`, release zip | `docs/installation.md`, `main.py:27` |
| `~/.config/systemd/user/touch-master.service` | user unit | `scripts/deploy.sh`, release zip | `scripts/deploy.sh:46-50`, `main.py:76-106` |
| `~/.local/share/applications/touch-master.desktop`, `touch-master-stop.desktop` | launcher entries | `scripts/deploy.sh`, release zip | `scripts/deploy.sh:33-44` |
| `~/.local/share/icons/hicolor/scalable/apps/touch-master.svg` | icon | `scripts/deploy.sh`, release zip | `scripts/deploy.sh:38` |
| `/home/armada/homebrew/plugins/thor-input/` | Decky plugin folder (root-owned) | `scripts/deploy.sh`, `scripts/deploy-decky-panel.sh` | `scripts/deploy.sh:15`, `scripts/deploy-decky-panel.sh:16` |
| `/etc/sudoers.d/92-ratatoskr-backlight` (or as named in the file's comment) | optional narrow sudo rule | the user, by hand | `docs/installation.md:43-46`, `systemd/touch-master-backlight.sudoers:5-6` |
| `/usr/bin/armada-run-bottom` | wrapper the service runs the driver through | Armada | `systemd/touch-master.service:10` |

Hard-coded device paths in the code: `/var/home/armada` (`main.py:24`), `/run/user/1000` (`main.py:25`), the Decky plugin
folder, and the two backlight paths (`bin/system_stats.py:16-17`, `bin/dim_mirror.py:33`).

## Backlight write access

The driver writes backlight files in two ways. `_write_str` writes the file directly and, if that is denied
(`PermissionError`), runs `sudo -n tee <file>` (`bin/system_stats.py:68-76`). `_write_via_sudo` times out after
2 s and reads the value back to see whether it was written (`bin/system_stats.py:43-65`).

Files the driver writes:

| File | Written when | Covered by `systemd/touch-master-backlight.sudoers`? |
|---|---|---|
| `/sys/class/backlight/ae94000.dsi.0/brightness` (bottom) | every bottom brightness change and dim step | yes |
| `/sys/class/backlight/ae96000.dsi.0/brightness` (top) | every top brightness change | yes |
| `/etc/armada/bottom-screen-brightness` | each bottom brightness change with `persist` (the default), and the last dim step, and each restore | **no** |

The rule file allows `tee` only on the two `brightness` files (`systemd/touch-master-backlight.sudoers:7-8`). Because
`set_bottom_brightness` defaults to `persist=True` (`bin/system_stats.py:415`), a bottom slider change makes a second
sudo write to the saved file. Under only the narrow rule that second write is refused, so the function reports failure
(`bin/system_stats.py:420-424`). The dim feature then logs `DBG-701` and retries. **Unverified** on a device: this is a
reading of the code against the rule file. The docs call the narrow rule "untested" (`docs/troubleshooting.md`, Known issues).

## Install requirements

| Requirement | Detail | Source |
|---|---|---|
| Thor on Armada OS with Decky Loader | author's test: Armada `20261006.9c7dd3e`, kernel 7.2.6 | `README.md`, `docs/installation.md` |
| Python 3 with GTK 3 (PyGObject) and cairo on the Thor | already present on the author's Thor; Ratatoskr installs no packages | `docs/installation.md` "Requirements" |
| `/dev/uinput` writable by the driver's user | checked by the self-test | `debug_codes.py:151-156` |
| SSH key access and `sudo` on the Thor for the deploy | used by `deploy.sh` and `deploy-decky-panel.sh` | `scripts/deploy.sh`, `scripts/deploy-decky-panel.sh` |
| `wpctl` (PipeWire) for volume | used for the volume slider and reading the level | `bin/system_stats.py:312-332`, `:363-393` |
| `systemctl --user` with a running user session | used by the Decky backend and the manager | `main.py:216-240`, `bin/touch_master_manager.py:80-119` |
| Gleipnir (optional) | only for the status view | `bin/gleipnir_view.py` |
| AppIndicator3 (optional) | only for the tray menu | `bin/thor_app.py:27-32` |
| Git on the developer PC | for `build-release.py` (reads `HEAD`) and `deploy.sh` | `scripts/build-release.py:33-34` |

## Requirements

Requirements are numbered for reference. "Evidence" names the code that implements the requirement or the test that
exercises it. The tests that need a device are marked (device). "Status" is what this spec can say from the reading:
**implemented** means the code does it; it does not mean the behaviour was observed on hardware in this review.

### Functional

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| R-01 | The driver grabs the bottom touchscreen exclusively and retries every 5 s if it is missing or the grab fails | `bin/thor_app.py:580-605`, `:659-662` | implemented |
| R-02 | Touches are read as frames; kernel timestamps are used for timing; `SYN_DROPPED` is handled by reading the slots back | `bin/touch_frames.py`, `tests/test_touch_frames.py`, `bin/thor_app.py:665-724` | implemented; `test_touch_frames` runs anywhere |
| R-03 | One finger moves the pointer; a tap clicks; two fingers scroll; a two-finger tap right-clicks | `bin/engine.py:760-803`, `:891-903`; `tests/test_engine.py` | implemented |
| R-04 | Four or more fingers produce no output until they all lift or go quiet | `bin/engine.py:693-701`; `tests/test_engine.py` | implemented |
| R-05 | The keyboard sends Linux key codes; Shift, Ctrl, Alt, Win behave as in [02](02-features.md#keyboard) | `bin/modifiers.py`; `tests/test_modifiers.py`; `tests/test_keyboard_handlers.py` (device) | implemented |
| R-06 | Leaving Keyboard or Split releases latched and locked modifiers | `bin/thor_app.py:373-376`; `tests/test_keyboard_handlers.py` (device) | implemented |
| R-07 | Each mode can be chosen from the header, the panel, the manager, the tray and the CLI | `bin/thor_app.py:366-368`, `src/index.tsx:276-282`, `bin/touch_master_manager.py:415` | implemented; the manager and CLI cannot select Split |
| R-08 | Hide blanks the UI and Open restores it; the state is not saved | `bin/thor_app.py:384-394`, `:746-764`; `tests/test_keyboard_handlers.py` (device) | implemented |
| R-09 | Quick Controls writes are clamped and asynchronous; a slider keeps the finger that grabbed it | `bin/system_stats.py:87-136`, `bin/thor_app.py:981-994` | implemented |
| R-10 | The dim feature is off by default; it dims only on a steady fall of the top backlight and restores on a rise, on input, or when the fall stops | `bin/top_follower.py`, `bin/dim_mirror.py`; `tests/test_top_follower.py`, `tests/test_dim_mirror.py` | implemented; on-device timing unconfirmed (author's docs) |
| R-11 | The pre-dim level survives a crash and is restored on the next start | `bin/dim_mirror.py:280-311`; `tests/test_dim_mirror.py` | implemented |
| R-12 | IPC requests get a reply, or a `303` error; the driver does not wait more than 2 s for one request | `bin/ipc_util.py`, `bin/thor_app.py:1012-1127`; `tests/test_ipc_util.py` | implemented |
| R-13 | Config writes are atomic | `bin/atomic_json.py`; `tests/test_atomic_json.py` | implemented |
| R-14 | Stopping the service returns the bottom screen to Armada's session | `main.py:247-251`, `bin/touch_master_manager.py:107-119`, `bin/thor_app.py:459-470` | implemented; device behaviour per the CHANGELOG |
| R-15 | The service restarts after a crash or a lost touch device | `systemd/touch-master.service:11-12`, `bin/thor_app.py:635-637`, `:726-729` | implemented |
| R-16 | Pen mode: one pointer, double tap clicks, hold right-clicks, edge strips scroll; Pen + writes the override | `bin/engine.py:624-665`, `bin/session_cursor.py`, `bin/pen_mode.py`; `tests/test_pen_mode.py`, `tests/test_session_cursor.py` | implemented |
| R-17 | Gleipnir is read-only | `bin/gleipnir_view.py:4-6`; `tests/test_gleipnir_view.py` | implemented |
| R-18 | The self-test changes nothing | `debug_codes.py:144-201` | implemented |
| R-19 | The release zip replaces the driver only where the file is missing or different | `main.py:76-106`; `tests/test_driver_sync.py` (needs Linux) | implemented |

### Non-functional

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| N-01 | Pure black UI with no container fills, to keep unlit pixels off | `bin/theme.py:1-12`, `bin/thor_app.py:1326`, `:1385`, `:1429` | implemented |
| N-02 | Burn-in measures: orbit shift, fading hint, idle veil | `bin/burn_in.py`; `tests/test_burn_in.py` | implemented |
| N-03 | Drawing and IPC never wait for a hardware sample | `bin/system_stats.py:204-219`, `:181-196` | implemented |
| N-04 | Each component logs with a `DBG-nnn` code | `debug_codes.py:124-141` | implemented |
| N-05 | No device address or credential in tracked files; the deploy host comes from an argument or a git-ignored file | `scripts/deploy.sh:5-14`, `.gitignore` (`local/`) | implemented |
| N-06 | Linux-bound files are checked out with LF endings | `.gitattributes` | implemented |
| N-07 | The gesture engine, touch frame parser, modifiers, IPC helpers and dim logic import without GTK or a device | `bin/engine.py:15-18` (imports `fcntl` optionally), `bin/touch_frames.py`, `bin/modifiers.py`, `bin/ipc_util.py`, `bin/top_follower.py` | implemented |
| N-08 | The driver needs no build step; the panel is built with the Decky plugin template (`pnpm run build`). Until 2026-11-24 the panel had no build step either | `package.json`, `rollup.config.js`, `docs/development.md` | implemented |

## Requirements that are not met or not shown

| Gap | Detail | Reference |
|---|---|---|
| The narrow sudo rule does not cover the saved-level file | see "Backlight write access" | [06](06-testing-limitations-glossary.md#known-issues-and-open-defects) |
| No Armada version check | the driver does not read or check the Armada version; behaviour on other builds is unknown | `README.md` |
| Sleep | not handled by the dim feature; untested | `bin/dim_mirror.py:14-17` |
