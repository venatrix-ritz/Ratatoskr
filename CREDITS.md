# Credits

Ratatoskr exists because other people did the hard parts first.

## Built on
- **[Project Barry / Barry Launcher](https://github.com/project-barry/barry-launcher)** by **lavachemist** and the Project Barry community (GPL-2.0): the dual-display gamescope approach on the Thor, the digitizer coordinate mapping for the rotated panel, trackpad multi-touch gesture ideas and momentum physics, and sensor-discovery patterns, as this project's earlier README stated.
- **[Armada OS](https://armadaos.dev)** by the Armada team: the bottom-screen gamescope session (`armada-run-bottom`, `armada-bottom-gamescope`), the SM8550 device tree and backlight bindings, and the Decky setup this plugin sits in. Armada's own scripts are GPL-2.0-or-later.
- **[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)** by the SteamDeckHomebrew community: the plugin framework and Quick Access Menu components.
- Research on the Thor and Armada that this was built from: [venatrix-ritz/AynThor](https://github.com/venatrix-ritz/AynThor).

## Licence note: Barry Launcher is GPL-2.0, Ratatoskr is MIT
Checked 2026-10-07 by reading both code bases. The only construct identical by inspection is a one-line coordinate flip (`raw_to_screen`), which is the panel's physical orientation. Barry's code has no matching momentum or friction implementation, and its sensor discovery (environment overrides, `_first()` lookups) differs from this project's fixed paths and globs. So MIT is kept and Barry is credited as inspiration. If you know more of Barry's code was reused, the project must become GPL-2.0-compatible: please open an issue and it will be fixed.

## Who made this
**Ven** ([venatrix-ritz](https://github.com/venatrix-ritz)): idea, direction, the Thor it runs on, and every decision about what goes in. Written together with AI assistants (Claude by Anthropic; a Google Antigravity agent), which are tools, not authors.

If you are named here and want something changed, credited differently or removed, open an issue.
