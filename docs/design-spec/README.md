# Ratatoskr design spec

How each part of Ratatoskr works: the processes and modules, the touch path, the timing constants, the idle and dim
logic, the IPC message formats, error handling, the OS constraints it works under, and the reasons behind the main
decisions.

Written from a read of the code at `origin/main` commit `2447189` on 2026-10-22. Anchors are `file:line`. A statement that
rests on the author's notes or on an observation recorded in `docs/` is marked as such. Anything not traced in the code
or confirmed on a device is marked **unverified**. The companion [application spec](../application-spec/README.md) says
what the product does and what it requires.

| # | File | Subsystem / topic |
|---|---|---|
| 01 | [01-architecture-modules.md](01-architecture-modules.md) | Processes, modules, threads, locks, component diagram |
| 02 | [02-touch-path.md](02-touch-path.md) | Touch frame format, parser, resync, screen transform, routing, gesture state machine |
| 03 | [03-timing-idle-throttling-dim.md](03-timing-idle-throttling-dim.md) | Timing constants, burn-in, idle tracking, dim follower and mirror, throttles |
| 04 | [04-ipc-data-flow.md](04-ipc-data-flow.md) | IPC message formats, panel polling and merging, config write path, sequence diagrams |
| 05 | [05-error-handling-os-constraints.md](05-error-handling-os-constraints.md) | Failure handling, retries, timeouts, shutdown, OS and Armada constraints |
| 06 | [06-design-decisions-roadmap.md](06-design-decisions-roadmap.md) | Decisions with rejected alternatives, and open work |
