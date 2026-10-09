"""Write a JSON file so that a reader, a crash or a second writer never sees half of it.

config.json is rewritten by three processes: the driver, the Decky backend (which runs as root) and the manager. Writing it
in place can leave a truncated file if the process dies mid-write. This writes a temporary file next to it, flushes it to
disk and renames it over the original. The original's owner and mode are kept: the Decky backend runs as root, and a
root-owned replacement would lock the user-level driver out of its own config.

main.py carries a copy of this function, because only main.py (and debug_codes.py) are installed in the Decky plugin
folder; tests/test_atomic_json.py runs the same checks against both.
"""
from __future__ import annotations

import json
import os
import tempfile


def write_json_atomic(path, data, indent: int = 2) -> None:
    path = os.fspath(path)
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    payload = json.dumps(data, indent=indent)  # serialise first: a failure here leaves the file alone
    try:
        ref = os.stat(path)
    except OSError:
        ref = os.stat(folder)  # a new file takes the folder's owner
        ref_mode = None
    else:
        ref_mode = ref.st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, ref_mode if ref_mode is not None else 0o644)
        chown = getattr(os, "chown", None)
        if chown is not None:
            try:
                chown(tmp, ref.st_uid, ref.st_gid)
            except OSError:
                pass  # not allowed to (not root) or not needed: the owner is already the caller
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
