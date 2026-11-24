# Development

## Layout
| Path | What |
|---|---|
| `bin/thor_app.py` | the driver: touch reader, UI drawing, IPC server |
| `bin/engine.py` | `UInputBridge` and `TouchGestureProcessor` |
| `bin/keyboard_layout.py` | on-glass keyboard geometry |
| `bin/key_render.py` | key label drawing (pure cairo) |
| `bin/keyboard_settings.py` | keyboard timing settings and limits |
| `bin/modifiers.py` | Shift / Ctrl / Alt / Win state machine |
| `bin/gleipnir_view.py` | read-only Gleipnir status for the ribbon and Quick Controls |
| `tests/test_keyboard_handlers.py` | drives the real touch handlers with a fake keyboard; needs GTK, so run it on the Thor (prints `skip` elsewhere) |
| `tests/render_screens.py` | renders every mode of the real drawing code to PNG (run it on the Thor) |
| `tests/render_keyboard.py` | renders the keyboard labels to PNG for a visual check (needs pycairo; run it on the Thor) |
| `bin/system_stats.py` | battery/CPU/GPU/RAM/backlight/volume sampling and setters |
| `bin/dim_mirror.py` | idle tracker and the bottom-screen dim follower |
| `bin/touch_master_manager.py` | standalone GTK window and CLI |
| `debug_codes.py` | diagnostic codes and logger |
| `main.py`, `plugin.json`, `package.json` | the Decky plugin: backend, manifest and store metadata, build scripts |
| `src/index.tsx`, `src/panelLogic.ts` | the Decky panel (TypeScript and React), built into `dist/index.js`, which git ignores |
| `rollup.config.js`, `tsconfig.json`, `pnpm-lock.yaml` | the panel build, from the Decky plugin template |
| `systemd/` | the user unit and the optional sudoers fragment |
| `scripts/deploy.sh` | install onto a Thor over SSH |
| `scripts/artemis-wrapper.sh`, `scripts/update-artemis-config.py` | helpers for running the Artemis streaming client in Game Mode; not part of Ratatoskr's function |
| `tests/` | unit tests that need no device |

## Running the tests
```bash
for t in tests/test_*.py; do python "$t" || break; done
node tests/test_panel_logic.mjs
```
The Python tests use fake hardware, pipes and socket pairs and run on any OS (except `tests/test_driver_sync.py`, which needs `os.chown` and skips itself on Windows); they are also run on the Thor by the deploy routine, so none of them may touch the real volume, backlight or sudo (`tests/test_system_stats.py` blocks real commands and fails if anything slips through). `tests/test_panel_logic.mjs` runs the Decky panel's pure helpers (`mergeStatus`, `makeThrottle` in `src/panelLogic.ts`) under Node 23.6 or newer, which imports the TypeScript file directly (type stripping), so it needs no `pnpm install`. The driver itself needs GTK, cairo, `/dev/uinput` and the Thor's bottom-screen session, so it can only be exercised on the device. Syntax checks that work anywhere:
```bash
python -m py_compile main.py debug_codes.py bin/*.py
bash -n scripts/deploy.sh
pnpm exec tsc --noEmit
```
The type check needs `pnpm install` first.

## Building the panel
The panel follows the [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template): `src/index.tsx` uses `@decky/ui` components and `@decky/api` calls, and `pnpm run build` (rollup with `@decky/rollup`) writes `dist/index.js`. Decky supplies React and `@decky/ui` at runtime, so the bundle refers to them instead of including them. `dist/` is git-ignored: `deploy.sh` and `deploy-decky-panel.sh` stop if it is missing, and `build-release.py` builds it with `pnpm install --frozen-lockfile`. Keep `pnpm-lock.yaml` on `lockfileVersion: '9.0'` (Decky's review checks it) and the `name` in `plugin.json` as `Ratatoskr` (the bundle's manifest name is taken from it). Logic that needs neither Decky nor React goes in `src/panelLogic.ts`, so the Node test can import it.

Run `pnpm install` once, then `pnpm run build`, or `pnpm run watch` to rebuild on every save.

## Changing things
- **A new setting:** add the key to the gesture processor (`engine.py`) or the app (`_apply_mirror_settings` is the pattern), to `get_status`, to the defaults in `main.py` and `touch_master_manager.py`, to the panel, and to [configuration.md](configuration.md).
- **A new IPC action:** add it to the `_ipc_loop` chain in `thor_app.py` and to the table in [architecture.md](architecture.md). The manager builds its requests with `ipc_util.settings_request` / `brightness_request`, and `tests/test_ipc_util.py` checks that they only use actions the driver handles.
- **A new diagnostic code:** add it to `DebugCode` and `CODE_DESCRIPTIONS` in `debug_codes.py` and to the README table.

## Conventions
- Linux-bound files are pinned to LF by `.gitattributes` (Windows checkouts use `autocrlf`). Never let CRLF reach the Thor.
- Keep device addresses, MAC addresses and credentials out of tracked files. `local/` is git-ignored.
- Branch for every change and open a pull request; commit author is Ven, with no Co-Authored-By or other attribution lines.
- Never rewrite published history without a backup bundle (`git bundle create ../backup.bundle --all`).

## Releasing
1. In a pull request, turn the changes into a `## X.Y.Z (date)` section of `CHANGELOG.md` and set `version` in `package.json`. Merge it.
2. Tag the merge commit on `main` as `vX.Y.Z` and push the tag.
3. Check the tag out (a detached worktree is fine) and run `python scripts/build-release.py`. It builds `release/Ratatoskr.zip` from `HEAD`'s committed files plus the panel, which it builds with pnpm (on `PATH`, or set `PNPM`), with one top-level `thor-input/` folder.
4. Create the GitHub release from the tag and attach the zip as `Ratatoskr.zip`, the name the Armada Store matches (`^Ratatoskr\.zip$`). Mark it a pre-release while parts are untested on hardware, and say in the notes what was and wasn't tested.
