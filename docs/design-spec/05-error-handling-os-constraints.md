# 05 - Error handling, recovery and OS constraints

## Error handling by component

| Component | Failure | What happens | Log code | Source |
|---|---|---|---|---|
| Touchscreen node missing | no node named "bottom" and "touchscreen" | retry in 5 s, indefinitely | `DBG-201` | `bin/thor_app.py:507-511` |
| Touchscreen open denied | `PermissionError` | retry in 5 s | `DBG-202` | `bin/thor_app.py:519-527` |
| `EVIOCGRAB` fails | another holder, or other `OSError` | close the descriptor, retry in 5 s | `DBG-203` | `bin/thor_app.py:519-529` |
| `select` on the device fails | `OSError` or `ValueError` | restart the service (`_device_lost`), unless shutting down | `DBG-204` | `bin/thor_app.py:539-546` |
| Read on the device fails with `ENODEV`, `EIO`, `EBADF`, `ENOENT` | device gone | restart the service with exit code 1 | `DBG-204` | `bin/thor_app.py:555-563`, `:651-654` |
| Other read error | `OSError` | log, sleep 50 ms, continue | `DBG-204` | `bin/thor_app.py:564-566` |
| A frame handler raises | any exception | log at most every 5 s, keep reading with the grab held | `DBG-204` | `bin/thor_app.py:572-580` |
| `SYN_DROPPED` | kernel buffer overflow | reset gesture state, end key press, release UI button, resync slots | `DBG-204` | `bin/thor_app.py:594-604` |
| Slot read fails during resync | `OSError` or `struct.error` | log, leave the state empty | `DBG-204` | `bin/thor_app.py:641-645` |
| `/dev/uinput` open or setup fails | `OSError` | raised from `UInputBridge.__init__`; logged with `DBG-101` or `DBG-102` | `DBG-101`, `DBG-102` | `bin/engine.py:142-185` |
| Virtual device write fails | `OSError` | log, the event is lost; the key or button stays in the held set until a release succeeds | `DBG-104` | `bin/engine.py:200-204`, `:291-294`, `:270-273` |
| IPC request malformed, unknown, or too slow | see [04](04-ipc-data-flow.md) | reply `303` or time out with no reply | `DBG-303` | `bin/thor_app.py:1016-1021` |
| IPC client cannot connect | socket missing or refused | client returns `{"ok": false, "code": 302}` or `304` | none in the client | `main.py:35-57` |
| Config file unreadable or not JSON | `ValueError`, `OSError` | the defaults are used; the driver logs `save_config` or `load_config` failures under `DBG-303` | `DBG-303` | `bin/thor_app.py:222-223`, `:247-248` |
| Config write fails | `OSError` | the driver logs it under `DBG-303`; the Decky backend and the manager ignore it silently. The in-memory value still applies in the driver | `DBG-303` (driver only) | `bin/thor_app.py:247-248`, `main.py:183-187`, `bin/touch_master_manager.py:70-71` |
| Backlight write denied | `PermissionError` | `sudo -n tee`; if that fails, `last_write_ok = False` | `DBG-701` (dim only) | `bin/system_stats.py:68-76`, `bin/dim_mirror.py:348-357` |
| Backlight write, sudo times out | 2 s | the value is read back; it counts as written only if it matches | none | `bin/system_stats.py:58-62` |
| Brightness write failure, top | any | ignored; no status is kept | none | `bin/system_stats.py:403-409` |
| Volume `wpctl` fails or times out | `OSError`, `TimeoutExpired` | volume shown as 0 in the sample | `DBG-702` is defined but not used by the code | `bin/system_stats.py:315-332`, `:367-391` |
| Gleipnir status fails | not installed, bad output, timeout | the view shows "not installed or not answering" or "off" | none | `bin/gleipnir_view.py:30-47`, `bin/thor_app.py:1162` |
| Dim recovery write fails | `OSError` or sudo fails | retry every 5 s, log at most every 30 s | `DBG-701` | `bin/dim_mirror.py:280-311`, `:380-382` |
| Dim record cannot be written | `OSError` | log `DBG-701`, continue | `DBG-701` | `bin/dim_mirror.py:262-270` |
| Idle tracker cannot list devices | exception | log `DBG-610`, skip this scan | `DBG-610` | `bin/dim_mirror.py:150-156` |
| Idle tracker select fails | `OSError`, `ValueError` | drop every descriptor; the next scan reopens them | none | `bin/dim_mirror.py:194-199` |
| Decky `systemctl` fails | non-zero exit or exception on both forms | logs `ERR_SERVICE_START` or `ERR_SERVICE_STOP` (undefined, see note below) | undefined | `main.py:214-238` |
| Tray stop | the command cannot be started | logs `DBG-303` with the error text | `DBG-303` | `bin/thor_app.py:399-401` |
| Driver socket bind at start | `OSError` (for example a stale file that cannot be removed) | not caught; the exception leaves `start()` and the process exits | `DBG-301` is defined but never emitted | `bin/thor_app.py:908-917`, `debug_codes.py:36` |
| Cleanup step fails | any exception | log, continue with the next step (intended) | `ERR_SERVICE_STOP` (undefined, see below) | `bin/thor_app.py:484-488` |

