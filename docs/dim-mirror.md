# Dim the bottom screen with the top (opt-in)

**Status: the dim write path is verified on a Thor (2026-10-08); its timing against Steam's own dim is still being observed.** The first version dimmed for a moment and was undone by Armada (see below). That is fixed and checked on the hardware: the dim holds, the restore works, and a dim left by a crash is recovered at the next start. Compare the `DBG-610` log lines with the top panel while you use it.

## The problem
Steam's idle dim only touches the top panel. Armada deliberately steers every Steam backlight write to the primary panel (`ae96000.dsi.0` on the Thor), so the bottom panel (`ae94000.dsi.0`) keeps its brightness. [src: Armada `system_files/usr/bin/steamos-polkit-helpers/steamos-priv-write`, `devices/ayn-thor.conf`]

The dim delay is a Steam setting. On the surveyed Thor `config.vdf` held `IdleBacklightDimBatterySeconds` = 300 and `IdleBacklightDimACSeconds` = 0 (never), and the journal (`armada-steamos-priv-write` tag) showed a ramp of about 265 writes from 254 down to 7 starting exactly 300 s after the previous wake. [observed 2026-10-07, details in the AynThor repo's `docs/armada/dual-screen-dimming.md`]

## What the mirror does
1. Reads the delay for the current power source from `~/.local/share/Steam/config/config.vdf` (battery, or charging/full; 0 means never) and re-reads it every 10 s.
2. Tracks idle time from input on every readable input device: buttons, sticks past about 25 % deflection, triggers, hat, mouse, the top touchscreen. The grabbed bottom touchscreen is reported by the app itself. Haptics, jack, lid and power-key devices and Ratatoskr's own virtual devices are ignored.
3. After the delay, fades the bottom backlight to `mirror_dim_floor_percent` (default 3 %, about Steam's observed floor of 7/255). On the next input it restores the level it had.
4. Writes the dimmed level to Armada's saved bottom-screen level (`/etc/armada/bottom-screen-brightness`) as well, because Armada's root service (`armada-control`) re-applies that saved level every 2 seconds whenever the backlight differs from it. Before 2026-10-08 the mirror only changed the backlight, and Armada put it back within about 1.5 seconds (measured on the Thor). The pre-dim level is kept in `~/.local/state/thor-input/dim-restore.json` until it has been restored, so a crash, kill or reboot while dimmed is repaired at the next start instead of leaving the screen dim.
5. If the backlight is not writable it logs `DBG-701` and retries after a minute.
6. Logs `DBG-610` lines for each dim and restore, **and every time the top backlight really drops or rises**, with the idle time at that moment and Steam's delay, so you can check the timer against Steam.

## Turn it on
Decky panel, **Screens**, "Dim bottom screen with the top"; or `"mirror_dim": true` in `config.json`. It needs permission to write the bottom backlight; see the sudo note in [installation.md](installation.md).

## Sleep
Not handled here. Armada's `fake-suspend` sends `drm_sleep_internal_screen` to every gamescope instance in the session and falls back to `bl_power` on every backlight, which should cover the bottom panel. [src: Armada `system_files/usr/libexec/armada/fake-suspend`, `display_off`] Not yet confirmed by a test on the Thor.

## Limits
- The idle source is Ratatoskr's own, not Steam's, so the two timers can drift apart if the input they see differs.
- Gyro/IMU motion is not an input device here and does not count as activity.
- A game that holds a button or stick for longer than the delay counts as idle after the press, as the key events stop.

Source and tests: `bin/dim_mirror.py`, `tests/test_dim_mirror.py`.
