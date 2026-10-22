# 03 - Hardware targets

The only target is the **AYN Thor** dual-screen handheld running **Armada OS** with **Decky Loader** (README.md).
The author's stated test unit ran Armada `20261006.9c7dd3e` on kernel 7.2.6 (README.md, "Honest status"). Nothing in the
repo checks the Armada version at run time, so other builds are **unverified**.

## The bottom screen

| Property | Value | Source |
|---|---|---|
| Panel | 3.92-inch AMOLED, drawn at 1240 by 1080 | `SCREEN_WIDTH = 1240`, `SCREEN_HEIGHT = 1080` `bin/engine.py:66-67`; size in `bin/thor_app.py:75-76` |
| Pixel density | about 16.5 px per mm (comment) | `bin/thor_app.py:75-76`; derived from the 3.92-inch diagonal, not measured here |
| Mounting | rotated 90 degrees relative to the digitizer's raw axes | `raw_to_screen` `bin/engine.py:110-112`: `x = raw_y`, `y = 1079 - raw_x` |
| Driver window | GTK window, fullscreen, undecorated, 1240 by 1080 | `bin/thor_app.py:194-199` |
| Display | runs in the bottom-screen gamescope through `armada-run-bottom`; the code comments name the secondary display `:2` | `systemd/touch-master.service:10`, `debug_codes.py:20` (comment), `docs/architecture.md` ("DISPLAY :2") |
| Pixel colour | pure black base; lit pixels are the only power draw | `bin/theme.py:1-10`, `bin/thor_app.py:1050-1052` |

The header is 80 px of buttons and an 88 px ribbon, so the drawing area starts at y = 168 (`bin/thor_app.py:77-81`).
The split line is at y = 500 (`bin/thor_app.py:82`).

## Touch digitizer

