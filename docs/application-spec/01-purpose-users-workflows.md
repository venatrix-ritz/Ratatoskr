# 01 - Purpose, users and workflows

## Purpose
Ratatoskr makes the AYN Thor's bottom screen usable as an input surface while a game runs on the top screen
(README.md, "Ratatoskr" section). It does this in four ways:

1. **Trackpad**: the bottom screen is a touchpad that moves the pointer of the top-screen game.
2. **Keyboard**: a thumb keyboard that sends real Linux key codes (`bin/keyboard_layout.py`, `bin/thor_app.py`).
3. **Split**: trackpad above, keyboard below (`SPLIT_Y = 500.0`, `bin/thor_app.py:82`).
4. **Quick Controls**: sliders for volume and both backlights, a live status ribbon, and optionally a battery and
   Gleipnir card (`bin/thor_app.py` `_draw_quick_settings`, `_draw_battery_card`).

The output is a pair of virtual uinput devices: "Thor Virtual Trackpad" (`bin/engine.py:159`) and "Thor Virtual Keyboard"
(`bin/engine.py:179`). The game sees them as ordinary mouse and keyboard hardware.

## Scope

### In scope
- Grabbing the bottom touchscreen exclusively (`EVIOCGRAB`, `bin/thor_app.py:516`) and reading its multitouch frames.
- Gesture interpretation: pointer motion, taps, long press, two- and three-finger gestures, momentum glide, Pen mode
  (`bin/engine.py`).
- Drawing the bottom-screen UI with GTK and cairo (`bin/thor_app.py`, `bin/key_render.py`, `bin/theme.py`).
- Quick-control writes to volume (PipeWire through `wpctl`) and to the two backlights (`bin/system_stats.py`).
- The opt-in bottom-screen dim that follows the top panel's idle dim (`bin/dim_mirror.py`, `bin/top_follower.py`).
- Burn-in measures: orbit shift, fading hint, idle veil (`bin/burn_in.py`).
- A read-only status view of Gleipnir, the separate charge limiter (`bin/gleipnir_view.py`).
- A UNIX-socket IPC used by the Decky backend and the manager (`bin/thor_app.py` `_start_ipc_server`).
- Diagnostic codes `DBG-nnn` and a log file (`debug_codes.py`).
- Installing the driver and plugin onto a Thor (`scripts/deploy.sh`, `scripts/build-release.py`,
  `scripts/deploy-decky-panel.sh`).

### Out of scope (as the code and docs show it)
- **Charge limiting.** That is Gleipnir, a separate project (`bin/gleipnir_view.py` header: "Read-only"). Ratatoskr only
  reads its status.
- **Game streaming.** `scripts/artemis-wrapper.sh` and `scripts/update-artemis-config.py` configure the Artemis streaming
  client. `docs/development.md` states they are "not part of Ratatoskr's function".
- **Armada OS itself**: the bottom-screen session, backlight ownership and the Steam dim are Armada's behaviour, which
  Ratatoskr works around or depends on (see [03-hardware-targets.md](03-hardware-targets.md)).
- **Sleep handling.** `bin/dim_mirror.py:14-17` says sleep is not handled there; the docs say it is untested
  (`docs/dim-mirror.md`, "Sleep").
- **Other devices.** Nothing in the repo targets a device other than the AYN Thor on Armada OS (`README.md`, "Honest status").

### Naming
The project was called Touch Master until 2026-10-07 (`CHANGELOG.md`, top). Display names are Ratatoskr. Runtime names
are unchanged on purpose so existing installs keep working (`docs/installation.md`): the service is `touch-master.service`,
the socket is `thor-input.sock`, the config folder is `~/.config/thor-input`, and the package name in `package.json` is
`thor-input`.

### Licence and credit
MIT (`LICENSE`, `package.json`). `CREDITS.md` credits Project Barry (GPL-2.0), Armada OS, Decky Loader and the AynThor
research repo, and records a licence check dated 2026-10-07 that kept MIT.

## Users

| User | What they do | Evidence |
|---|---|---|
| The owner-operator (Ven) | Installs from the repo with `deploy.sh`, plays on the Thor, tunes settings in the Decky panel, reads logs | `README.md`, `CREDITS.md` ("every decision about what goes in") |
| A Thor owner installing from the release zip | Uses the Armada Store zip; `main.py` copies the driver into the home folder | `scripts/build-release.py`, `docs/installation.md` "Install from a release zip" |
| A developer running the unit tests | Runs the Python and Node tests without a device, or device-only tests on the Thor | `docs/development.md`, `tests/` |

