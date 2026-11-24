#!/usr/bin/env python3
"""Build Ratatoskr.zip, the Decky plugin archive the Armada Store installs.

One top-level folder, thor-input/ (the name existing installs use, so a Store install replaces a deploy.sh install
instead of loading a second copy). It holds the plugin files plus the driver under driver/, which main.py copies into
the user's home on first load (see _sync_driver). Files come from git (committed content, LF), not the working tree,
except the panel: dist/index.js is built here with pnpm install --frozen-lockfile and pnpm run build, the way Decky's
builder does, so run this in a clean checkout of the tag.

Usage: python scripts/build-release.py [OUT.zip]      default: release/Ratatoskr.zip
Set PNPM to pnpm's path when it is not on PATH.
"""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "thor-input"
# source path in the repo -> path inside the archive (below thor-input/)
MAP = {
    "plugin.json": "plugin.json", "package.json": "package.json", "main.py": "main.py", "debug_codes.py": "debug_codes.py",
    "LICENSE": "LICENSE",
    "systemd/touch-master.service": "driver/systemd/touch-master.service",
    "touch-master.desktop": "driver/share/touch-master.desktop",
    "touch-master-stop.desktop": "driver/share/touch-master-stop.desktop",
    "touch-master.svg": "driver/share/touch-master.svg",
}


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


BUILD_INPUTS = ["src", "package.json", "pnpm-lock.yaml", "rollup.config.js", "tsconfig.json", "plugin.json"]


def build_panel() -> bytes:
    """Build dist/index.js from the committed sources and return it."""
    if git("status", "--porcelain", "--", *BUILD_INPUTS).strip():
        sys.exit("the panel sources differ from HEAD; build from a clean checkout of the tag")
    pnpm = shutil.which(os.environ.get("PNPM", "pnpm"))
    if not pnpm:
        sys.exit("pnpm not found: put it on PATH or set PNPM to its path")
    for args in (["install", "--frozen-lockfile"], ["run", "build"]):
        subprocess.run([pnpm, *args], cwd=ROOT, check=True)
    return (ROOT / "dist" / "index.js").read_bytes()


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
    contents = {dst: git("show", f"HEAD:{src}") for src, dst in files.items()}
    contents["dist/index.js"] = build_panel()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dst, data in sorted(contents.items()):
            info = zipfile.ZipInfo(f"{TOP}/{dst}", date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (0o755 if dst.endswith(".desktop") else 0o644) << 16
            z.writestr(info, data, zipfile.ZIP_DEFLATED)
    print(f"{out}: {len(contents)} files, top-level folder {TOP}/")


if __name__ == "__main__":
    main()
