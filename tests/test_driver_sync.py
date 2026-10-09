"""The release zip ships the driver under driver/; main.py copies it into the user's home when it is missing or differs."""
import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(home: Path, plugin_dir: Path):
    os.environ["RATATOSKR_HOME"] = str(home)
    sys.modules.pop("main", None)
    m = importlib.import_module("main")
    m.PLUGIN_DIR = plugin_dir
    m.DRIVER_SRC = plugin_dir / "driver"
    return m


def build_plugin(plugin: Path) -> None:
    (plugin / "driver/bin").mkdir(parents=True)
    (plugin / "driver/systemd").mkdir()
    (plugin / "driver/share").mkdir()
    (plugin / "driver/bin/thor_app.py").write_text("print('app')\n")
    (plugin / "driver/bin/touch_master_manager.py").write_text("print('mgr')\n")
    (plugin / "driver/bin/engine.py").write_text("X = 1\n")
    (plugin / "debug_codes.py").write_text("Y = 2\n")
    (plugin / "driver/systemd/touch-master.service").write_text("[Service]\n")
    for n in ("touch-master.desktop", "touch-master-stop.desktop", "touch-master.svg"):
        (plugin / "driver/share" / n).write_text(n)


def test_no_driver_folder_does_nothing():
    with tempfile.TemporaryDirectory() as d:
        home, plugin = Path(d) / "home", Path(d) / "plugin"
        home.mkdir(); plugin.mkdir()
        m = load(home, plugin)
        r = m._sync_driver()
        assert r["any"] is False and not any(home.iterdir()), r


def test_first_install_copies_everything_and_sets_modes():
    with tempfile.TemporaryDirectory() as d:
        home, plugin = Path(d) / "home", Path(d) / "plugin"
        home.mkdir(); plugin.mkdir(); build_plugin(plugin)
        m = load(home, plugin)
        r = m._sync_driver()
        assert r["bin"] and r["unit"] and r["any"] and not r["errors"], r
        app = home / ".local/share/thor-input"
        assert (app / "bin/thor_app.py").read_text() == "print('app')\n"
        assert (app / "bin/engine.py").is_file() and (app / "debug_codes.py").read_text() == "Y = 2\n"
        assert oct((app / "bin/thor_app.py").stat().st_mode & 0o777) == "0o755"
        assert oct((app / "bin/engine.py").stat().st_mode & 0o777) == "0o644"
        assert (home / ".config/systemd/user/touch-master.service").is_file()
        assert (home / ".local/share/applications/touch-master.desktop").is_file()
        assert (home / ".local/share/icons/hicolor/scalable/apps/touch-master.svg").is_file()
        assert not list(home.rglob("*.tmp"))


def test_second_run_is_a_no_op_and_an_update_reports_what_changed():
    with tempfile.TemporaryDirectory() as d:
        home, plugin = Path(d) / "home", Path(d) / "plugin"
        home.mkdir(); plugin.mkdir(); build_plugin(plugin)
        m = load(home, plugin)
        m._sync_driver()
        assert m._sync_driver()["any"] is False
        (plugin / "driver/bin/engine.py").write_text("X = 2\n")
        r = m._sync_driver()
        assert r["bin"] is True and r["unit"] is False, r
        (plugin / "driver/systemd/touch-master.service").write_text("[Service]\nRestart=always\n")
        r = m._sync_driver()
        assert r["unit"] is True and r["bin"] is False, r


def test_a_bad_file_is_reported_and_does_not_stop_the_rest():
    with tempfile.TemporaryDirectory() as d:
        home, plugin = Path(d) / "home", Path(d) / "plugin"
        home.mkdir(); plugin.mkdir(); build_plugin(plugin)
        (home / ".config").write_text("not a directory")   # the unit cannot be written under a file
        m = load(home, plugin)
        r = m._sync_driver()
        assert r["errors"], r
        assert (home / ".local/share/thor-input/bin/thor_app.py").is_file()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
