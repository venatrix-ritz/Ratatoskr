# Configuration

Settings live in one JSON file, `~/.config/thor-input/config.json` (`/var/home/armada/.config/thor-input/config.json` on Armada). The driver reads it once at start; the Decky panel and IPC `set_settings` change values live and write the file back. Delete the file to return to the defaults below.

| Key | Default | Range | What it does |
|---|---|---|---|
| `enabled` | `true` | bool | whether the Decky plugin starts the service when Decky loads (written by the plugin and the manager, not by the driver) |
| `mode` | `"trackpad"` | `trackpad`, `split`, `keyboard`, `settings` | the active bottom-screen mode |
| `debug_hud` | `false` | bool | draw coordinates, FPS and counters on the bottom screen |
| `sensitivity` | `1.5` | 0.2 to 5.0 (the Decky slider offers 0.5 to 3.5) | pointer speed multiplier |
| `glide` | `true` | bool | momentum after a flick |
| `friction` | `5` | 1 (slick) to 10 (heavy) | how fast the glide slows |
| `scroll_speed` | `3` | 1 to 5 | two-finger scroll speed |
| `tap_to_click` | `true` | bool | a quick one-finger tap clicks |
| `two_finger_right_click` | `true` | bool | a two-finger tap right-clicks (turning it on turns long-press off) |
| `long_press_right_click` | `false` | bool | press and hold right-clicks (turning it on turns two-finger right click off) |
| `long_press_delay_ms` | `450` | 200 to 1200 (the Decky slider offers 250 to 900) | hold time for the long press |
| `three_finger_middle_click` | `false` | bool | a three-finger tap middle-clicks |
| `three_finger_swipe_enabled` | `false` | bool | three-finger swipes send Super, Escape, Alt+Tab |
| `pen_mode` | `"off"` | `off`, `pen`, `pen_plus` | Pen mode ([usage](usage.md#pen-mode)); `pen_plus` also writes the Game Mode pointer-visible override |
| `stylus_mode` | `false` | bool | the engine half of Pen mode (on for `pen` and `pen_plus`); older configs only have this key, and are read as `pen`, or `pen_plus` if the override file exists |
| `mirror_dim` | `false` | bool | dim the bottom screen on Steam's idle-dim timer ([details](dim-mirror.md)) |
| `mirror_dim_floor_percent` | `3` | 1 to 50 | brightness the bottom screen dims to |

Values outside a range are clamped. The ranges and defaults come from `bin/engine.py` (`TouchGestureProcessor`), `bin/thor_app.py` and `main.py`.

## Things to know
- The standalone manager keeps its own copy of the defaults (it writes the whole file when you touch a control, so they matter). They match the driver's since 2026-10-08; before that the manager's `glide` was `false` and `friction` `7`, and any `config.json` it wrote carries those values. Once `config.json` exists, whatever it holds wins.
- The pointer and tap thresholds that are not settings are constants in `bin/engine.py`: tap time 0.25 s, tap travel 12 px per finger (the cursor is held still until the finger travels past that or stays down that long), long-press travel 24 px, swipe distance 85 px.
- Steam's own settings are not Ratatoskr's, but one of them matters: the dim mirror reads `IdleBacklightDimBatterySeconds` and `IdleBacklightDimACSeconds` from `~/.local/share/Steam/config/config.vdf`.
- Runtime files: socket `/run/user/<uid>/thor-input.sock`, log `/tmp/thor-input-debug.log`.
