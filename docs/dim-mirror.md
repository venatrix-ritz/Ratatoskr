# Dim the bottom screen with the top (opt-in)

**Status: follows the top panel's backlight (2026-10-08). The first version guessed Steam's idle timing and was wrong; this one watches what Steam did. Verified by tests against Steam's real ramp; on-device timing is being observed.**

## The problem
Steam's idle dim only touches the top panel. Armada deliberately steers every Steam backlight write to the primary panel (`ae96000.dsi.0` on the Thor), so the bottom panel (`ae94000.dsi.0`) keeps its brightness. [src: Armada `system_files/usr/bin/steamos-polkit-helpers`]

Steam's idle ramp, read from the Thor's journal (`armada-steamos-priv-write` tag): about 260 writes over 30 s, value 254 down to 7 of 255 (panel value 4079 down to 112 of 4096). Sampled once a second on 2026-10-08 it falls 4079, 4015, 3838, 3614, 3324, 3003, 2666 ... 112. [observed 2026-10-08]

## What the mirror does
1. Reads the top backlight four times a second (`brightness` over `max_brightness`). It does not read Steam's delay and does not guess idle time from input.
2. When the top has been falling steadily for about 2.5 s, by at least 6 % of where it started, and is below 95 % of its recent peak, it fades the bottom backlight to `mirror_dim_floor_percent` (default 3 %). That is about 4 s after Steam's ramp starts.
3. It restores the bottom when the top comes back (back to 97 % of the peak, or up by 15 points), or when the top stops falling above 6 % for 4 s (a brightness-slider move ended, not an idle ramp), or when the bottom screen is touched. After a touch it will not dim again until the top has recovered.
4. Writes the dimmed level to Armada's saved bottom-screen level (`/etc/armada/bottom-screen-brightness`) as well, because Armada's root service (`armada-control`) re-applies that saved level every 2 seconds whenever the backlight differs from it.
5. If the backlight is not writable it logs `DBG-701` and retries after a minute.
6. If the service starts while the top is already at its floor (a restart during an idle dim), it treats that as a dim and follows it, assuming the normal level is full.
7. Logs a `DBG-610` line for each dim and restore, with the reason.

The logic is in `bin/top_follower.py` (pure, no I/O) and `DimMirror._run` in `bin/dim_mirror.py`.

## Why not Steam's delay and input
The first version read `IdleBacklightDim*Seconds` from `config.vdf` and tracked input itself. On the Thor its clock disagreed with Steam's, by up to 55 s with the bottom first (2026-10-08: bottom dimmed 19:37:33, top ramp began 19:38:28; again 19:47:50 against 19:48:00). One cause is certain: the physical controller `/dev/input/event7` ("AYN Odin2 Gamepad") is mode `c---------` root:root, so the tracker cannot open it ("Permission denied") and never counts its input, while Steam does. Whether other input is missed too is not established. [observed 2026-10-08]

A second guess, that Steam dims on the charger at the battery delay although the AC value reads 0, was written into the earlier version of this page and is withdrawn: with the charger in and AC at 0, nothing dimmed for an hour (18:03 to 19:03), and earlier dims on the charger are not explained by it.

## Turn it on
Decky panel, **Screens**, "Dim bottom screen with the top"; or `"mirror_dim": true` in `config.json`. It needs permission to write the bottom backlight; see the sudo note in [installation.md](installation.md).

## Sleep
Not handled here. Armada's `fake-suspend` sends `drm_sleep_internal_screen` to every gamescope instance in the session and falls back to `bl_power` on every backlight, which should cover the bottom panel. [src: Armada `system_files/usr/libexec/armada/fake-suspend`, `display_off`] Not yet confirmed by a test on the Thor.

## Limits
- The idle source is Ratatoskr's own, not Steam's, so the two timers can drift apart if the input they see differs.
- Gyro/IMU motion is not an input device here and does not count as activity.
- A game that holds a button or stick for longer than the delay counts as idle after the press, as the key events stop.

Source and tests: `bin/dim_mirror.py`, `tests/test_dim_mirror.py`.