| Property | Value | Source |
|---|---|---|
| Node selection | first `/dev/input/event*` whose `/sys/class/input/<node>/device/name` contains both "bottom" and "touchscreen" (case-insensitive) | `_find_bottom_touchscreen` `bin/thor_app.py:656-665` |
| Node name used by the diagnostic and the idle tracker | `bottom_touchscreen` | `debug_codes.py:158-163`, `bin/dim_mirror.py:119` |
| Fallback node | **none in the code**. The docs say `/dev/input/event5` is a fallback (see [06](06-testing-limitations-glossary.md#documentation-and-code-mismatches-found-in-this-review)) | `bin/thor_app.py:656-665` |
| Exclusive access | `EVIOCGRAB` (value 1) on the node; released on cleanup | `bin/thor_app.py:516-517`, `:465-468` |
| Slots | at most five, and "the controller reports at most five fingers" | `bin/engine.py:93-95`; the docs say it loses lifts when several fingers are down (`docs/troubleshooting.md`, author's observation 2026-10-08, **unverified** here) |
| Retry | if the node is missing or the grab fails, the driver retries every 5 s | `bin/thor_app.py:509-531`, `:585-588` |

The digitizer is grabbed, so no other process can read it. The idle tracker is therefore told about bottom touches by the
app (`bin/thor_app.py:570`, `poke()`). The docs also say a physical controller `/dev/input/event7` is root-only on the
Thor (`docs/dim-mirror.md`, observed 2026-10-08). That is not in the code and is **unverified** here.

## Backlights

| Property | Value | Source |
|---|---|---|
| Top panel backlight | `/sys/class/backlight/ae96000.dsi.0` | `bin/system_stats.py:16`, `bin/dim_mirror.py:33` |
| Bottom panel backlight | `/sys/class/backlight/ae94000.dsi.0` | `bin/system_stats.py:17` |
| Maximum, top | read from `max_brightness`, default 4096 when unreadable | `bin/system_stats.py:336` |
| Maximum, bottom | read from `max_brightness`, default 255 when unreadable | `bin/system_stats.py:340` |
| Armada's saved bottom level | `/etc/armada/bottom-screen-brightness` (integer 0 to 100) | `bin/system_stats.py:18`, `bin/dim_mirror.py:51` |
| Steam's idle ramp, observed | about 260 writes over 30 s, 254 down to 7 on the top panel | `docs/dim-mirror.md` ("observed 2026-10-08", **unverified** here) |

Armada routes every Steam backlight write to the top panel (`docs/dim-mirror.md`, citing Armada's
`steamos-polkit-helpers`, **unverified** here). That is why only the top panel dims with Steam.
Armada's root service `armada-control` re-applies the saved bottom level every 2 s when the backlight differs from it
(`bin/dim_mirror.py:49-50`, citing Armada, **unverified** here). That is why the dim writes the saved file too.

## Sensors and other sysfs and proc nodes

| Quantity | Path or source | Source |
|---|---|---|
| Battery | `/sys/class/power_supply/battery`: `capacity`, `status`, `voltage_now`, `current_now` | `bin/system_stats.py:19`, `_sample` `:304-309` |
| USB charger (for Gleipnir card) | `/sys/class/power_supply/qcom-battmgr-usb`: `online`, `usb_type`, `voltage_now`, `input_current_limit` | `bin/gleipnir_view.py:64-66` |
| GPU clock and temperature | devfreq `/sys/class/devfreq/3d00000.gpu/cur_freq`; thermal zones whose type contains "gpu" | `bin/system_stats.py:20`, `:173-175`, `:278-283` |
| CPU clock and temperature | `/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq`; thermal zones whose type starts with "cpuss" | `bin/system_stats.py:168-172`, `:269-275` |
| CPU load | `/proc/stat` first line, idle and iowait fields | `bin/system_stats.py:253-267` |
| RAM | `/proc/meminfo` `MemTotal`, `MemAvailable` | `bin/system_stats.py:288-302` |
| Pointer auto-hide delay | `--hide-cursor-delay` in every `/proc/<pid>/cmdline` | `bin/session_cursor.py:237-270` |
| Volume and mute | PipeWire default sink through `wpctl get-volume`, `set-volume`, `set-mute` on `@DEFAULT_AUDIO_SINK@` | `bin/system_stats.py:312-332`, `:363-393` |

## Virtual devices

| Device | Bus, vendor, product | Keys and axes | Source |
|---|---|---|---|
| Thor Virtual Trackpad | virtual (0x06), 0x1234, 0x5678 | buttons left, right, middle; relative X, Y, wheel, horizontal wheel, and high-resolution wheels | `bin/engine.py:23-42`, `:143-165` |
| Thor Virtual Keyboard | virtual (0x06), 0x1234, 0x5679 | key codes 1 to 247 | `bin/engine.py:167-185` |

Both are created through `/dev/uinput` and need write access to it (`scripts/deploy.sh`, `docs/installation.md`,
`run_self_diagnostics` `debug_codes.py:147-152`).

## Armada and Decky components the code depends on

| Component | How Ratatoskr uses it | Source |
|---|---|---|
| `armada-run-bottom` | wraps the driver's launch so it gets the bottom session environment | `systemd/touch-master.service:10` |
| `armada-bottom-gamescope.service` | the unit is `PartOf` and ordered after it | `systemd/touch-master.service:3-4` |
| `armada-bottom-screen.service` | Ratatoskr conflicts with it and the stop path starts it again | `systemd/touch-master.service:5`, `main.py` `_stop_service`, `bin/touch_master_manager.py:97-114` |
| `/run/user/<uid>/armada-bottom-env` | existence checked by self-test as the bottom display environment | `debug_codes.py:189-191` |
| `gamescope-session-plus` | reads `~/.config/environment.d/*.conf` and passes `--hide-cursor-delay` | `bin/session_cursor.py:1-10` (author's read on 2026-10-08, **unverified** here) |
| `plugin_loader.service` | restarted by the install scripts to reload Decky | `scripts/deploy.sh:67`, `scripts/deploy-decky-panel.sh:30` |
| Decky plugin folder | `/home/armada/homebrew/plugins/thor-input` (root-owned) | `scripts/deploy.sh:15`, `scripts/deploy-decky-panel.sh:16` |
| Steam | the top panel's idle dim is the thing mirrored; Ratatoskr does not call Steam | `bin/dim_mirror.py:1-12` |
| Gleipnir | optional read-only status (`gleipnir --status --json`, `systemctl is-active gleipnir`, journal tag `gleipnir`) | `bin/gleipnir_view.py:4-6`, `:43`, `:79` |
| AppIndicator3 | optional tray menu | `bin/thor_app.py:27-32` |

## Hardware-linked constants

| Constant | Value | Why, as the code or docs say | Source |
|---|---|---|---|
| Pointer auto-hide | 3000 ms by default in Game Mode | gamescope hides the pointer after this many ms without motion | `bin/session_cursor.py:1-10`, `bin/engine.py:77-84` |
| Pen + override | 3600000 ms (one hour) | "effectively never" | `bin/session_cursor.py:200` |
| Digitizer lift loss | a contact silent for 1.5 s is dropped | the controller sometimes does not report a lift | `bin/engine.py:85-89` |
| Dim floor | 3 percent by default | the brightness the bottom dims to | `bin/thor_app.py:140`, `main.py` `_default_config` |
