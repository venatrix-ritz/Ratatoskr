# Ratatoskr application spec

What Ratatoskr is, who uses it, what it takes in and produces, the features it has, the hardware it targets, its
interfaces and configuration, and the requirements and limits it is held to.

Written from a read of the code at `origin/main` commit `2447189` on 2026-10-22. Every statement is anchored to
`file:line` (or to a function name for short modules) or is marked **unverified**. Nothing here was run on a device:
the spec was written by reading. Where a statement comes from the author's notes or the existing `docs/` pages rather
than from code, it says so.

The companion [design spec](../design-spec/README.md) explains how each part works.

| # | File | Topic |
|---|---|---|
| 01 | [01-purpose-users-workflows.md](01-purpose-users-workflows.md) | Purpose, scope, users and the day-to-day workflows |
| 02 | [02-features.md](02-features.md) | Every user-visible feature, with its setting and code anchor |
| 03 | [03-hardware-targets.md](03-hardware-targets.md) | The AYN Thor, its bottom screen, the sysfs and input nodes, the Armada software it depends on |
| 04 | [04-interfaces.md](04-interfaces.md) | Inputs and outputs, CLI reference, IPC reference |
| 05 | [05-configuration-requirements.md](05-configuration-requirements.md) | Configuration keys, file paths, install requirements, numbered requirements |
| 06 | [06-testing-limitations-glossary.md](06-testing-limitations-glossary.md) | Test inventory, limitations, known issues, documentation mismatches, glossary |

## Summary

Ratatoskr (formerly Touch Master, renamed 2026-10-07) turns the lower 3.92-inch AMOLED screen of an AYN Thor into a
trackpad, a keyboard, a split of both, or a quick-settings and hardware panel, for a game running on the top screen.
It has three parts: a GTK driver app (`bin/thor_app.py`) that grabs the bottom touchscreen and creates two virtual
uinput devices; a Decky Loader plugin (`main.py` and `dist/index.js`) that starts, stops and configures the driver; and a
standalone manager (`bin/touch_master_manager.py`) that does the same without Decky.

## Status of this spec

- The code is the primary source. The author's own status claims (README "Honest status", CHANGELOG) are quoted as claims.
- The spec does not claim the behaviour was confirmed on a device in this review. Device results are only cited where
  the existing docs cite them, with their date.
- Open defects and documentation/code mismatches found during the read are listed in
  [06-testing-limitations-glossary.md](06-testing-limitations-glossary.md#documentation-and-code-mismatches-found-in-this-review).