The install path assumes the Armada user `armada` (UID 1000). `main.py:25` hard-codes `/run/user/1000/thor-input.sock`
and `main.py:24` defaults `HOME` to `/var/home/armada`. **Unverified** whether any other user or UID is intended to work.

## Workflows

Each workflow lists the steps as the code performs them. Device-level steps are described from code, not run.

### W-01 Install onto a Thor from a PC
1. Clone the repo and run `./scripts/deploy.sh <host>`, or set `THOR_HOST` or `local/thor.env` (`scripts/deploy.sh:5-14`).
2. The script copies `debug_codes.py`, `bin/*.py`, the desktop entries, the icon, the user unit and the Decky files
   (`scripts/deploy.sh:21-68`).
3. It reloads the user systemd, restarts `plugin_loader.service` and restarts `touch-master.service`
   (`scripts/deploy.sh:70-71`).
4. In Steam, open Decky, then Ratatoskr, and check that "Enable Bottom Screen" is on (`docs/installation.md`, "Verify").

### W-02 Install from the release zip
`python scripts/build-release.py` writes `release/Ratatoskr.zip` with one top-level `thor-input/` folder
(`scripts/build-release.py:2-9`). On first load Decky runs `main.py` `Plugin._main`, which calls `_sync_driver`
(`main.py:76`; `_main` starts at `main.py:194` and calls it at `main.py:197`). That copies the shipped driver files into the home folder when they are missing or differ,
reloads user systemd if the unit changed, and starts or restarts the service.

### W-03 Turn the bottom screen on or off
- **Decky**: "Enable Bottom Screen" calls `set_enabled` (`dist/index.js:314-320`). Enabling runs
  `_start_service` (disable `armada-bottom-screen.service`, enable and start `touch-master.service`,
  `main.py:240-243`). Disabling runs `_stop_service` (stop and disable Ratatoskr, re-enable and start Armada's session,
  `main.py:245-249`).
- **Manager**: `touch_master_manager.py --start`, `--stop`, `--toggle` (`bin/touch_master_manager.py:431-442`).
- **Tray menu**: "Stop Ratatoskr" starts the manager's `--stop` in a transient `systemd-run --user` unit
  (`bin/thor_app.py:390-401`, `bin/tray_actions.py`), so the hand-back still runs after the service stops.

### W-04 Choose an input mode
Modes are `trackpad`, `split`, `keyboard` and `settings` (`bin/thor_app.py:301`, which also accepts no others).
They can be chosen from the header buttons (Trackpad, Split, Keyboard, Quick Controls), the status ribbon (a tap toggles
Quick Controls, `bin/thor_app.py:731-732`), the Decky dropdown (`dist/index.js:298-303`), the tray menu, or
`touch_master_manager.py --mode trackpad|keyboard|settings` (the CLI has no `split` choice, `bin/touch_master_manager.py:428`).

