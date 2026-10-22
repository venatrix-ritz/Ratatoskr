# 06 - Testing, limitations, known issues, mismatches and glossary

## Testing

### Test inventory

Every file below was read for this spec. "Device" means the file needs GTK, cairo or the Thor's session and says so in its
header. The tests were **not run** for this spec (the task was documentation only).

| File | What it covers | Needs a device? | Source of the statement |
|---|---|---|---|
| `tests/test_engine.py` | gesture engine: taps, moves, holds, two-finger scroll, stale contacts, glide, pen | no | `tests/test_engine.py` header and test names |
| `tests/test_touch_frames.py` | frame parser: down, move, up, `SYN_DROPPED`, resync, screen transform | no | header |
| `tests/test_modifiers.py` | Shift, Ctrl, Alt, Win state machine | no | header |
| `tests/test_keyboard_settings.py` | keyboard timing defaults, clamping | no | header |
| `tests/test_keyboard_handlers.py` | the real touch handlers with a fake keyboard: Shift, Caps, split drag, Hide and Open | yes (needs GTK and cairo; prints `skip` elsewhere) | header |
| `tests/test_dim_mirror.py` | idle tracker activity rules, boot clock, Armada saved level, restore and recovery, unwritable backlight | no (fake stats and files) | header and names |
| `tests/test_top_follower.py` | dim and restore decisions on synthetic and Steam-like ramps | no | header |
| `tests/test_system_stats.py` | sudo write handling, writer folding, optimistic values, mute; blocks real commands and fails if one gets through | no, but its header says it also runs on the Thor | header |
| `tests/test_atomic_json.py` | atomic writes, failures, concurrent writers, mode and owner kept | no (temp dirs) | header |
| `tests/test_ipc_util.py` | request framing, limits, stalls, builders only use driver actions | no (socket pairs) | header |
| `tests/test_driver_sync.py` | release-zip driver copy: first install, no-op, update, bad file | needs Linux (`os.chown`); skips itself on Windows | header |
| `tests/test_burn_in.py` | orbit radius, hint fade, luminance floor | no | header |
| `tests/test_pen_mode.py` | cycle order, migration from `stylus_mode`, override only for Pen + | no | header |
| `tests/test_session_cursor.py` | override file, sourcing, `/proc` scan, cached status | no (temp dirs and fake `/proc`) | header |
| `tests/test_gleipnir_view.py` | Gleipnir status and sysfs parsing, journal, card rows | no (fake runner and sysfs) | header |
| `tests/test_theme.py` | palette values and names | no | header |
| `tests/test_tray_actions.py` | the tray Stop command runs the manager in its own unit | no | header |
| `tests/test_panel_logic.cjs` | `mergeStatus` and `makeThrottle` from `dist/index.js` | no (Node) | header |
| `tests/render_screens.py` | renders every mode to PNG via `ThorApp._paint` | yes (gi and pycairo, run on the Thor) | header; not a unit test |
| `tests/render_keyboard.py` | renders the key labels to PNG | yes (pycairo) | header; not a unit test |

### How the tests are meant to run

From `docs/development.md` (not run here):

```bash
for t in tests/test_*.py; do python "$t" || break; done
node tests/test_panel_logic.cjs
python -m py_compile main.py debug_codes.py bin/*.py
node --check dist/index.js
bash -n scripts/deploy.sh
```

