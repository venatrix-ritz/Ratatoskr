"""Commands the driver's tray menu runs.

Stopping touch-master.service kills every process in its control group, including children the driver started. The
Stop action has to carry on after that, to hand the bottom screen back to Armada's stock Plasma session
(armada-bottom-screen.service) exactly as the manager's --stop and the Decky panel do. So it runs the manager in a
transient unit of its own, outside the service's group.
"""
from __future__ import annotations


def stop_command(manager_script: str, python: str) -> list[str]:
    return ["systemd-run", "--user", "--collect", "--quiet", python, manager_script, "--stop"]
