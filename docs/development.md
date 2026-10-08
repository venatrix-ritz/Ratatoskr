# Development

## Layout
| Path | What |
|---|---|
| `bin/thor_app.py` | the driver: touch reader, UI drawing, IPC server |
| `bin/engine.py` | `UInputBridge` and `TouchGestureProcessor` |
| `bin/keyboard_layout.py` | on-glass keyboard geometry |
| `bin/system_stats.py` | battery/CPU/GPU/RAM/backlight/volume sampling and setters |
| `bin/dim_mirror.py` | idle tracker and the bottom-screen dim follower |
| `bin/touch_master_manager.py` | standalone GTK window and CLI |
| `debug_codes.py` | diagnostic codes and logger |
| `main.py`, `plugin.json`, `package.json`, `dist/index.js` | the Decky plugin (backend and panel) |
| `systemd/` | the user unit and the optional sudoers fragment |
| `scripts/deploy.sh` | install onto a Thor over SSH |
| `scripts/artemis-wrapper.sh`, `scripts/update-artemis-config.py` | helpers for running the Artemis streaming client in Game Mode; not part of Ratatoskr's function |
| `tests/` | unit tests that need no device |

## Running the tests
```bash
python tests/test_dim_mirror.py
```
The dim-mirror tests use fake hardware and run on any OS. The driver itself needs GTK, cairo, `/dev/uinput` and the Thor's bottom-screen session, so it can only be exercised on the device. Syntax checks that work anywhere:
```bash
python -m py_compile main.py debug_codes.py bin/*.py
node --check dist/index.js
bash -n scripts/deploy.sh
```

## The panel has no build step
`dist/index.js` is plain JavaScript written against the globals Decky injects (`DFL`, `SP_JSX`, `SP_REACT`), kept in the repo as shipped. Its manifest name must equal the `name` in `plugin.json` (`Ratatoskr`).

## Changing things
- **A new setting:** add the key to the gesture processor (`engine.py`) or the app (`_apply_mirror_settings` is the pattern), to `get_status`, to the defaults in `main.py` and `touch_master_manager.py`, to the panel, and to [configuration.md](configuration.md).
- **A new IPC action:** add it to the `_ipc_loop` chain in `thor_app.py` and to the table in [architecture.md](architecture.md). The manager builds its requests with `ipc_util.settings_request` / `brightness_request` / `hud_request`, and `tests/test_ipc_util.py` checks that they only use actions the driver handles.
- **A new diagnostic code:** add it to `DebugCode` and `CODE_DESCRIPTIONS` in `debug_codes.py` and to the README table.

## Conventions
- Linux-bound files are pinned to LF by `.gitattributes` (Windows checkouts use `autocrlf`). Never let CRLF reach the Thor.
- Keep device addresses, MAC addresses and credentials out of tracked files. `local/` is git-ignored.
- Branch for every change and open a pull request; commit author is Ven; commit messages end with the Co-Authored-By line when an assistant helped.
- Never rewrite published history without a backup bundle (`git bundle create ../backup.bundle --all`).

## Releasing
There are no versioned releases yet. When there are: update `CHANGELOG.md` and `package.json`, tag, and attach nothing (the plugin is installed from the repo with `deploy.sh`).
