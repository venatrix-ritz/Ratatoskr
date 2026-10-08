# Changelog

Dates are 2026. The project was called Touch Master until 2026-10-07. No version numbers have been cut yet.

## Unreleased
- **Fixed:** scrolling stopped working once the pointer had been still for 3 s, and again after 3 s of continuous scrolling. Game Mode's gamescope hides the pointer after `--hide-cursor-delay` (3000 ms on the Thor); pointer motion un-hides it, but wheel events neither un-hide it nor restart the timer, and a hidden pointer's wheel does not reach Steam (`refs/upstream/gamescope` `steamcompmgr.cpp` `checkSuspension`, `wlserver.cpp` `wlserver_mousemotion` / `wlserver_mousewheel`). A scroll or a button press sent after the pointer has been still for 2 s is now preceded by a net-zero one-pixel nudge (barry-launcher's `inputd` does this for scrolling). Button presses need it too: they do not restart the timer either, so tapping in one place, like a clicker game, lost the pointer after 3 s. `get_debug` telemetry counts them as `pointer_wakes`.
- **Fixed:** the Mute button lagged. It ran `wpctl set-mute ... toggle` on the touch thread and then read the state back from a cache, so the button could show the old state. It now flips the shown state at once and a writer sets the mute state explicitly (`1` or `0`), so quick repeated taps cannot get out of step.
- **Fixed:** the Quick Controls sliders lagged and lost the finger on fast drags. Measured on the Thor on 2026-10-08: each backlight write through `sudo tee` took about 25 ms and the bottom slider did two per touch event on the touch thread, and every write forced a fresh stats sample (about 29 ms) on the next redraw. Writes now go to one background writer per control that always writes the newest value, the requested value is drawn immediately, stats are sampled once a second on their own thread, and a slider keeps following the finger that grabbed it even when the finger leaves the bar. `get_debug` reports `draw_ms_avg`, `draw_ms_max` and `frame_lag_ms_max` (read once, then reset).
- **Fixed:** the trackpad no longer gets stuck after pressing several fingers. Observed on the Thor on 2026-10-08: the digitizer sometimes never reports a finger's lift when several fingers are down (the kernel slot table keeps the contact for minutes), and a later finger can land in that slot and arrive as movement of the old tracking id. Four or more fingers at once are now ignored until all of them lift or go quiet for 1.5 s; contacts silent for 1.5 s are dropped on every frame and idle tick; a dropped contact that moves again is adopted as a new touch; the reader parses frames with timestamps from the kernel (`bin/touch_frames.py`), logs `SYN_DROPPED` and digitizer-versus-engine contact counts, retries a failed grab every 5 s, and exits for a restart when the device disappears.
- **Fixed:** three-finger swipes no longer fire on a 2 px move. The swipe's start position was never set (it compared against the screen corner, so any move sent Escape), and it could not trigger a second time. The start is now taken when the third finger lands, and a new swipe is allowed after a finger lifts.
- **Fixed:** quick cursor nudges no longer click, and taps no longer nudge the cursor. A tap is now under 0.25 s and 12 px of travel per finger (was 0.38 s and 36 px), and the cursor is held still while a touch could still be a tap. The engine now imports on machines without `fcntl`, so its tests run anywhere.
- **Added:** a `wake` action (and `touch_master_manager.py --wake`) that taps F24 through the virtual keyboard. Steam treats it as input: it restored a dimmed top screen within a second on the Thor and restarts the idle and sleep timers.
- **Fixed:** a dim left by a crash or restart is now reliably put back. Found on the Thor: the first write after a restart can fail with "Invalid argument", and recovery gave up. Recovery is retried every 5 s until it works, a `sudo` write that times out is checked by reading the value back (the timeout is 2 s, was 0.4 s), and write failures now log the reason.
- **Fixed:** the dim mirror's idle tracker listed input devices once at start, so after a boot it saw 3 of 5 (the virtual controllers appear later) and controller input counted as idle. It now rescans every 5 s, picks up and drops devices as they come and go, and never exits when the list is empty.
- **Fixed:** the bottom-screen idle dim was undone by Armada within seconds, because `armada-control` re-applies its saved bottom level every 2 s. The dim now also sets that saved level, records the pre-dim level for crash recovery, retries a failed restore instead of forgetting it, and treats a charger on the USB supply as AC (a charge limit makes the battery report "Not charging").
- Opt-in **bottom-screen idle dim** that follows Steam's dim delay (`mirror_dim`, `mirror_dim_floor_percent`), with a Decky toggle, a manager switch, `DBG-610`, an optional narrow sudo rule for backlight writes, and unit tests.
- Renamed **Touch Master to Ratatoskr** (display names only; the `touch-master` / `thor-input` runtime names are unchanged).
- Made the repo public-ready: no device address in tracked files (`deploy.sh` takes the host from an argument, `THOR_HOST`, `THOR_ENV_FILE` or a git-ignored `local/thor.env`), LF line endings pinned, `deploy.sh` restarts the user service after copying.
- Full documentation under `docs/`; corrected the README, which still described the removed edge-scroll feature.

## 2026-10-06
- Fixed the conflict between Armada's `armada-bottom-screen` session and Ratatoskr, and the backlight daemon clash (`Conflicts=` in the unit; the stock session is restored when Ratatoskr is stopped).

## 2026-10-05
- Initial Decky plugin and input driver with diagnostics.
- Live system-monitor ribbon, quick settings, key highlighting.
- Gesture suite: long-press right click, two-finger right click, pinch zoom, three-finger swipes; friction and the full settings set in the Decky panel.
- Autostart through a systemd user service; Decky enable/disable through `systemctl --machine` with a plain `--user` fallback.
- Standalone manager window and CLI, desktop entries and icon.
- Gamescope X11 wrapper; Artemis configuration helper scripts.
- Simplified gestures, fixed brightness sliders and digitizer polling.
- Edge-scroll bars were added and then removed; continuous key repeat, glyph fixes and clean desktop exit added.
