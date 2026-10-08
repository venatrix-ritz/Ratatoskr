# Installing Ratatoskr

Ratatoskr (formerly *Touch Master*) turns the AYN Thor's bottom screen into a trackpad, keyboard and quick-settings surface. It has three parts that are installed together:

| Part | Where it lives on the Thor | What it is |
|---|---|---|
| Driver app | `/var/home/armada/.local/share/thor-input/` (`bin/*.py`, `debug_codes.py`) | the GTK app that grabs the touchscreen, draws on the bottom screen and creates the virtual mouse/keyboard |
| User service | `~/.config/systemd/user/touch-master.service` | starts the driver inside the bottom-screen gamescope (`armada-run-bottom`) |
| Decky plugin | `/home/armada/homebrew/plugins/thor-input/` | the Quick Access Menu panel and its backend, which start/stop the service and change settings |

The runtime names (`touch-master`, `thor-input`) are the project's old names. They are unchanged on purpose so existing installs keep working.

## Requirements
- AYN Thor on **Armada OS** with **Decky Loader** (Armada ships it). Written and tested against Armada `20261006.9c7dd3e`, kernel 7.2.6.
- Python 3 with GTK 3 (PyGObject) and cairo on the Thor. They are already present on the surveyed Thor (the driver runs there); Ratatoskr installs no packages.
- SSH key access to the Thor and `sudo` there, for the one-time Decky plugin copy.
- `/dev/uinput` writable by the `armada` user (for the virtual mouse and keyboard). The diagnostics (below) check this.

## Install from your PC
```bash
git clone https://github.com/venatrix-ritz/Ratatoskr && cd Ratatoskr
./scripts/deploy.sh armada@<thor-ip>
```
The host can also come from `THOR_HOST`, `THOR_ENV_FILE` or a git-ignored `local/thor.env` (template: `scripts/thor.env.example`). The Thor's address is shown in Armada Tools, Remote Access.

`deploy.sh` copies the driver, the desktop entries and icon, the user unit and the Decky plugin files, restarts `plugin_loader.service` (Decky) and restarts `touch-master.service` so the new code loads. It uses `sudo` only for the Decky plugin directory.

## Manual install
1. Copy `bin/*.py` and `debug_codes.py` to `~/.local/share/thor-input/` (keep `bin/` as a subfolder).
2. Copy `systemd/touch-master.service` to `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now touch-master.service`.
3. Copy `plugin.json`, `package.json`, `main.py`, `debug_codes.py` and `dist/index.js` to `/home/armada/homebrew/plugins/thor-input/` (root-owned, mode 755), then `sudo systemctl restart plugin_loader.service`.

## Verify
- Steam menu, Decky, **Ratatoskr**: the toggle "Enable Bottom Screen" should be on and the bottom screen should show the trackpad.
- Over SSH: `systemctl --user is-active touch-master.service` prints `active`; `~/.local/share/thor-input/bin/touch_master_manager.py --status` prints the service state and the daemon's reply.
- The Decky panel has a **Run Diagnostics** button; it checks `/dev/uinput`, the `bottom_touchscreen` node, the IPC socket and the bottom-screen gamescope environment.

## Optional: a narrow sudo rule for brightness
Stock Armada leaves both backlights root-only, on purpose (Steam would otherwise write the wrong panel). Ratatoskr changes brightness through `sudo -n tee <backlight file>`. If you have broad passwordless sudo that already works; if not, install the narrow rule, which allows only those two files:
```bash
sudo visudo -cf systemd/touch-master-backlight.sudoers && \
  sudo install -m 0440 -o root -g root systemd/touch-master-backlight.sudoers /etc/sudoers.d/92-ratatoskr-backlight
```
Without either, the brightness sliders and the [dim mirror](dim-mirror.md) cannot change a backlight (they log `DBG-701`).

## Uninstall
```bash
systemctl --user disable --now touch-master.service
rm ~/.config/systemd/user/touch-master.service ~/.local/share/applications/touch-master*.desktop
rm -r ~/.local/share/thor-input ~/.config/thor-input
sudo rm -r /home/armada/homebrew/plugins/thor-input && sudo systemctl restart plugin_loader.service
```
Armada's own bottom-screen session (`armada-bottom-screen.service`) is stopped while Ratatoskr runs (the unit declares `Conflicts=`). The Decky toggle and the manager's stop button restart it; after a manual uninstall run `systemctl --user enable --now armada-bottom-screen.service`.

## Standalone manager
`touch_master_manager.py` is a small GTK window and CLI that works without Decky: `--start`, `--stop`, `--toggle`, `--status`, `--mode trackpad|keyboard|settings`. There are desktop entries for it. See [Known issues](troubleshooting.md#known-issues-not-yet-fixed) for what its window cannot do live yet.
