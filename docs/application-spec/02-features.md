# 02 - Features

Each row is a feature the code implements. "Setting" is the config key that controls it, if any
([05-configuration-requirements.md](05-configuration-requirements.md#configuration-keys)). Numbers in brackets are the
constants in `bin/engine.py`, `bin/thor_app.py` or the other module named.

## Modes and screens

| ID | Feature | Setting | Where |
|---|---|---|---|
| F-01 | Four modes: Trackpad, Split, Keyboard, Quick Controls | `mode` | `bin/thor_app.py:301`, `:328-332`, `:1089-1098` |
| F-02 | Header: Trackpad, Split, Keyboard, Quick Controls, HUD, Left Click, Right Click, Pen, Hide | `pen_mode`, `debug_hud` | `HEADER_BUTTONS` `bin/thor_app.py:85-88`, `_handle_header_touch` `:801-817` |
| F-03 | Ribbon: a tap on the status ribbon toggles Quick Controls | none | `bin/thor_app.py:731-732` |
| F-04 | Hide and Open: the whole screen blanks except an Open button; not persisted | none | `bin/thor_app.py:316-325`, `:671-678` |
| F-05 | Split: the split line is at y = 500; a touch belongs to the area it started in | none | `bin/thor_app.py:82`, `_owner_at` `:671-687` |
| F-06 | Status ribbon: battery (with watts), CPU load and temperature, GPU clock and temperature, RAM, volume, top and bottom brightness; two rows of three | none | `_draw_status_ribbon` `bin/thor_app.py:1128-1188` |
| F-07 | Bottom-screen debug HUD: coordinates, FPS, state, counters | `debug_hud` | `_draw_debug_hud` `bin/thor_app.py:1560-1592` |
| F-08 | Live refresh: the ribbon redraws once a second, so the stats go stale by at most about a second | none | `GLib.timeout_add(1000, ...)` `bin/thor_app.py:435` |

## Trackpad

Gesture constants are in `bin/engine.py`. The engine state machine is `TouchGestureProcessor`
(`bin/engine.py:350`).

| ID | Gesture | Result | Setting | Constant |
|---|---|---|---|---|
| F-10 | One finger moves | relative pointer motion with acceleration `accel = 1 + min(1.6, distance / 25)` | `sensitivity` (default 1.5, driver clamp 0.2 to 5.0) | `engine.py:674-676` |
| F-11 | Quick tap clicks left | `BTN_LEFT` click | `tap_to_click` (default true) | tap time 0.25 s `engine.py:70`; tap travel 12 px per finger `engine.py:71` |
| F-12 | Two fingers move | scroll; step is `HI_RES_NOTCH / max(4, 22 - 4 * scroll_speed)` | `scroll_speed` (1 to 5, default 3) | `engine.py:692-699`, `:76`, `:74` |
| F-13 | Two-finger tap right-clicks | `BTN_RIGHT` click | `two_finger_right_click` (default true) | `engine.py:794-797` |
| F-14 | Press and hold right-clicks | `BTN_RIGHT` after the delay, if the finger moved less than 24 px | `long_press_right_click` (default false), `long_press_delay_ms` (default 450, driver clamp 200 to 1200) | `engine.py:568-573`, `:72-73` |
| F-15 | Three-finger tap middle-clicks | `BTN_MIDDLE` | `three_finger_middle_click` (default false) | `engine.py:798-801` |
| F-16 | Three-finger swipe | up: Super (`KEY_LEFTMETA`), down: Escape, left or right: Alt+Tab; fires after 85 px | `three_finger_swipe_enabled` (default false) | `engine.py:701-724`, `:75` |
| F-17 | Momentum glide after a flick | the pointer keeps moving and decays; starts above 140 px/s, stops below 12 px/s, ticks every 16 ms | `glide` (default true), `friction` (1 to 10, default 5) | start `engine.py:804`, stop `:830`, decay `:821`, `:90-92` |
| F-18 | Four or more fingers are ignored | no output until every finger lifts or goes quiet | none | `MISUSE_FINGERS = 4` `engine.py:95`; `misuse_lock` `:589-597` |
| F-19 | A contact silent for 1.5 s is treated as lifted | the pointer returns after a lost lift | none | `STALE_CONTACT_S = 1.5` `engine.py:89`, `_drop_stale_contacts` `:497-511` |
| F-20 | Held cursor until the touch is known to be a move | a tap does not nudge the pointer | none | `engine.py:664-670` |

Long press and two-finger right click exclude each other. Turning one on turns the other off in the engine
(`engine.py:436-444`) and in the Quick Controls button (`bin/thor_app.py:872-878`).

## Keyboard

| ID | Feature | Setting | Where |
|---|---|---|---|
| F-30 | Five-row QWERTY layout with Esc, Tab, Bksp, Enter, Space, arrows, Ctrl, Alt, Win | none | `create_qwerty_rows` `bin/keyboard_layout.py:94-192` |
| F-31 | Dual-symbol keys (`1 / !`, `, / <`) with the typed symbol drawn large | none | `bin/key_render.py` `draw_dual_label` |
| F-32 | Key repeat: first repeat after the delay, then at the interval | `keyboard_repeat_delay_ms` (default 350, range 150 to 800), `keyboard_repeat_interval_ms` (60, range 20 to 200) | `bin/thor_app.py:403-419`, `bin/keyboard_settings.py:9-16` |
| F-33 | Modifiers: Shift, Ctrl, Alt, Win. Tap = next key only; quick second tap = locked; tap a locked one to release; hold with one finger to cover other keys | `keyboard_caps_window_ms` (default 350, range 150 to 800) | `bin/modifiers.py`, `bin/thor_app.py:742-762` |
| F-34 | Caps Lock is a locked Shift. The Shift key shows "CAPS" when locked | `keyboard_caps_window_ms` | `bin/thor_app.py:1352-1353`, `bin/modifiers.py:80-88` |
| F-35 | Leaving Keyboard or Split, or hiding the UI, releases every modifier, held or latched. A SYN_DROPPED resync ends the current key press and releases only the latched modifiers that no finger holds | none | `set_mode` `bin/thor_app.py:305-308`, `set_ui_hidden` `:321-323`, `_dispatch_frame` `:594-604`, `_end_key_press` `:702-711`, `ModifierState.key_released` `bin/modifiers.py:152-159` |
| F-36 | Keyboard highlights on press; shifted letters are drawn in a brighter tone | none | `_draw_keyboard` `bin/thor_app.py:1281-1359` |

Key codes come from `bin/keyboard_layout.py:4-66` (Linux `input-event-codes`). The virtual keyboard registers every key
code from 1 to 247 (`bin/engine.py:171-175`).

## Pen mode

| ID | Feature | Setting | Where |
|---|---|---|---|
| F-40 | Three states: Off, Pen, Pen + (`pen_mode`); the engine flag is on for Pen and Pen + | `pen_mode` | `bin/pen_mode.py:10-40`, `bin/engine.py:579-580` |
| F-41 | One touch moves; a second contact while one is down is ignored | none | `touch_down` `bin/engine.py:579-580` |
| F-42 | Double tap (two taps within 0.45 s and 60 px) left-clicks; a single tap never clicks; a third quick tap clicks again | none | `_pen_tap` `bin/engine.py:520-534`; `PEN_DOUBLE_TAP_S = 0.45`, `PEN_DOUBLE_TAP_DIST_PX = 60.0` `engine.py:106-107` |
| F-43 | Hold right-clicks after 0.45 s, unless the touch started in a strip | `long_press_delay_ms` | `engine.py:615-619`, `:568-573` |
| F-44 | Right strip (x >= 1130) scrolls vertically; bottom strip (y >= 980) scrolls horizontally | none | `_strip_at` `engine.py:513-518`; `STRIP_RIGHT_W = 110`, `STRIP_BOTTOM_H = 100` `engine.py:98-99` |
| F-45 | Strips have a 4 px start dead zone, a 1.5 px jitter rule, and a speed-based boost of 1x to 3x (`STRIP_ACCEL_MAX = 2.0` added to 1.0) | none | `engine.py:100-103`, `_strip_scroll` `:536-561` |
| F-46 | Two-finger scroll, right-click taps, three-finger gestures and glide are off in Pen mode | none | `engine.py:579-580`, `:803`, `:787-799` |
| F-47 | Strips are drawn on the glass when Pen mode is on | none | `_draw_scroll_strips` `bin/thor_app.py:1253-1279` |

The Pen header button is labelled "Pen" or "Pen +" and drawn lit whenever the mode is not Off (`bin/thor_app.py:1126`).

## Pointer visibility

Game Mode's gamescope hides the pointer after `--hide-cursor-delay` (3000 ms on the Thor, per the author's read of
`gamescope-session-plus` recorded in `bin/session_cursor.py:1-10`). A pointer that is hidden does not receive wheel
events. The driver works around it in two ways.

| ID | Mechanism | Setting | Where |
|---|---|---|---|
| F-50 | Nudge: before a scroll or a press that follows 2 s of pointer stillness, the driver moves the pointer one pixel out and back | none; on unless Pen + is active | `_wake_pointer_locked` `bin/engine.py:206-214`; `POINTER_WAKE_S = 2.0` `engine.py:84`; `wake_pointer` set by `_refresh_cursor_status` `bin/thor_app.py:438-441` |
| F-51 | Pen +: writes the environment override so the next Game Mode start never hides the pointer | `pen_mode` = `pen_plus` | `bin/session_cursor.py`; `set_pen_mode` `bin/thor_app.py:250-266` |
| F-52 | The driver reports whether the running Game Mode has the override (`cursor_stay_visible_active`) | none | `running_delay_ms` and `status` `bin/session_cursor.py:237-279` |

`bin/session_cursor.py` reads `--hide-cursor-delay` from every `/proc/*/cmdline` and caches the result for 10 s.

## Quick Controls

| ID | Feature | Setting | Where |
|---|---|---|---|
| F-60 | Volume slider 0 to 100 with -5, +5 and Mute buttons | none | `_handle_settings_touch` `bin/thor_app.py:819-837`, `_draw_quick_settings` `:1361-1471` |
| F-61 | Top backlight slider, 1 to 100, with -10 and +10 | none | `bin/thor_app.py:839-850` |
| F-62 | Bottom backlight slider, 1 to 100, with -10 and +10 | none | `bin/thor_app.py:852-863` |
| F-63 | Sliders keep following the finger that grabbed them | none | `_handle_settings_drag` `bin/thor_app.py:889-902` |
| F-64 | Tap Click on/off, Right-click 2-finger or press-hold, Glass HUD on/off, Back to Trackpad | `tap_to_click`, `two_finger_right_click`, `long_press_right_click`, `debug_hud` | `bin/thor_app.py:865-884` |
| F-65 | Health card (CPU, GPU, RAM, battery) when Gleipnir is off; Battery and Gleipnir card when on | `gleipnir_ribbon` | `bin/thor_app.py:1408-1412` |

Writes are asynchronous. The requested value is drawn at once and a writer thread per control writes only the newest
value (`bin/system_stats.py:87-136`, `request_*` `:229-245`). The displayed value is held for 1.5 s
(`OPTIMISTIC_HOLD_S`, `bin/system_stats.py:146`).

## Dim bottom screen with the top

| ID | Feature | Setting | Where |
|---|---|---|---|
| F-70 | Opt-in fade of the bottom backlight when the top panel's idle ramp starts; restore when it ends or input arrives | `mirror_dim`, `mirror_dim_floor_percent` (default 3, range 1 to 50) | `bin/dim_mirror.py` `DimMirror`, `bin/top_follower.py` `TopFollower` |
| F-71 | A dim is ignored while the user is probably dragging a slider: input within the last 5 s, and the dim loop has been running for at least 5 s | none | `input_says_slider` `bin/dim_mirror.py:38-42`, call `:393` |
| F-72 | Crash recovery: the pre-dim level is kept in a file until restored, and put back on the next start | none | `RECOVERY_FILE` `bin/dim_mirror.py:53`, `recover` `:280-311` |

Details are in the [design spec](../design-spec/03-timing-idle-throttling-dim.md#dim-follower).

## Burn-in measures

| ID | Measure | Parameters | Where |
|---|---|---|---|
| F-80 | Orbit shift: the whole UI is translated on a circle | radius 1.5 px, cycle 90 s | `get_orbital_offset` `bin/burn_in.py:46-52`; `bin/thor_app.py:151` |
| F-81 | Trackpad hint fades out | shown for 5 s after start or the last mode change, then fades over 1.5 s | `get_hint_alpha` `bin/burn_in.py:54-64` |
| F-82 | Idle veil: after 30 s without a touch the lit pixels dim to 40 % over 5 s; the next touch restores them | `idle_timeout` 30, `idle_floor` 0.4 | `get_luminance_scale` `bin/burn_in.py:66-74`; veil drawn `bin/thor_app.py:1068-1072` |
| F-83 | Pure black background; unlit pixels draw no power; no fills on containers | none | `bin/theme.py`, `_paint` `bin/thor_app.py:1050-1052` |

The Open button in hidden mode is outline only and is dimmed by the same veil (`bin/thor_app.py:1060-1062`).

## Gleipnir view (optional, read-only)

| ID | Feature | Setting | Where |
|---|---|---|---|
| F-90 | Battery cell shows Gleipnir state: held at its cap, charging toward it, running, off, or unverified | `gleipnir_ribbon` | `summary` `bin/gleipnir_view.py:128-145` |
| F-91 | Battery and Gleipnir card: charge in Ah, current, watts, time left, voltage, temperature, health, wear, charger, Gleipnir state, last two journal events | `gleipnir_ribbon` | `card_items` `bin/gleipnir_view.py:167-196` |
| F-92 | Polls `gleipnir --status --json` and sysfs every 10 s; journal once a minute | none | `_gleipnir_loop` `bin/thor_app.py:284-298` |

The script is searched at `/var/local/bin/gleipnir`, `/usr/local/bin/gleipnir`, then `PATH`
(`bin/gleipnir_view.py:15`, `:23-27`). The panel offers the toggle only when Gleipnir is found or the setting is on
(`dist/index.js:496`).

## Diagnostics and logs

| ID | Feature | Where |
|---|---|---|
| F-100 | Numbered diagnostic codes in `DBG-nnn` format | `debug_codes.py:12-117` |
| F-101 | Log lines to stdout and to `/tmp/thor-input-debug.log` | `DebugLogger.log` `debug_codes.py:120-137` |
| F-102 | Self-test: uinput, touchscreen node, IPC socket path, bottom gamescope environment file | `run_self_diagnostics` `debug_codes.py:140-197` |
| F-103 | Telemetry counters: moves, scrolls, clicks, keystrokes, pointer wakes; draw time and frame lag (read and reset with `reset: true`) | `get_telemetry` `bin/engine.py:318-329`; `get_debug` `bin/thor_app.py:950-966` |
| F-104 | Touch log: each touch's duration, travel, fingers, and outcome (click, long press, none) | `touch_up` `bin/engine.py:726-747` |

## Standalone manager

| ID | Feature | Where |
|---|---|---|
| F-110 | GTK window: start or stop, mode radio buttons (Trackpad, Keyboard, Quick Controls), sensitivity, tap and two-finger switches, dim switch, HUD switch, top and bottom brightness sliders, status and telemetry | `bin/touch_master_manager.py:127-418` |
| F-111 | CLI: `--start`, `--stop`, `--toggle`, `--status`, `--wake`, `--mode` | `bin/touch_master_manager.py:421-461` |
| F-112 | Desktop entries: the manager and "Stop Ratatoskr" | `touch-master.desktop`, `touch-master-stop.desktop` |

The manager window has no control for Split, Pen, Hide, the keyboard timings, or Gleipnir.

## Tray menu (AppIndicator)

When `AppIndicator3` is importable, the driver adds an indicator with: Trackpad, Split, Keyboard and Quick Controls mode
items, "Ratatoskr Manager...", and "Stop Ratatoskr" (`bin/thor_app.py:333-376`). The indicator id is `touch-master`
(`bin/thor_app.py:337-341`). If the import fails the driver runs without it (`bin/thor_app.py:27-32`, `:334-335`).
