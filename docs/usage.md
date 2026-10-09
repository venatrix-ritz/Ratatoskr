# Using Ratatoskr

The bottom screen is a 3.92" AMOLED panel. Ratatoskr draws on it with pure black (unlit pixels use no power) and turns your touches into a virtual mouse and keyboard that the game on the top screen sees.

## The four modes
Switch with the buttons along the top of the bottom screen, from the Decky panel, or with `touch_master_manager.py --mode`.

| Mode | What the bottom screen is |
|---|---|
| **Trackpad** | a full-screen touchpad |
| **Split** | the upper part is a trackpad, the lower part a keyboard (the keyboard starts 500 px down) |
| **Keyboard** | a thumb keyboard that sends real Linux key codes through `/dev/uinput`, with dual-symbol keys, a highlight on active modifiers and key repeat. Shift, Ctrl, Alt and Win: tap once for the next key only, tap twice quickly to lock (Caps Lock for Shift), tap a locked one to release it; or hold one with a finger while typing with another. Switching to Trackpad or Quick Controls releases them all |
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
| Three-finger swipe (85 px) | up: Super (opens Steam), down: Escape, left/right: Alt+Tab | `three_finger_swipe_enabled` (off) |
| Flick and release | the pointer keeps gliding and slows down | `glide`, `friction` |

Three-finger swipes are off by default because they caused accidental triggers. Pinch zoom and drag lock were removed (they were never implemented).

Four or more fingers at once do nothing: the touch is ignored until every finger has left the glass. The digitizer has five slots and, observed on the Thor on 2026-10-08, it sometimes never reports the lift of a finger when several were down; the kernel then keeps that contact "held". Ignoring multi-finger presses stops them from turning into scrolls or clicks, and a contact that goes quiet for 1.5 s is treated as lifted, so the pointer is back within about 1.5 s of letting go.

## Pen mode
For a stylus. Tap the orange **Pen** button in the header (each tap goes Off, Pen, Pen +, Off) or use the **Pen** section of the Decky panel.

| In Pen mode | Result |
|---|---|
| One touch moves | the pointer moves like a mouse; lifting and setting the pen down again only repositions it |
| Double tap (two taps within 0.45 s and 60 px) | left click; a third quick tap clicks again, so three quick taps make a double click |
| Single tap | nothing: a pen landing often registers as a quick tap, so a lone tap never clicks |
| Press and hold (0.45 s) | right click |
| Drag along the right-hand strip | scroll up and down |
| Drag along the bottom strip | scroll sideways |
| A second touch while one is down | ignored, so a resting palm does nothing |

Two-finger scroll, right-click taps, three-finger swipes and glide are off while Pen mode is on. A touch that starts in a strip stays a scroll wherever the pen drifts.

**Pen +** is Pen plus Game Mode's pointer-visible setting. Game Mode's gamescope hides the pointer 3 s after it last moved, and a scroll or a button press does not count as moving it (`refs/upstream/gamescope` `steamcompmgr.cpp` `checkSuspension`, `wlserver.cpp`). Plain Pen deals with that by nudging the pointer one pixel out and back before a scroll or press that follows 2 s of stillness. Pen + removes the cause instead: it writes `~/.config/environment.d/50-ratatoskr-cursor.conf` (`HIDE_CURSOR_DELAY_MS=3600000`), which the Thor's `gamescope-session-plus` passes to gamescope as `--hide-cursor-delay`. That is a launch argument with no run-time setter, so it takes effect the next time Game Mode starts (a reboot is the sure way). Until then the nudges stay on and the pen hint says so. Leaving Pen + deletes the file.

## Settings
In the Decky panel (Steam menu, Decky, Ratatoskr): sensitivity, glide and friction, scroll speed, tap to click, long-press right click and its delay, two- and three-finger taps, navigation swipes, the **Pen** section (Pen mode and Pen +), the on-glass HUD, and the **Screens** toggle that dims the bottom screen with Steam's idle dim ([details](dim-mirror.md)). All keys and ranges are in [configuration.md](configuration.md).

The panel also shows service state, hardware stats, input telemetry (moves, scrolls, clicks, keys) and a **Run Diagnostics** button.

## The HUD
"Bottom Screen HUD Overlay" draws live touch coordinates, FPS and event counters on the glass. It is for tuning and debugging.

## The standalone manager
`touch_master_manager.py` opens a small window with a start/stop button, mode buttons, sensitivity, tap and two-finger switches, brightness sliders and the dim switch. Some of its controls do not take effect live yet; see [Known issues](troubleshooting.md#known-issues-not-yet-fixed). The Decky panel is the complete interface.

## Waking the screens and restarting the sleep timer
`touch_master_manager.py --wake` sends a harmless key tap (F24) through Ratatoskr's virtual keyboard. Steam sees it as input, so a dimmed top screen lights up and the idle timers start over. It is meant for scripts and SSH sessions that should keep the Thor awake while they work. It cannot help once the Thor has actually suspended (Armada's fake suspend freezes user processes, SSH included, until the power button is pressed).

## Stopping it
Turn off "Enable Bottom Screen" in the Decky panel, or `touch_master_manager.py --stop`. This stops and disables the Ratatoskr service and re-enables and starts Armada's own bottom-screen session (`armada-bottom-screen.service`). Turning it back on does the reverse.
