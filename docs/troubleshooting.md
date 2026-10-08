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
| Panel missing from Decky | the plugin folder or `plugin.json` is wrong | redeploy with `scripts/deploy.sh`; `sudo systemctl restart plugin_loader.service` |

## Known issues (not yet fixed)
These were found while writing the documentation, on the code as published. They are real and unfixed; the Decky panel is the reliable interface.
1. **The standalone manager window sends actions the driver does not understand.** Its brightness sliders send `set_brightness` and its HUD switch sends `set_debug_hud`; the driver only handles `set_top_brightness`, `set_bottom_brightness` and `toggle_hud`. Those controls do nothing live.
2. **The manager nests settings** (`{"action": "set_settings", "settings": {...}}`) but the driver reads flat keys, so its sensitivity slider and switches, including the dim switch, are saved to `config.json` and take effect only after the service restarts. The Decky panel sends flat keys and applies instantly.
3. **Defaults differ** between the manager (`glide` off, `friction` 7) and the driver (`glide` on, `friction` 5). See [configuration.md](configuration.md).
4. **The dim mirror and the narrow sudo rule are untested on a Thor.**

## Reporting a problem
Open an issue with the Armada version, the output of `touch_master_manager.py --status`, and the last lines of the log.
