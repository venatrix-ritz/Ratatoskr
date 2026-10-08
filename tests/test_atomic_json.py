"""Tests for atomic config writes (run: python tests/test_atomic_json.py). Temp dirs only."""
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import atomic_json as aj  # noqa: E402
import main as decky  # noqa: E402  (the Decky backend carries its own copy)

WRITERS = {"bin/atomic_json.py": aj.write_json_atomic, "main.py": decky._write_json_atomic}


def each(fn):
    def run():
        for name, w in WRITERS.items():
            try:
                fn(w)
            except AssertionError as err:
                raise AssertionError(f"{name}: {err}") from None
    run.__name__ = fn.__name__
    return run


@each
def test_writes_valid_json_and_creates_the_folder(w):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sub", "config.json")
        w(p, {"a": 1, "b": [1, 2]})
        assert json.load(open(p, encoding="utf-8")) == {"a": 1, "b": [1, 2]}
        assert os.listdir(os.path.join(d, "sub")) == ["config.json"]       # no temp file left behind


@each
def test_a_failed_serialisation_leaves_the_old_file_untouched(w):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "config.json")
        w(p, {"keep": True})
        try:
            w(p, {"bad": object()})
            raise AssertionError("expected TypeError")
        except TypeError:
            pass
        assert json.load(open(p, encoding="utf-8")) == {"keep": True}
        assert os.listdir(d) == ["config.json"]


@each
def test_a_failure_while_renaming_removes_the_temp_file_and_keeps_the_old_one(w):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "config.json")
        w(p, {"keep": True})
        real = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            try:
                w(p, {"new": True})
                raise AssertionError("expected OSError")
            except OSError:
                pass
        finally:
            os.replace = real
        assert json.load(open(p, encoding="utf-8")) == {"keep": True}
        assert os.listdir(d) == ["config.json"]


@each
def test_concurrent_writers_never_leave_a_torn_file(w):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "config.json")
        w(p, {"n": 0})
        stop = threading.Event()
        torn = []

        def reader():
            while not stop.is_set():
                try:
                    with open(p, encoding="utf-8") as f:
                        json.load(f)
                except (FileNotFoundError, PermissionError):  # PermissionError: Windows, while the file is being replaced
                    pass
                except ValueError as err:
                    torn.append(err)

        def writer(k):
            import time
            for i in range(40):
                for _ in range(200):  # Windows refuses to replace a file another thread has open; Linux never does
                    try:
                        w(p, {"writer": k, "i": i, "pad": "x" * 2000})
                        break
                    except PermissionError:
                        time.sleep(0.002)

        r = threading.Thread(target=reader, daemon=True)
        r.start()
        ws = [threading.Thread(target=writer, args=(k,)) for k in range(3)]
        for t in ws:
            t.start()
        for t in ws:
            t.join(30)
        stop.set()
        r.join(5)
        assert not torn, torn[:1]
        assert json.load(open(p, encoding="utf-8"))["i"] == 39
        assert os.listdir(d) == ["config.json"]


@each
def test_the_original_mode_and_owner_are_kept(w):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "config.json")
        w(p, {"a": 1})
        if os.name != "nt":
            os.chmod(p, 0o640)
        calls = []
        had = hasattr(os, "chown")
        real = getattr(os, "chown", None)
        os.chown = lambda path, uid, gid: calls.append((uid, gid))
        try:
            w(p, {"a": 2})
        finally:
            if had:
                os.chown = real
            else:
                del os.chown
        if os.name != "nt":
            assert (os.stat(p).st_mode & 0o7777) == 0o640
        st = os.stat(p)
        assert calls == [(st.st_uid, st.st_gid)], calls          # the Decky backend (root) hands the file back to its owner


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
