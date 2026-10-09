#!/usr/bin/env python3
"""Build Ratatoskr.zip, the Decky plugin archive the Armada Store installs.

One top-level folder, thor-input/ (the name existing installs use, so a Store install replaces a deploy.sh install
instead of loading a second copy). It holds the plugin files plus the driver under driver/, which main.py copies into
the user's home on first load (see _sync_driver). Files come from git (committed content, LF), not the working tree.

Usage: python scripts/build-release.py [OUT.zip]      default: release/Ratatoskr.zip
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "thor-input"
# source path in the repo -> path inside the archive (below thor-input/)
MAP = {
    "plugin.json": "plugin.json", "package.json": "package.json", "main.py": "main.py", "debug_codes.py": "debug_codes.py",
    "dist/index.js": "dist/index.js", "LICENSE": "LICENSE",
    "systemd/touch-master.service": "driver/systemd/touch-master.service",
    "touch-master.desktop": "driver/share/touch-master.desktop",
    "touch-master-stop.desktop": "driver/share/touch-master-stop.desktop",
    "touch-master.svg": "driver/share/touch-master.svg",
}


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "release" / "Ratatoskr.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    tracked = set(git("ls-files").decode().split("\n"))
    files = dict(MAP)
    for name in sorted(tracked):
        if name.startswith("bin/") and name.endswith(".py"):
            files[name] = "driver/" + name
    missing = [s for s in files if s not in tracked]
    if missing:
        sys.exit("not tracked by git: " + ", ".join(missing))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for src, dst in sorted(files.items(), key=lambda kv: kv[1]):
            data = git("show", f"HEAD:{src}")
            info = zipfile.ZipInfo(f"{TOP}/{dst}", date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (0o755 if src.endswith((".desktop",)) else 0o644) << 16
            z.writestr(info, data, zipfile.ZIP_DEFLATED)
    print(f"{out}: {len(files)} files, top-level folder {TOP}/")


if __name__ == "__main__":
    main()
