# Changelog

Dates are 2026. The project was called Touch Master until 2026-10-07. No version numbers have been cut yet.

## Unreleased
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
