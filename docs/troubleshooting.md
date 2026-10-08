# Troubleshooting

Start with the log: `journalctl --user -u touch-master.service -n 50 --no-pager` and `/tmp/thor-input-debug.log`. Lines look like `[DBG-203] ... EVIOCGRAB failed`; the codes are in the README.

## Quick checks
```bash
systemctl --user status touch-master.service
~/.local/share/thor-input/bin/touch_master_manager.py --status
```
In the Decky panel, **Run Diagnostics** checks `/dev/uinput`, the touchscreen node, the IPC socket and the bottom-screen gamescope environment.

## Symptoms
| Symptom | Likely cause | What to do |
|---|---|---|
| Bottom screen is black and nothing responds | the service is not running, or the bottom gamescope is not up (`DBG-401`) | `systemctl --user restart armada-bottom-gamescope.service touch-master.service` |
| Panel says "Stopped" but the service is active | the IPC socket is missing (`DBG-302`) | restart the service; check `ls /run/user/1000/thor-input.sock` |
| Touch does nothing and the log says `EVIOCGRAB failed` (`DBG-203`) | another process already holds the digitizer exclusively | stop Armada's own bottom-screen session (`armada-bottom-screen.service`); Ratatoskr's unit conflicts with it, so use the toggle rather than starting both |
| Cursor does not move, keys do nothing (`DBG-101`) | `/dev/uinput` is not writable by `armada` | check `ls -l /dev/uinput` and your groups |
| Brightness sliders and the dim mirror do nothing (`DBG-701`) | stock Armada makes both backlights root-only | install the narrow sudo rule in [installation.md](installation.md) |
| Volume slider does nothing (`DBG-702`) | `wpctl` failed under PipeWire | run `wpctl status` in a user session |
| Log: `could not recover the bottom level ... Invalid argument; will retry` | right after the service (re)starts, the bottom backlight can reject a write for a moment (observed 2026-10-08) | nothing; the mirror retries and the next attempt succeeds. A dim left by a crash or restart is put back from `~/.local/state/thor-input/dim-restore.json` |
| The pointer is dead for a second or two after a press with four or five fingers (log: `4 fingers down: ignoring touch until all lift`) | by design: four or more fingers are ignored until everything has lifted or gone quiet for 1.5 s | wait. The kernel's slot table (`EVIOCGMTSLOTS`) can stay non-empty indefinitely after a lost lift; that no longer blocks input |
| Log: `contact N moved after being dropped as stale: treating it as a new touch` | a finger landed in the slot of a contact whose lift was lost; the kernel keeps the old tracking id, so the engine adopts it | nothing; this is the recovery working |
| The pointer disappears after 3 s and scrolling or tapping in one place stops working | Game Mode's gamescope hides the pointer after `--hide-cursor-delay` (3000 ms on the Thor); pointer motion un-hides it, wheel events and button presses do not restart the timer (`refs/upstream/gamescope` `wlserver.cpp`) | turn on **Keep the pointer visible** in the Decky panel to stop the auto-hide (applies the next time Game Mode starts; it is a launch argument) |
| Panel missing from Decky | the plugin folder or `plugin.json` is wrong | redeploy with `scripts/deploy.sh`; `sudo systemctl restart plugin_loader.service` |

## Known issues (not yet fixed)
These were found while writing the documentation, on the code as published. They are real and unfixed; the Decky panel is the reliable interface.
1. **The standalone manager window sends actions the driver does not understand.** Its brightness sliders send `set_brightness` and its HUD switch sends `set_debug_hud`; the driver only handles `set_top_brightness`, `set_bottom_brightness` and `toggle_hud`. Those controls do nothing live.
2. **The manager nests settings** (`{"action": "set_settings", "settings": {...}}`) but the driver reads flat keys, so its sensitivity slider and switches, including the dim switch, are saved to `config.json` and take effect only after the service restarts. The Decky panel sends flat keys and applies instantly.
3. **Defaults differ** between the manager (`glide` off, `friction` 7) and the driver (`glide` on, `friction` 5). See [configuration.md](configuration.md).
4. **The dim mirror and the narrow sudo rule are untested on a Thor.**

## Reporting a problem
Open an issue with the Armada version, the output of `touch_master_manager.py --status`, and the last lines of the log.
