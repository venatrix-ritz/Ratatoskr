# 06 - Design decisions and open work

Each decision gives the reason the repo records. Where the repo records no rejected alternative, the entry says so; it does
not invent one. Evidence labelled "observed" is an author's device observation cited from `CHANGELOG.md` or `docs/`, not
reproduced here.

## Decisions

| ID | Decision | Reason recorded in the repo | Alternative recorded | Source |
|---|---|---|---|---|
| D-01 | Grab the bottom touchscreen exclusively | A second reader would also receive the touches (`docs/troubleshooting.md`, `DBG-203` row). The unit declares `Conflicts=armada-bottom-screen.service`, so the stock bottom session is stopped while Ratatoskr runs | none recorded | `systemd/touch-master.service:5`, `bin/thor_app.py:515-517`, `docs/troubleshooting.md` (`DBG-203`) |
| D-02 | Create two uinput devices for pointer and keyboard | The docs describe the top-screen game receiving a virtual mouse and keyboard (`docs/architecture.md`, diagram); the keys are real Linux key codes | none recorded | `bin/engine.py:23-42`, `:143-185`, `bin/keyboard_layout.py:4-66` |
| D-03 | The dim follows the top backlight, not Steam's configuration and not an input tracker | Steam's delay read from `config.vdf` and the tracker's own clock ran up to 55 s apart from Steam's; the physical controller was unreadable. The "AC fallback" was withdrawn after it failed to explain an observed hour | reading Steam's delay and tracking input (the first version, withdrawn) | `CHANGELOG.md` (Unreleased, "Changed: the bottom screen now follows"), `docs/dim-mirror.md` ("Why not Steam's delay and input") |
| D-04 | Mirror the top's fall with a slow-fall rule that ignores a single large drop | Steam blanks the top before a suspend, and a one-second drop must not start a fade that finishes after the wake (observed) | the fade on any fall (recorded as a bug, fixed) | `bin/top_follower.py:178-180`, `CHANGELOG.md` (Unreleased, "a second cause of the dip on wake") |
| D-05 | Use the top backlight's clock `CLOCK_BOOTTIME` for the dim | `CLOCK_MONOTONIC` stops during a suspend, so the gap looked like a fall (observed) | `CLOCK_MONOTONIC` (the earlier code) | `bin/dim_mirror.py:45-48`, `CHANGELOG.md` |
| D-06 | Write the dim level to Armada's saved file as well, on the last step | Armada's root service re-applies the saved level every 2 s, which would undo the dim (observed) | none recorded | `bin/dim_mirror.py:49-50`, `:337-347`, `CHANGELOG.md` |
| D-07 | Record the pre-dim level in a file until it is restored | A crash or restart during a dim would otherwise leave the bottom dim | none recorded | `bin/dim_mirror.py:280-311`, `docs/troubleshooting.md` |
| D-08 | Pen + uses a session environment override, not a runtime setter | gamescope reads `--hide-cursor-delay` only at launch; there is no run-time setter | keeping only the nudges (still in place as a fallback) | `bin/session_cursor.py:1-10` (author's read of `gamescope-session-plus`, 2026-10-08) |
| D-09 | Nudge the pointer by one pixel out and back before a scroll or press after 2 s of stillness | Game Mode hides the pointer after 3 s; wheel events and presses do not un-hide it. The fix follows barry-launcher's `inputd` | Pen + (the override) for the trackpad too | `bin/engine.py:77-84`, `CHANGELOG.md` (scrolling fix), `CREDITS.md` |
| D-10 | Tap limits: 0.25 s and 12 px per finger | The earlier values (0.38 s, 36 px) let quick cursor nudges click | the earlier values | `bin/engine.py:70-71`, `CHANGELOG.md` ("quick cursor nudges no longer click") |
| D-11 | Pen mode clicks only on a double tap; a single tap never clicks | The pen's landing often registered as a short tap a fraction of a second before the stroke (observed) | single tap click | `bin/engine.py:520-534`, `:106-107`, `CHANGELOG.md` (Pen entry) |
| D-12 | Ignore four or more fingers until all lift or go quiet | the controller sometimes loses a lift, so a ghost contact stays down and scrolls or clicks (observed) | handling the extra fingers | `bin/engine.py:85-95`, `:589-597`, `CHANGELOG.md` |
| D-13 | Drop a contact silent for 1.5 s | a lost lift otherwise holds the pointer until the controller lets go | none recorded | `bin/engine.py:85-89`, `:497-511` |
| D-14 | Read the kernel's slot table after `SYN_DROPPED` | fingers already down would otherwise stay invisible until lift | none recorded | `bin/thor_app.py:622-649`, `bin/touch_frames.py:72-84` |
| D-15 | One writer thread per hardware control, keeping only the newest value | each `sudo tee` write took about 25 ms and the bottom slider needed two per touch (observed) | writing on the touch thread (the earlier code) | `bin/system_stats.py:87-136`, `CHANGELOG.md` ("the Quick Controls sliders lagged") |
| D-16 | Sample the hardware on a thread once a second; drawing reads a cache | a sample took about 29 ms (observed); drawing must not wait | sampling on demand | `bin/system_stats.py:204-219`, `docs/architecture.md` |
| D-17 | Config writes are atomic and merge the disk copy | a crash mid-write reset every setting to defaults; the driver's rewrite dropped `enabled` (observed) | in-place writes; writing only the driver's keys | `bin/atomic_json.py`, `bin/thor_app.py:225-248`, `CHANGELOG.md` |
| D-18 | One IPC request per connection, JSON, flat settings keys | the manager's nested settings were ignored by the driver, and unknown actions returned `ok` (observed and fixed) | nested `{"settings": {...}}`; silent `ok` for unknown actions | `bin/ipc_util.py:88-100`, `bin/thor_app.py:1013-1014`, `CHANGELOG.md` |
| D-19 | Replies are read to end of file, with a 2 s limit | a single `recv(4096)` could cut a reply | a fixed-size read | `bin/ipc_util.py:46-64`, `CHANGELOG.md` |
| D-20 | The driver exits on device loss and systemd restarts it | spinning on a dead descriptor would use a core | in-process re-open | `bin/thor_app.py:555-563` (comment) |
| D-21 | Tray Stop runs the manager's stop in a transient unit | stopping the service kills its children, including the hand-back steps | running them in-process | `bin/tray_actions.py:3-8`, `CHANGELOG.md` |
| D-22 | Release zip: the driver ships inside the plugin and `main.py` copies it | the Armada Store installs only the plugin folder | a separate installer | `scripts/build-release.py`, `main.py:60-106`, `CHANGELOG.md` |
| D-23 | Pure black, no fills, a 1.5 px orbit, a fading hint, and an idle veil | AMOLED pixels draw power when lit and can burn in | a lit surface | `bin/theme.py`, `bin/burn_in.py`, `CHANGELOG.md` (AMOLED entry) |
| D-24 | Gleipnir is read-only in Ratatoskr | Gleipnir is a separate project with its own control; Ratatoskr shows status only | a control | `bin/gleipnir_view.py:4-6` |
| D-25 | The Decky panel is plain JavaScript with no build step | Decky provides its globals; the file is shipped as is | a bundled build | `dist/index.js:1-16`, `docs/development.md` |
| D-26 | Runtime names kept after the rename | existing installs keep working | renaming the service and socket | `docs/installation.md`, `README.md` |
| D-27 | Pinch zoom and drag lock removed | never implemented; the switches did nothing and had been causing stuck keys | finish them | `CHANGELOG.md` ("Removed") |
| D-28 | Hide is not saved | a restart shows the UI, so the screen cannot be left blank by accident | saving the state | `bin/thor_app.py:121`, `CHANGELOG.md` |
| D-29 | MIT licence, with Barry credited as inspiration | a licence check of both code bases on 2026-10-07 found one identical line and no matching momentum code | GPL-2.0 | `CREDITS.md` |
| D-30 | Keyboard tap sends press, waits 20 ms, sends release, on the reader thread | a key tap is a short fixed hold | a non-blocking tap | `bin/engine.py:296-300`, `bin/thor_app.py:760`. **Design observation, not a recorded decision** |

## Open work

Each item names the place it comes from. "Open" means the repo records it as open or the code shows a gap. No item here
is a commitment.

| ID | Item | Where it comes from | Related spec entry |
|---|---|---|---|
| R-01 | Define `ERR_SERVICE_START` and `ERR_SERVICE_STOP`, or use codes that exist | undefined in `debug_codes.py`, used in `main.py:199`, `:235`, `bin/thor_app.py:488` | application spec, defect K-01 |
| R-02 | Decide the sudoers rule for the saved-level file: add it to the rule, or write it another way; then test the rule on the Thor | `systemd/touch-master-backlight.sudoers:7-8`, `bin/system_stats.py:422`; `docs/troubleshooting.md` (known issue 1) | application spec, K-02 |
| R-03 | Log slider backlight failures under `DBG-701`, and record top-panel write failures | `bin/system_stats.py` imports no logger; the docs say `DBG-701` shows for sliders | application spec, K-03 and mismatch 13 |
| R-04 | Log `DBG-702` on `wpctl` failure, or remove the doc claim | `ERR_PIPEWIRE_WPCTL` is defined and not emitted; `docs/troubleshooting.md` cites it | mismatch 13 |
| R-05 | Socket bind errors: catch and log `DBG-301` | `bin/thor_app.py:915-917`; `DBG-301` defined and never emitted | 05, error table |
| R-06 | Choose: a fallback to `/dev/input/event5`, or remove the doc sentence | `docs/architecture.md:35`; no fallback in code | mismatch 1 |
| R-07 | Make the deploy run the tests, or correct `docs/development.md` | `scripts/deploy.sh` has no test step | mismatch 2 |
| R-08 | Correct the dim wording in the panel, the manager and `docs/dim-mirror.md` step 3 (the restore on any input) | `dist/index.js:490-491`, `bin/touch_master_manager.py:230`, `bin/dim_mirror.py:402-403` | mismatches 5 and 6 |
| R-09 | Remove the claim that the dim reads Steam's `config.vdf` | `docs/configuration.md:34`; no code reads it | mismatch 3 |
| R-10 | Correct the Open-button distance (24 px is about 1.5 mm, not 2 cm) | `docs/usage.md:54`, `bin/thor_app.py:75-76`, `:92` | mismatch 4 |
| R-11 | Reconcile the sudoers file names | `docs/installation.md:45` and `systemd/touch-master-backlight.sudoers:6` | mismatch 7 |
| R-12 | Hard-coded UID 1000 in the Decky backend | `main.py:25` | application spec, K-06 |
| R-13 | Reserved code 521: remove the entry or update the README | `debug_codes.py:54`, `README.md` | application spec, K-05 |
| R-14 | Dangling references: `docs/hardware/device-observed.md` and `devcheck.sh` | `bin/gleipnir_view.py:174`, `tests/test_system_stats.py` | application spec, K-07, K-08 |
| R-15 | Burn-in orbit: the code is a Lissajous path (x at 1x, y at 1.5x), while the CHANGELOG says "circular" | `bin/burn_in.py:49-51`, `CHANGELOG.md` (AMOLED entry) | 03, burn-in |
| R-16 | Confirm sleep behaviour on the device, or document the gap | `docs/dim-mirror.md` ("Sleep", not yet confirmed) | application spec, limitation 4 |
| R-17 | Run the narrow sudo rule on the device | `docs/troubleshooting.md` (known issue 1) | application spec, 05 |
| R-18 | Pen + needs Game Mode to restart; the UI has no restart control | `bin/session_cursor.py:1-10`, `docs/usage.md` | application spec, W-12 |
| R-19 | The manager lacks Split, Pen, Hide and the keyboard timings | `bin/touch_master_manager.py:127-418` | application spec, F-110 |
| R-20 | Check the Armada version at run time, or document that other builds are untested | `README.md` | application spec, limitation 1 |
| R-21 | Decide whether the lost-update race in the config files matters | `bin/atomic_json.py` header | application spec, 05 |
| R-22 | Keyboard tap blocks the touch reader for 20 ms | `bin/engine.py:296-300`, `bin/thor_app.py:760` | 02, keyboard path |
| R-23 | Scroll events truncate sub-unit movement on each step | `bin/engine.py:695-696` | 02, two and three fingers |
