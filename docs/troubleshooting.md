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
| The pointer disappears after 3 s and scrolling or tapping in one place stops working | Game Mode's gamescope hides the pointer after `--hide-cursor-delay` (3000 ms on the Thor); pointer motion un-hides it, wheel events and button presses do not restart the timer (`refs/upstream/gamescope` `wlserver.cpp`) | in plain Pen mode and the normal trackpad the driver nudges the pointer one pixel out and back before a scroll or press after 2 s of stillness. **Pen +** (header button or Decky panel) stops the auto-hide altogether; it applies the next time Game Mode starts, because the delay is a launch argument |
| Panel missing from Decky | the plugin folder or `plugin.json` is wrong | redeploy with `scripts/deploy.sh`; `sudo systemctl restart plugin_loader.service` |

## Known issues (not yet fixed)
1. **The narrow sudo rule is untested.** The Thor in use has full passwordless sudo, so the dim mirror's backlight writes have been exercised through that, not through `systemd/touch-master-backlight.sudoers`.

## Reporting a problem
Open an issue with the Armada version, the output of `touch_master_manager.py --status`, and the last lines of the log.
