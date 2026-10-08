# Using Ratatoskr

The bottom screen is a 3.92" AMOLED panel. Ratatoskr draws on it with pure black (unlit pixels use no power) and turns your touches into a virtual mouse and keyboard that the game on the top screen sees.

## The four modes
Switch with the buttons along the top of the bottom screen, from the Decky panel, or with `touch_master_manager.py --mode`.

| Mode | What the bottom screen is |
|---|---|
| **Trackpad** | a full-screen touchpad |
| **Split** | the upper part is a trackpad, the lower part a keyboard (the keyboard starts 500 px down) |
| **Keyboard** | a thumb keyboard that sends real Linux key codes through `/dev/uinput`, with dual-symbol keys, a highlight on active modifiers and key repeat |
| **Quick Controls** | sliders for volume, top-screen brightness and bottom-screen brightness, plus a live ribbon: battery % and watts, CPU load and temperature, GPU clock and temperature, RAM, volume, both backlights |

## Trackpad gestures
| Gesture | Result | Setting |
|---|---|---|
| One finger moves | relative pointer movement with acceleration | `sensitivity` |
| Quick tap (under 0.25 s, under 12 px of travel; the cursor stays put meanwhile) | left click | `tap_to_click` |
| Two fingers move | scroll | `scroll_speed` |
| Two-finger tap | right click | `two_finger_right_click` (on) |
| Press and hold (0.45 s default) | right click | `long_press_right_click` (off; turning it on turns two-finger right click off, and the reverse) |
| Three-finger tap | middle click | `three_finger_middle_click` (off) |
| Two-finger pinch | Ctrl plus mouse wheel (zoom) | `pinch_zoom_enabled` (off) |
| Three-finger swipe (85 px) | up: Super (opens Steam), down: Escape, left/right: Alt+Tab | `three_finger_swipe_enabled` (off) |
| Double-tap and drag | holds the left button | `drag_lock_enabled` (off) |
| Flick and release | the pointer keeps gliding and slows down | `glide`, `friction` |

Pinch zoom, three-finger swipes and drag lock are off by default because they caused accidental triggers (Ctrl presses, stray gestures, a stuck left button).

## Settings
In the Decky panel (Steam menu, Decky, Ratatoskr): sensitivity, glide and friction, scroll speed, tap to click, long-press right click and its delay, two- and three-finger taps, pinch zoom, navigation swipes, drag lock, the on-glass HUD, and the **Screens** toggle that dims the bottom screen with Steam's idle dim ([details](dim-mirror.md)). All keys and ranges are in [configuration.md](configuration.md).

The panel also shows service state, hardware stats, input telemetry (moves, scrolls, clicks, keys) and a **Run Diagnostics** button.

## The HUD
"Bottom Screen HUD Overlay" draws live touch coordinates, FPS and event counters on the glass. It is for tuning and debugging.

## The standalone manager
`touch_master_manager.py` opens a small window with a start/stop button, mode buttons, sensitivity, tap and two-finger switches, brightness sliders and the dim switch. Some of its controls do not take effect live yet; see [Known issues](troubleshooting.md#known-issues-not-yet-fixed). The Decky panel is the complete interface.

## Waking the screens and restarting the sleep timer
`touch_master_manager.py --wake` sends a harmless key tap (F24) through Ratatoskr's virtual keyboard. Steam sees it as input, so a dimmed top screen lights up and the idle timers start over. It is meant for scripts and SSH sessions that should keep the Thor awake while they work. It cannot help once the Thor has actually suspended (Armada's fake suspend freezes user processes, SSH included, until the power button is pressed).

## Stopping it
Turn off "Enable Bottom Screen" in the Decky panel, or `touch_master_manager.py --stop`. This stops and disables the Ratatoskr service and re-enables and starts Armada's own bottom-screen session (`armada-bottom-screen.service`). Turning it back on does the reverse.