**Undefined codes.** `main.py` (lines 199 and 235) and `bin/thor_app.py` (line 488) use `DebugCode.ERR_SERVICE_START` and
`DebugCode.ERR_SERVICE_STOP`. `debug_codes.py` does not define them. The intent of `cleanup`'s per-step guard is that a
failing step is logged and the rest still run; with an undefined code, the logging call inside `except` raises first.
This is from reading the code, not from running it ([06](06-design-decisions-roadmap.md#open-work)).

## Retries and timeouts

| Operation | Timeout or retry | Source |
|---|---|---|
| Touchscreen open and grab | every 5 s, forever | `bin/thor_app.py:509-530`, `:585-588` |
| Driver restart after device loss | systemd, after 2 s (`RestartSec=2`), no start limit (`StartLimitIntervalSec=0`) | `systemd/touch-master.service:6`, `:11-12` |
| Dim recovery | every 5 s until it succeeds | `bin/dim_mirror.py:380-382` |
| Dim fade failure | next attempt after 60 s | `bin/dim_mirror.py:351` |
| Dim restore failure | every 0.25 s pass, log at most every 30 s | `bin/dim_mirror.py:314-329`, `:376-404` |
| `sudo -n tee` | 2 s, then read back | `bin/system_stats.py:39`, `:48-62` |
| IPC request to driver | 2 s from the client, 2 s to complete on the driver | `main.py:35-57`, `bin/ipc_util.py:18` |
| IPC reply from driver | 2 s from the client | `bin/ipc_util.py:46-64` |
| Manager IPC | 1.0 s | `bin/touch_master_manager.py:74` |
| Panel `set_enabled` wait | 3 s | `main.py` `set_enabled` |
| `systemctl` from the backend | 5 s per form | `main.py:214-238` |
| Gleipnir CLI | 3 s; the `systemctl is-active` check 2 s | `bin/gleipnir_view.py:36`, `:43` |
| `wpctl` read | 0.4 s | `bin/system_stats.py:319` |
| `wpctl` write | 0.5 s | `bin/system_stats.py:370`, `:387` |
| Driver shutdown wait for dim thread | 2 s | `bin/dim_mirror.py:252-259` |
| Idle tracker scan | every 5 s | `bin/dim_mirror.py:119` |

## Shutdown

Signals: SIGINT and SIGTERM call `request_quit`, which logs and leaves the GTK main loop (`bin/thor_app.py:454-459`,
`:1613-1614`). systemd sends SIGTERM on stop and restart. The default action would end the process before cleanup
(the comment at `bin/thor_app.py:1605-1606`).

`cleanup()` (`bin/thor_app.py:475-500`) runs once (`_cleaned`), and each step is guarded by `step()`:

1. dim mirror stop: sets the stop event, waits up to 2 s, restores the bottom level and clears the record;
2. idle tracker stop;
3. stats sampler stop;
4. key repeat stop;
5. the stop events for the touch reader, Gleipnir and IPC are set;
6. the IPC socket file is removed;
7. the touchscreen grab is released and the descriptor closed (`_release_touch_device`, `:461-473`);
8. the virtual devices are closed: all held buttons and keys are released first (`bin/engine.py:331-347`).

`main()` calls `cleanup()` in a `finally` as well (`bin/thor_app.py:1616-1619`). The exit code is 1 when the device was
lost, otherwise 0 (`:1620`).

## Recovery

| Situation | Recovery | Source |
|---|---|---|
| Crash or kill during a dim | the record is read on the next start and the saved level is put back; retried every 5 s on failure | `bin/dim_mirror.py:280-311`, `:333` |
| Restart during Steam's idle dim | the first sample at the floor starts a dim; the restore comes with the next rise or input | `bin/top_follower.py:171-174` |
| Lost touch device | exit 1; systemd restarts the service; the new process grabs the node again | `bin/thor_app.py:561-563`, `:651-654` |
| Stuck fingers (lost lift) | 1.5 s silence drops the contact | `bin/engine.py:497-511` |
| Stuck held button or key after an error | `release_all` on close; a failed release is kept in the held set | `bin/engine.py:311-316`, `:270-273`, `:292` |
| Driver out of date after a deploy | the Decky backend restarts it when the code or unit changed (release zip) | `main.py:197-205` |
| Stale socket file | removed before bind on start, and on cleanup | `bin/thor_app.py:909-913`, `:497` |
| Brightness write that failed | the bottom path reports `last_write_ok` false; the dim does not record success | `bin/system_stats.py:415-426` |

Recovery is local and automatic. Nothing rolls back a configuration change, because the file is replaced atomically and
the last good version is what remains on disk if a write is interrupted (`bin/atomic_json.py:18-49`).

## Atomic JSON write

`write_json_atomic` (`bin/atomic_json.py:18-49`), in order:

1. serialise the data first, so an encoding error leaves the file alone;
2. stat the existing file for owner and mode; a new file takes the folder's owner and mode 0644;
3. create a temp file in the same folder (`mkstemp`, a name with `.tmp` and the original name);
4. write, flush and `fsync` it;
5. set the mode and, if the module can chown, the owner, to match the original;
6. `os.replace` over the original.

If any step fails, the temp file is removed and the exception is raised. The copy in `main.py` (`:149-180`) is the same,
with `newline="\n"`. `tests/test_atomic_json.py` checks the copy and the original (`test_concurrent_writers_never_leave_a_torn_file`,
`test_the_original_mode_and_owner_are_kept`).

The `session_cursor` override file is written with a plain temp file and `os.replace`, without the fsync
(`bin/session_cursor.py:223-225`). It is small and rewritten on each change.

## Driver state files

| File | Written when | Read when | Failure behaviour |
|---|---|---|---|
| `config.json` | every change | start, and by the Decky backend and manager on each call | defaults are used if unreadable |
| dim recovery record | a dim starts; removed on restore | start | an unreadable record is deleted |
| Pen + override | Pen + on or off | every status check (cached 10 s) | a write failure returns `False`; the pen hint says the override is pending |

## OS and Armada constraints

| Constraint | How the code deals with it | Source |
|---|---|---|
| Only one process can read the touchscreen at a time (`EVIOCGRAB`) | the driver grabs it and Armada's bottom session is disabled while the driver runs (`Conflicts=`) | `systemd/touch-master.service:5`, `bin/thor_app.py:515-517`; `docs/troubleshooting.md` |
| `/dev/uinput` must be writable by the user | checked by the self-test; the driver fails to start if it cannot open it | `debug_codes.py:147-152`, `bin/engine.py:142-147` |
| Backlights are root-only | `sudo -n tee` fallback and the optional narrow rule | `bin/system_stats.py:43-76`, `systemd/touch-master-backlight.sudoers` |
| Armada's root service re-applies the saved bottom level every 2 s | the dim writes the saved file as well | `bin/dim_mirror.py:49-50`, `:337-347` (citing Armada's `armada-control`, **unverified** here) |
| Suspend and resume | timers use `CLOCK_BOOTTIME` where available, so a sleep is a gap and not a fall | `bin/dim_mirror.py:45-48`; the rest of sleep handling is **unverified** |
| The Thor's pointer hides after 3 s in Game Mode | the nudge, or Pen + | `bin/engine.py:77-84`, `bin/session_cursor.py` |
| Steam blanks the top screen just before a suspend | a single large drop is not treated as a dim | `bin/top_follower.py:178-180` |
| Decky loads the plugin as root and the driver must run as `armada` | the backend uses `--machine=armada@.host` first, so `systemctl --user` reaches the user session | `main.py:214-238` |
| The user session's bus and runtime directory | the backend sets `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` to the UID 1000 paths; the manager sets them when missing | `main.py:215-217`, `bin/touch_master_manager.py:21-26` |
| PipeWire needs `XDG_RUNTIME_DIR` for `wpctl` | `_wpctl_env` sets it from the UID if it is missing | `bin/system_stats.py:79-84` |
| The bottom gamescope environment | the self-test checks for the file `/run/user/<uid>/armada-bottom-env` | `debug_codes.py:189-191` |
| Python version | the modules use `from __future__ import annotations`, which defers most annotations. `Event = tuple[int, bool]` (`bin/modifiers.py:95`) is an assignment and is evaluated at import, so Python 3.9 or later is needed. **Unverified**: which Python Armada ships | `bin/modifiers.py:95` |
| Linux-only calls | `os.chown`, `fcntl`, `CLOCK_BOOTTIME`, `EVIOCGRAB`, `/proc` are Linux; `fcntl` is optional in the engine, and `os.chown` is checked with `getattr` | `bin/engine.py:15-18`, `bin/atomic_json.py:44-45`, `bin/dim_mirror.py:48` |
| Fonts and emoji | the Thor's fonts do not draw emoji, so the ribbon uses short text labels | `bin/thor_app.py:1146` (comment) |
| Burn-in on AMOLED | pure black, no fills, orbit, hint fade, idle veil | [03](03-timing-idle-throttling-dim.md#burn-in) |
