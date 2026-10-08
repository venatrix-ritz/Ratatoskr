# Ratatoskr

> The squirrel that runs messages up and down Yggdrasil: Ratatoskr carries your touches from the bottom screen to the game on the top one. Formerly **Touch Master** (renamed 2026-10-07). The service, config folder, socket and install paths still use the old `touch-master` / `thor-input` names so existing installs keep working.

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin and virtual input driver for the **AYN Thor** (dual-screen handheld, Armada OS). It turns the lower 3.92" AMOLED screen into a **trackpad**, a **keyboard**, a **split** of both, or a **quick-settings and hardware monitor** for games on the main screen, with no launcher in the way.

> **Honest status.** Written and run on one Thor (Armada `20261006.9c7dd3e`, kernel 7.2.6). The trackpad, keyboard, quick controls, Pen mode, the Decky panel and the idle-dim mirror have all been run on that Thor; the dim mirror needed two fixes that only showed up there (Armada re-applies its saved bottom level every 2 s, and a dim left by a restart had to be recovered). Not done: pinch zoom and drag lock are not implemented, the narrow sudo rule is untested, and what the bottom screen does across sleep is unconfirmed. See the [known issues](docs/troubleshooting.md#known-issues-not-yet-fixed). Nothing here is affiliated with AYN or Armada.

## Features
- **Four modes:** Trackpad; Keyboard (5-row thumb layout sending real Linux key codes through `/dev/uinput`, key repeat, modifier highlight); Split (trackpad above, keyboard below); Quick Controls (volume, top and bottom backlight, live ribbon of battery, CPU, GPU, RAM).
- **Trackpad gestures:** acceleration, tap to click, two-finger scroll and right-click tap, optional long-press right click, three-finger middle click, three-finger navigation swipes, and momentum glide with adjustable friction. Middle click, swipes and long-press are off by default. There are also switches for pinch zoom and drag lock, but those two gestures are **not implemented**: the switches are stored and nothing reads them.
- **Pen mode:** one pointer for a stylus (double-tap clicks, hold right-clicks, edge strips scroll), and **Pen +**, which also keeps Game Mode's pointer visible. See [Usage](docs/usage.md#pen-mode).
- **AMOLED friendly:** pure black UI; unlit pixels draw no power.
- **Opt-in: bottom screen follows Steam's idle dim.** Steam only dims the top panel. Ratatoskr can read Steam's dim delay and dim the bottom panel the same way ([docs/dim-mirror.md](docs/dim-mirror.md)).
- **Diagnostics:** numbered `DBG-nnn` codes, a log at `/tmp/thor-input-debug.log`, an on-glass HUD, and a **Run Diagnostics** button.

## Quick start
```bash
git clone https://github.com/venatrix-ritz/Ratatoskr && cd Ratatoskr
./scripts/deploy.sh armada@<thor-ip>      # or set THOR_HOST / local/thor.env
```
Then open the Steam menu, Decky, **Ratatoskr**. Full steps, requirements and uninstall: [docs/installation.md](docs/installation.md).

## Documentation
| Page | What is in it |
|---|---|
| [Installation](docs/installation.md) | requirements, deploy script, manual install, the optional sudo rule, uninstall |
| [Usage](docs/usage.md) | the four modes, every gesture, the Decky panel, the HUD, the manager |
| [Configuration](docs/configuration.md) | every `config.json` key with default and range |
| [Architecture](docs/architecture.md) | processes, touch path, virtual devices, the IPC protocol |
| [Dim mirror](docs/dim-mirror.md) | why only the top screen dims, how the mirror works, limits |
| [Troubleshooting](docs/troubleshooting.md) | symptoms, log reading, **known issues** |
| [Development](docs/development.md) | layout, tests, how to change things, release notes |
| [Changelog](CHANGELOG.md) · [Credits](CREDITS.md) | history; who this builds on |

## Diagnostic codes
| Range | Meaning | Examples |
|---|---|---|
| `DBG-0xx` | lifecycle | `000` OK, `001` starting, `002` ready, `004` stopped |
| `DBG-1xx` | virtual input | `100` uinput OK, `101` cannot open `/dev/uinput` |
| `DBG-2xx` | digitizer | `200` grabbed, `201` node missing, `203` `EVIOCGRAB` failed |
| `DBG-3xx` | IPC socket | `300` ready, `302` cannot connect, `303` bad request |
| `DBG-4xx` | display | `400` display OK, `401` cannot reach the bottom display |
| `DBG-5xx` | gesture telemetry | clicks, scroll, swipe, glide, key presses (`521` is reserved: edge scrolling was removed; no pinch code does anything, see the known issues) |
| `DBG-6xx` | settings and controls | `600` settings updated, `601` backlight, `602` volume, `610` dim mirror |
| `DBG-7xx` | hardware errors | `701` backlight write failed, `702` `wpctl` failed |

The full registry is `debug_codes.py`.

## Credits and licence
Ratatoskr builds on the work of Project Barry (Barry Launcher), the Armada team and the Decky community; see [CREDITS.md](CREDITS.md). MIT licence, see [LICENSE](LICENSE).