`docs/development.md` also says the deploy routine runs the Python tests on the Thor. `scripts/deploy.sh` does not
(see [mismatch 2](#documentation-and-code-mismatches-found-in-this-review)).

### What the tests cannot show
- Real digitizer timing, real uinput delivery to a game, gamescope pointer hiding, and Armada's backlight behaviour are
  outside the test suite. The docs record observations of these on the author's device, dated, and this spec cites them
  as observations only.
- The narrow sudo rule is not exercised by any test. `docs/troubleshooting.md` says so.

## Limitations

1. **One device, one OS build.** Targets only the AYN Thor on Armada OS (see [03](03-hardware-targets.md)). No check of the Armada version.
2. **Lost lifts.** The controller sometimes does not report a finger lift when several fingers are down. The driver
   copes with a 1.5 s silence timeout and by ignoring four or more fingers (`bin/engine.py:85-95`). A pointer can be dead
   for up to about 1.5 s after such an event.
3. **Pointer hidden by Game Mode.** Without Pen + the driver nudges the pointer before scrolls and presses after 2 s of
   stillness (`bin/engine.py:77-84`). Pen + needs Game Mode to restart before it takes effect (`bin/session_cursor.py:1-10`).
4. **Dim mirror follows the top only.** It cannot dim the bottom when the top is not dimmed by Steam. It does not handle
   sleep (`bin/dim_mirror.py:14-17`), and its timing is tuned against one observed Steam ramp (`docs/dim-mirror.md`).
5. **Narrow sudo rule incomplete** (see [05](05-configuration-requirements.md#backlight-write-access)).
6. **Keyboard.** There is no Caps Lock key; Caps is a double-tapped Shift (`bin/keyboard_layout.py:94-192`). The keyboard
   has no number pad. Layout is QWERTY only. Modifier state is kept only while the keyboard is shown.
7. **Hide is not saved.** A restart shows the UI (`bin/thor_app.py:121`).
8. **Manager is partial.** It cannot select Split, Pen, Hide, keyboard timings, or Gleipnir (`bin/touch_master_manager.py`).
   Its sensitivity range (0.2 to 3.0) differs from the panel (0.5 to 3.5) and the driver (0.2 to 5.0).
9. **Brightness failures are not reported for the top panel.** `set_top_brightness` ignores the result of its write
   (`bin/system_stats.py:403-409`); only the bottom path records `last_write_ok` (`:415-426`).
10. **Gleipnir view depends on a separate program** and reads its output format (`bin/gleipnir_view.py:30-47`).
11. **Single digitizer.** Only the first node whose name contains "bottom" and "touchscreen" is used (`bin/thor_app.py:656-665`).
12. **Uninstall does not hand the bottom screen back.** Stopping Ratatoskr from the tray, the manager or the Decky toggle
    starts Armada's session again (W-03). The manual uninstall in `docs/installation.md` disables the service and removes
    files, and it tells the user to run `enable --now armada-bottom-screen.service` afterwards.

## Known issues and open defects

These are defects or gaps found by reading the code. None has been reproduced in this review.

| ID | Defect | Where | Effect if hit | Status |
|---|---|---|---|---|
| K-01 | `DebugCode.ERR_SERVICE_START` and `ERR_SERVICE_STOP` are used but not defined in the enum | `main.py:199`, `main.py:235`, `bin/thor_app.py:488`; `debug_codes.py:12-117` | Reading an undefined `IntEnum` attribute raises `AttributeError`. In `main.py` that can stop `_main` or the `_run_systemctl` failure path. In `cleanup()` a failing step raises inside its `except` and stops the remaining cleanup steps | verified by grep; **not executed** |
| K-02 | The narrow sudo rule does not allow the saved-level file, which the bottom backlight write also needs | `bin/system_stats.py:415-426`, `systemd/touch-master-backlight.sudoers:7-8` | With only the rule installed, bottom brightness writes and dims report failure and log `DBG-701` | by reading; the docs call the rule untested |
| K-03 | Top-panel brightness write failures are not reported | `bin/system_stats.py:403-409` | A failed top write is silent | by reading |
| K-04 | The panel and manager text describe the older Steam-delay design | see mismatch 5 | Users expect a Steam-delay dim | by reading |
| K-05 | `STATUS_EDGE_SCROLL = 521` is still defined and described as "Edge scrollbar active", while the README says 521 is reserved | `debug_codes.py:54`, `README.md` (diagnostic codes table) | Cosmetic | by reading |
| K-06 | `main.py` hard-codes the socket path with UID 1000; the driver uses the real UID | `main.py:25`, `bin/thor_app.py:73` | The Decky side cannot reach a driver run by another UID | by reading; the Thor's user is UID 1000 per the docs |
| K-07 | `bin/gleipnir_view.py:174` cites `docs/hardware/device-observed.md`, which is not in this repository | `bin/gleipnir_view.py:174` | Dangling reference in a comment | by grep |
| K-08 | `tests/test_system_stats.py` says it also runs as `devcheck.sh` on the Thor; that script is not in the repository | `tests/test_system_stats.py` header | The on-device run described in the header cannot be reproduced from this repo | by grep |
| K-09 | `docs/configuration.md` describes the dim mirror as reading Steam's `config.vdf` as current behaviour | `docs/configuration.md:34` | Misleading; the code reads no Steam file | by grep (no reference in code) |
| K-10 | The IPC socket bind is not guarded. `DBG-301` is defined and never emitted | `bin/thor_app.py:915-917`, `debug_codes.py:36` | A failed bind raises out of `start()` and the driver exits without a `DBG-301` line | by reading |
| K-11 | `DBG-701` for slider failures and `DBG-702` for volume failures are documented, but only the dim path emits `DBG-701`, and nothing emits `DBG-702` | `docs/troubleshooting.md` (the DBG-701 and DBG-702 rows), `bin/system_stats.py` (no logger), `bin/dim_mirror.py` | A slider that does nothing leaves no log line of its own | by grep |

## Documentation and code mismatches found in this review

Each item states what the existing `docs/` page says, what the code does, and where. Nothing has been changed in
`docs/` by this spec.

1. **Fallback digitizer node.** `docs/architecture.md:35` says the digitizer is found by name "(fallback `/dev/input/event5`)".
   `_find_bottom_touchscreen` returns the first match on name and `None` otherwise (`bin/thor_app.py:656-665`); there is no
   fallback to `event5`, and the driver retries every 5 s instead (`bin/thor_app.py:509-510`).
2. **Tests on deploy.** `docs/development.md` says the deploy routine runs the tests on the Thor. `scripts/deploy.sh` copies
   and restarts; it has no test step (`scripts/deploy.sh:18-73`).
3. **Steam config as a dim input.** `docs/configuration.md:34` says the dim mirror reads `IdleBacklightDimBatterySeconds`
   and `IdleBacklightDimACSeconds` from Steam's `config.vdf`. No code reads that file or those keys (grep of the repo).
   `docs/dim-mirror.md` says the first version did that and the current one does not.
4. **Open-button distance.** `docs/usage.md` ("Hide and Open") says to tap "within about 2 cm of the Open button (24 px around it)".
   The code uses `OPEN_HIT_PAD = 24` px (`bin/thor_app.py:92`). The driver's own scale is about 16.5 px per mm
   (`bin/thor_app.py:75-76`), so 24 px is about 1.5 mm. The "2 cm" figure is not supported by the code.
5. **Dim description in the panel and manager.** The Decky panel says the dim "dims the bottom screen after Steam's idle-dim
   delay ... and restores it on any input" (`dist/index.js:490-491`). The manager labels the switch "Dim bottom screen with
   Steam's idle dim" (`bin/touch_master_manager.py:230`). The code follows the top backlight, not Steam's delay
   (`bin/dim_mirror.py:1-12`), as `docs/dim-mirror.md` also says.
6. **What restores the dim.** `docs/dim-mirror.md` (step 3) says the bottom is restored "when the bottom screen is touched".
   The code restores on any input the idle tracker sees within the last second, which includes other input devices
   (`bin/dim_mirror.py:402-403`, `bin/dim_mirror.py:134-138`). The touch path is the one the driver calls `poke()` for
   (`bin/thor_app.py:570`).
7. **Name of the sudoers file.** `docs/installation.md` installs the file as `/etc/sudoers.d/92-ratatoskr-backlight`. The
   file's own install comment names `92-touch-master-backlight` (`systemd/touch-master-backlight.sudoers:6`). Both
   work, but the two should agree.
8. **Narrow rule scope.** `docs/installation.md` says the narrow rule "allows only those two files". That is accurate, and
   it omits the saved-level file that the driver writes too (defect K-02).
9. **Architecture thread list.** `docs/architecture.md` ("Threads in the driver") lists the GTK main thread, touch reader,
   IPC server, key repeat, glide, idle tracker and dim mirror, with hardware stats sampled on a cache. The code also
   starts a stats sampler thread (`bin/thor_app.py:426`, `bin/system_stats.py:204-219`), four writer threads
   (`bin/system_stats.py:160-165`) and a Gleipnir thread that is started at launch and polls only while the view is on
   (`bin/thor_app.py:432`, `:284-298`).
10. **Keyboard layout wording.** `README.md` calls the keyboard a "5-row thumb layout". The code lays out five rows of a
    full QWERTY-style keyboard, not a thumb layout (`bin/keyboard_layout.py:94-192`).
11. **Decky button label.** `docs/installation.md` and the other pages say "Run Diagnostics". The panel's button reads
    "Run Self-Test Diagnostics" (`dist/index.js:597`). Cosmetic.
13. **Slider failure codes.** `docs/troubleshooting.md` says a brightness slider that does nothing logs `DBG-701`, and a
    volume slider that does nothing logs `DBG-702`. Only the dim path imports the code registry and logs `DBG-701`
    (`bin/dim_mirror.py`); `bin/system_stats.py` does not log at all, and nothing emits `DBG-702` (K-11).
14. **Burn-in orbit shape.** `CHANGELOG.md` (AMOLED entry) calls the burn-in shift a "circular" shift. The code moves
    x at one rate and y at 1.5 times that rate (`bin/burn_in.py:49-51`), which is a Lissajous path.

## Glossary

| Term | Meaning | Where |
|---|---|---|
| Ratatoskr | the project's current name; formerly Touch Master. In Norse myth the squirrel that carries messages up and down Yggdrasil | `README.md` |
| Armada OS | the Thor's operating system build that Ratatoskr targets | `README.md` |
| Decky Loader | the plugin loader that shows the Ratatoskr panel in Steam | `README.md`, `main.py` |
| Game Mode | Steam's game session on the top screen, run by gamescope | `bin/session_cursor.py` |
| gamescope | the compositor for each screen session; hides the pointer after `--hide-cursor-delay` | `bin/session_cursor.py`, `bin/engine.py:77-84` |
| Bottom screen | the 3.92-inch AMOLED panel that Ratatoskr draws on | [03](03-hardware-targets.md) |
| Digitizer | the bottom touchscreen's input device, grabbed exclusively | `bin/thor_app.py:515-517` |
| evdev | Linux's input event interface, `/dev/input/event*` | `bin/touch_frames.py` |
| `EVIOCGRAB` | ioctl that gives one process exclusive reads of an input device | `bin/thor_app.py:516` |
| uinput | Linux's interface for creating virtual input devices, `/dev/uinput` | `bin/engine.py:23` |
| MT slot, tracking id | multitouch slot number and the id of the contact in it | `bin/touch_frames.py:19-22` |
| `SYN_REPORT`, `SYN_DROPPED` | end-of-frame marker and the kernel's "buffer overflowed, state lost" marker | `bin/touch_frames.py:17-18` |
| Frame | the contacts that changed at one `SYN_REPORT` | `bin/touch_frames.py:26-32` |
| Contact | one finger as the engine tracks it | `bin/engine.py:369` |
| Stale contact | a contact silent for 1.5 s, treated as lifted | `bin/engine.py:89`, `:497-511` |
| Misuse lock | the state that ignores touches from the fourth finger until all lift | `bin/engine.py:95`, `:589-597` |
| Glide | momentum after a flick | `bin/engine.py:814-844` |
| Strip | the right-hand or bottom edge in Pen mode that scrolls | `bin/engine.py:96-103` |
| Pen, Pen + | Pen mode; Pen + also keeps Game Mode's pointer visible | `bin/pen_mode.py` |
| Nudge | a one-pixel out-and-back pointer move that wakes a hidden pointer | `bin/engine.py:206-214` |
| Latched, locked | a modifier that applies to the next key only, and one that stays on | `bin/modifiers.py:1-16` |
| Quick Controls | the settings screen with sliders and buttons | `bin/thor_app.py:1361` |
| Ribbon | the status row under the header | `bin/thor_app.py:1128` |
| Hide, Open | blank the UI except an Open button, and the button that brings it back | `bin/thor_app.py:316-325` |
| Idle veil | the black overlay that dims lit pixels after 30 s without touch | `bin/burn_in.py:66-74` |
| Orbit | the 1.5 px circular shift of the whole UI for burn-in | `bin/burn_in.py:46-52` |
| Steam idle dim | Steam's ramp of the top backlight when the screen is idle; the thing Ratatoskr mirrors | `docs/dim-mirror.md` |
| Top follower | the pure logic that decides dim and restore from the top backlight | `bin/top_follower.py` |
| Dim mirror | the thread that applies the dim to the bottom backlight | `bin/dim_mirror.py` |
| Saved level | Armada's stored bottom brightness, re-applied every 2 s by its root service | `bin/dim_mirror.py:49-51` |
| Recovery file | the pre-dim bottom level, kept until restored | `bin/dim_mirror.py:52-53` |
| Gleipnir | a separate charge-limiting project; Ratatoskr shows its status only | `bin/gleipnir_view.py` |
| IPC socket | the UNIX socket the Decky backend and the manager talk to | `bin/thor_app.py:908-926` |
| `DBG-nnn` | a numbered diagnostic code | `debug_codes.py` |
| Decky panel | the Quick Access Menu plugin UI, `dist/index.js` | `dist/index.js` |
| Manager | `bin/touch_master_manager.py`, the standalone window and CLI | `bin/touch_master_manager.py` |
| Release zip | the Armada Store archive with the driver under `driver/` | `scripts/build-release.py` |