### W-05 Use the trackpad
One finger moves the pointer. A short tap clicks. Two fingers scroll. Two-finger tap right-clicks. Holding one finger
still right-clicks if long-press is on. Three-finger tap middle-clicks and three-finger swipes send keys, both off by
default. A flick glides. The full table is in [02-features.md](02-features.md#trackpad).

### W-06 Type on the keyboard
Keys send a key-down and key-up pair at once on a tap (`bin/thor_app.py` `_keyboard_down` calls `tap_key`). A held key
repeats after `keyboard_repeat_delay_ms` at `keyboard_repeat_interval_ms` (`bin/thor_app.py:403-419`). Shift, Ctrl, Alt
and Win are one-shot on a tap, lock on a quick second tap, and act while held with another finger
(`bin/modifiers.py:1-16`).

### W-07 Use Pen mode
Tap the orange **Pen** header button (or use the Decky "Pen mode" toggle). The button cycles Off, Pen, Pen +, Off
(`bin/pen_mode.py` `cycle`). In Pen mode one touch moves the pointer, two taps close together click, a hold right-clicks,
and drags along the right and bottom edges scroll. Pen + also asks Game Mode to keep the pointer visible (W-12).

### W-08 Adjust settings and Quick Controls
Quick Controls shows three sliders (volume with mute, top brightness, bottom brightness), the ribbon (battery, CPU, GPU,
RAM, volume, brightness), and four buttons: Tap Click on/off, Right-click mode (2-finger or press-hold), Glass HUD,
and Back to Trackpad (`bin/thor_app.py` `_draw_quick_settings`, `_handle_settings_touch`). The Decky panel exposes the
same settings plus pointer tuning, keyboard timings and Pen controls (`dist/index.js`).

### W-09 Hide the UI and bring it back
The **Hide** header button blanks everything except an **Open** button in the same corner. While hidden, the whole
screen is a trackpad (`bin/thor_app.py` `_owner_at`, lines 671-687). A touch within `OPEN_HIT_PAD = 24` px of the Open
button restores the UI (`bin/thor_app.py:91-92`, `:729-730`). Hidden state is not saved (`bin/thor_app.py:121`).

### W-10 Dim the bottom screen with the top (opt-in)
Turn on "Dim bottom screen with the top" in the Decky panel, or set `mirror_dim: true`. The driver then watches the top
backlight and fades the bottom backlight down when Steam's idle ramp starts, and restores it when the top comes back or
input arrives (`bin/dim_mirror.py`, `bin/top_follower.py`). Needs write access to both backlights, see W-14 and
[05-configuration-requirements.md](05-configuration-requirements.md#backlight-write-access).

### W-11 Wake the screens
`touch_master_manager.py --wake` or the IPC `wake` action taps F24 on the virtual keyboard
(`bin/thor_app.py:998-1003`). The docs say Steam treats it as input and restores a dimmed top screen (`docs/usage.md`,
"Waking the screens"). That is the author's device observation, **unverified** in this review.

### W-12 Keep the pointer visible in Game Mode (Pen +)
Pen + writes `~/.config/environment.d/50-ratatoskr-cursor.conf` with `HIDE_CURSOR_DELAY_MS=3600000`
(`bin/session_cursor.py:198-200`, `:217-234`). Game Mode reads it only when it next starts, so a reboot is the reliable
way to apply it (`bin/session_cursor.py:1-10`, `docs/usage.md`). Until then the driver nudges the pointer before scrolls
and presses (see [02-features.md](02-features.md#pointer-visibility)).

### W-13 Run self-test diagnostics
The Decky panel's "Run Self-Test Diagnostics" calls `run_diagnostics`, which returns `run_self_diagnostics()`
(`main.py` `run_diagnostics`, `debug_codes.py:140-197`). It checks `/dev/uinput` write access, the `bottom_touchscreen`
node, the IPC socket path and the existence of `/run/user/<uid>/armada-bottom-env`. It does not change anything.

### W-14 One-time backlight permission (optional)
Armada keeps both backlights root-only. Ratatoskr writes with `sudo -n tee <file>` when a direct write is denied
(`bin/system_stats.py:68-76`). Without passwordless sudo for those files the brightness sliders and the dim feature log
`DBG-701`. `docs/installation.md` describes an optional narrow sudoers file. See
[05-configuration-requirements.md](05-configuration-requirements.md#backlight-write-access) for what that file does and
does not allow.

### W-15 Read the status ribbon and Gleipnir card (optional)
With `gleipnir_ribbon` on, the battery cell shows Gleipnir's state (held, charging toward its cap, off or unverified) and
Quick Controls shows a Battery and Gleipnir card (`bin/gleipnir_view.py`, `bin/thor_app.py:1161-1164`, `:1487`).
The view runs `gleipnir --status --json`, reads `systemctl is-active gleipnir` and the Gleipnir journal, and never writes
(`bin/gleipnir_view.py:4-6`).

### W-16 Read logs
Each component writes `[time] [DBG-nnn] [context] description - details` to stdout (the journal) and to
`/tmp/thor-input-debug.log` (`debug_codes.py:120-137`). Start with `journalctl --user -u touch-master.service`
(`docs/troubleshooting.md`). The code registry is `debug_codes.py` and the README table is a summary of it.

## Entry points

| Surface | Who calls it | Transport | Reference |
|---|---|---|---|
| Header, ribbon and Quick Controls on the glass | the user's fingers | evdev touch frames | [02-features.md](02-features.md) |
| Decky panel | Decky Loader, through `main.py` | `systemctl --user`, and the IPC socket | [04-interfaces.md](04-interfaces.md#decky-backend-methods) |
| Standalone manager window and CLI | the user, a script, a desktop entry | `systemctl --user`, the IPC socket | [04-interfaces.md](04-interfaces.md#cli-reference) |
| Tray menu (AppIndicator, if available) | the user | GTK menu in the driver (`bin/thor_app.py:333-376`) | W-03, W-04 |
| Desktop entries | the user | `touch_master_manager.py` actions | `touch-master.desktop`, `touch-master-stop.desktop` |
