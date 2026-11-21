"""Tests for PS mode's pad, buttons and Chiaki-NG focus detection (run: python tests/test_ps_pad.py)."""
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import ps_pad  # noqa: E402

ESC, CTRL, M, O, F, T = 1, 29, 50, 24, 33, 20


class Bridge:
    def __init__(self):
        self.ev = []

    def ps_touch(self, x, y):
        self.ev.append(("touch", round(x, 4), round(y, 4)))

    def ps_touch_up(self):
        self.ev.append(("lift",))

    def key(self, code, down):
        self.ev.append((code, "down" if down else "up"))


class FakeTimer:
    """Records timers; a test fires them by hand. `made` is shared by all timers of one pad."""

    def __init__(self, made, delay, fn, args=()):
        self.made, self.delay, self.fn, self.args = made, delay, fn, args
        self.started = self.cancelled = self.fired = False
        made.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        assert self.started and not self.cancelled
        self.fired = True
        self.fn(*self.args)


def make(active=True, tap_to_click=True, long_press_delay_ms=450):
    clock, timers = [100.0], []
    settings = SimpleNamespace(tap_to_click=tap_to_click, long_press_delay_ms=long_press_delay_ms)
    pad = ps_pad.PsPad(
        Bridge(), ps_pad.PsLayout(168.0, 1240.0, 1080.0), settings=settings, clock=lambda: clock[0],
        timer=lambda delay, fn, args=(): FakeTimer(timers, delay, fn, args),
    )
    pad.set_active(active)
    pad.clock, pad.timers = clock, timers
    return pad


def live(pad):
    return [t for t in pad.timers if t.started and not t.cancelled and not t.fired]


def centre(pad, name):
    lay = pad.layout
    if name == "pad":
        return lay.pad_x + lay.pad_w / 2, lay.pad_y + lay.pad_h / 2
    _n, _l, bx, bw = next(b for b in lay.buttons if b[0] == name)
    return bx + bw / 2, lay.button_y + lay.button_h / 2


def test_layout_fits_the_screen_below_the_header():
    lay = ps_pad.PsLayout(168.0, 1240.0, 1080.0)
    assert lay.pad_y >= 168.0 and lay.button_y + lay.button_h <= 1080.0
    assert abs(lay.pad_w / lay.pad_h - 16 / 9) < 0.01
    assert [b[0] for b in lay.buttons] == ["create", "ps", "options", "mic"]
    assert lay.hit(5.0, 500.0) is None and lay.hit(lay.pad_x + 1, lay.pad_y + 1) == "pad"


def test_pad_edges_stay_inside_the_inset():
    assert ps_pad.to_device(0.0, 0.0) == (ps_pad.EDGE_INSET, ps_pad.EDGE_INSET)
    x, y = ps_pad.to_device(1.0, 1.0)
    assert abs(x - (1 - ps_pad.EDGE_INSET)) < 1e-9 and abs(y - (1 - ps_pad.EDGE_INSET)) < 1e-9


def test_rotations_turn_the_axes():
    u, v = 0.25, 0.0
    a, b = ps_pad.to_device(u, v, 0, inset=0.0), ps_pad.to_device(u, v, 90, inset=0.0)
    assert a == (0.25, 0.0) and b == (1.0, 0.25)
    assert ps_pad.to_device(u, v, 180, inset=0.0) == (0.75, 1.0)
    assert ps_pad.to_device(u, v, 270, inset=0.0) == (0.0, 0.75)
    assert ps_pad.normalize_rotation("90") == 90 and ps_pad.normalize_rotation(45) == 0 and ps_pad.normalize_rotation(None) == 0


def test_a_pad_touch_lands_nudges_moves_and_lifts():
    pad = make()
    x, y = centre(pad, "pad")
    assert pad.touch_down(1, x, y) == "pad"
    assert pad.bridge.ev[0] == ("touch", 0.5, 0.5)
    assert pad.bridge.ev[1][0] == "touch" and pad.bridge.ev[1][1] > 0.5, pad.bridge.ev
    pad.touch_move(1, pad.layout.pad_x, pad.layout.pad_y)
    assert pad.bridge.ev[2] == ("touch", ps_pad.EDGE_INSET, ps_pad.EDGE_INSET)
    pad.touch_up(1)
    assert pad.bridge.ev[-1] == ("lift",) and pad.finger is None
    assert T not in [e[0] for e in pad.bridge.ev], "a swipe is no click"


def test_a_tap_clicks_with_the_touch_still_down_then_lifts():
    pad = make()
    x, y = centre(pad, "pad")
    pad.touch_down(1, x, y)
    pad.clock[0] += 0.1
    pad.touch_move(1, x + 5, y)
    pad.touch_up(1)
    assert pad.bridge.ev[-1] == (T, "down") and pad.clicking, pad.bridge.ev
    release = live(pad)[-1]
    assert abs(release.delay - ps_pad.TAP_CLICK_S) < 1e-9
    release.fire()
    assert pad.bridge.ev[-2:] == [(T, "up"), ("lift",)] and not pad.clicking


def test_a_slow_or_moving_touch_is_no_tap():
    for dt, dx in ((ps_pad.TAP_MAX_TIME_S + 0.01, 0.0), (0.05, ps_pad.TAP_MAX_DISTANCE_PX + 1)):
        pad = make()
        x, y = centre(pad, "pad")
        pad.touch_down(1, x, y)
        pad.clock[0] += dt
        pad.touch_move(1, x + dx, y)
        pad.touch_up(1)
        assert T not in [e[0] for e in pad.bridge.ev] and pad.bridge.ev[-1] == ("lift",), (dt, dx, pad.bridge.ev)


def test_tap_to_click_off_sends_only_the_touch():
    pad = make(tap_to_click=False)
    pad.touch_down(1, *centre(pad, "pad"))
    pad.touch_up(1)
    assert T not in [e[0] for e in pad.bridge.ev] and pad.bridge.ev[-1] == ("lift",)


def test_a_long_press_holds_the_click_until_the_lift():
    pad = make(long_press_delay_ms=600)
    x, y = centre(pad, "pad")
    pad.touch_down(1, x, y)
    hold = live(pad)[0]
    assert abs(hold.delay - 0.6) < 1e-9
    pad.clock[0] += 0.6
    hold.fire()
    assert pad.bridge.ev[-1] == (T, "down") and pad.clicking
    pad.touch_move(1, x + 200, y)  # dragging with the click held
    assert pad.bridge.ev[-1][0] == "touch" and pad.clicking
    pad.touch_up(1)
    assert pad.bridge.ev[-2:] == [(T, "up"), ("lift",)] and not pad.clicking
    assert len(live(pad)) == 0


def test_moving_before_the_long_press_cancels_it():
    pad = make()
    x, y = centre(pad, "pad")
    pad.touch_down(1, x, y)
    hold = live(pad)[0]
    pad.touch_move(1, x + ps_pad.LONG_PRESS_MAX_DIST_PX + 1, y)
    assert hold.cancelled
    hold.cancelled = False
    hold.fire()  # a timer that was already waiting for the lock when it was cancelled
    assert not pad.clicking and T not in [e[0] for e in pad.bridge.ev]


def test_a_new_touch_during_a_tap_click_finishes_the_tap_first():
    pad = make()
    x, y = centre(pad, "pad")
    pad.touch_down(1, x, y)
    pad.touch_up(1)
    old = live(pad)[-1]
    pad.touch_down(2, x + 100, y)
    assert pad.bridge.ev[3:6] == [(T, "up"), ("lift",), ("touch", pad.bridge.ev[5][1], 0.5)], pad.bridge.ev
    assert old.cancelled
    old.cancelled = False
    old.fire()  # the old release must not lift the new touch
    assert pad.bridge.ev[-1][0] == "touch" and pad.finger == 2


def test_buttons_and_pad_clicks_buzz_but_plain_touches_do_not():
    pad = make()
    buzz = []
    pad.on_press = lambda: buzz.append(1)
    x, y = centre(pad, "pad")
    pad.touch_down(1, x, y)
    pad.touch_move(1, x + 100, y)
    pad.touch_up(1)
    assert buzz == [], "a swipe does not buzz"
    pad.touch_down(2, x, y)
    pad.touch_up(2)
    assert buzz == [1], "a tap click buzzes"
    live(pad)[-1].fire()
    pad.touch_down(3, x, y)
    live(pad)[0].fire()
    assert buzz == [1, 1], "a long press buzzes when the click goes down"
    pad.touch_up(3)
    for name in ("ps", "mic"):
        pad.touch_down(9, *centre(pad, name))
        pad.touch_up(9)
    assert buzz == [1, 1, 1, 1]
    off = make(active=False)
    off.on_press = lambda: buzz.append(1)
    off.touch_down(1, *centre(off, "ps"))
    assert buzz == [1, 1, 1, 1], "nothing without focus"


def test_losing_focus_during_a_tap_click_releases_it():
    pad = make()
    pad.touch_down(1, *centre(pad, "pad"))
    pad.touch_up(1)
    pad.bridge.ev.clear()
    pad.set_active(False)
    assert pad.bridge.ev == [(T, "up"), ("lift",)] and not pad.clicking


def test_a_touch_at_the_right_edge_nudges_inwards():
    pad = make()
    pad.touch_down(1, pad.layout.pad_x + pad.layout.pad_w, pad.layout.pad_y)
    assert pad.bridge.ev[1][1] < pad.bridge.ev[0][1], pad.bridge.ev


def test_a_second_finger_on_the_pad_is_ignored():
    pad = make()
    x, y = centre(pad, "pad")
    pad.touch_down(1, x, y)
    n = len(pad.bridge.ev)
    pad.touch_down(2, x + 50, y)
    pad.touch_move(2, x + 60, y)
    pad.touch_up(2)
    assert len(pad.bridge.ev) == n and pad.finger == 1


def test_buttons_hold_their_key_while_the_finger_is_down():
    for name, code in (("ps", ESC), ("options", O), ("create", F)):
        pad = make()
        pad.touch_down(3, *centre(pad, name))
        assert pad.bridge.ev == [(code, "down")] and pad.pressed(name)
        pad.touch_up(3)
        assert pad.bridge.ev == [(code, "down"), (code, "up")] and not pad.pressed(name)


def test_two_fingers_on_one_button_release_with_the_last():
    pad = make()
    pad.touch_down(1, *centre(pad, "ps"))
    pad.touch_down(2, *centre(pad, "ps"))
    pad.touch_up(1)
    assert pad.bridge.ev == [(ESC, "down")]
    pad.touch_up(2)
    assert pad.bridge.ev == [(ESC, "down"), (ESC, "up")]


def test_mic_taps_ctrl_m():
    pad = make()
    pad.touch_down(4, *centre(pad, "mic"))
    pad.touch_up(4)
    assert pad.bridge.ev == [(CTRL, "down"), (M, "down"), (M, "up"), (CTRL, "up")]


def test_nothing_goes_out_without_focus():
    pad = make(active=False)
    for name in ("pad", "ps", "mic"):
        assert pad.touch_down(9, *centre(pad, name)) == name
        pad.touch_up(9)
    assert pad.bridge.ev == [] and pad.blocked_touch_at > 0


def test_losing_focus_lifts_the_touch_and_releases_keys():
    pad = make()
    pad.touch_down(1, *centre(pad, "pad"))
    pad.touch_down(2, *centre(pad, "options"))
    pad.bridge.ev.clear()
    pad.set_active(False)
    assert pad.bridge.ev == [("lift",), (O, "up")] and pad.finger is None and not pad.button_tids
    pad.touch_up(1)
    pad.touch_up(2)
    assert pad.bridge.ev == [("lift",), (O, "up")]


def test_parse_focused_app():
    assert ps_pad.parse_focused_app("GAMESCOPE_FOCUSED_APP(CARDINAL) = 3174227830\n") == 3174227830
    assert ps_pad.parse_focused_app("GAMESCOPE_FOCUSED_APP:  not found.\n") is None
    assert ps_pad.parse_focused_app("X(CARDINAL) = 769, 12") == 769


def test_read_focused_app_survives_a_missing_xprop():
    def missing(*a, **k):
        raise FileNotFoundError("xprop")

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("xprop", 1.0)

    assert ps_pad.read_focused_app(missing) is None and ps_pad.read_focused_app(timeout) is None
    ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "GAMESCOPE_FOCUSED_APP(CARDINAL) = 42\n", "")
    assert ps_pad.read_focused_app(ok) == 42


def test_chiaki_app_ids_reads_steam_app_id_of_chiaki_processes():
    with tempfile.TemporaryDirectory() as root:
        for pid, comm, env in (
            ("100", "chiaki\n", b"HOME=/x\0SteamAppId=3174227830\0"),
            ("101", "bwrap\n", b"SteamAppId=1\0"),
            ("102", "chiaki\n", b"HOME=/x\0"),
            ("self", "chiaki\n", b"SteamAppId=2\0"),
        ):
            os.makedirs(os.path.join(root, pid))
            with open(os.path.join(root, pid, "comm"), "w") as f:
                f.write(comm)
            with open(os.path.join(root, pid, "environ"), "wb") as f:
                f.write(env)
        assert ps_pad.chiaki_app_ids(root) == {3174227830}
    assert ps_pad.chiaki_app_ids(os.path.join(ROOT, "no-such-dir")) == set()


def test_focus_watcher_reports_changes_once():
    calls, focus, ids = [], [None], [{3174227830}]
    clock = [0.0]
    w = ps_pad.FocusWatcher(calls.append, read_focus=lambda: focus[0], read_ids=lambda: ids[0], clock=lambda: clock[0])
    assert w.poll_once() is False and calls == []
    focus[0] = 3174227830
    assert w.poll_once() is True and calls == [True]
    w.poll_once()
    assert calls == [True]
    focus[0] = 769
    assert w.poll_once() is False and calls == [True, False]


def test_focus_watcher_rescans_when_chiaki_starts_late():
    calls, scans = [], [set()]
    clock = [0.0]

    def read_ids():
        return scans[0]

    w = ps_pad.FocusWatcher(calls.append, read_focus=lambda: 5, read_ids=read_ids, clock=lambda: clock[0], rescan=5.0)
    w.poll_once()
    scans[0] = {5}
    clock[0] = 1.0
    w.poll_once()
    assert calls == []  # cached for the same app id until the rescan interval
    clock[0] = 6.0
    w.poll_once()
    assert calls == [True]


class Gone(Exception):
    """What python-xlib raises once the display has gone (ConnectionClosedError)."""


class FakeSource:
    """An XFocusSource stand-in: `script` is what each wait() does in turn: True (a write was heard), False (timeout),
    or an exception to raise."""

    def __init__(self, values, script, on_done=None):
        self.values, self.script, self.on_done = list(values), list(script), on_done
        self.reads = self.drains = 0
        self.waits = []
        self.closed = False

    def read(self):
        self.reads += 1
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]

    def wait(self, timeout):
        self.waits.append(timeout)
        if not self.script:
            self.on_done()
            return False
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def drain(self):
        self.drains += 1
        return False

    def close(self):
        self.closed = True


def watcher(sources, **kw):
    calls, logs = [], []
    it = iter(sources)

    def connect():
        src = next(it)
        if isinstance(src, Exception):
            raise src
        return src

    w = ps_pad.FocusWatcher(calls.append, read_ids=lambda: {3174227830}, connect=connect, log=logs.append, settle=0.0, **kw)
    return w, calls, logs


def test_focus_watcher_reconnects_when_the_display_goes_away():
    saved = ps_pad.RECONNECT_MIN_S
    ps_pad.RECONNECT_MIN_S = 0.01
    try:
        second = FakeSource([769], [], on_done=lambda: w._stop.set())
        first = FakeSource([3174227830], [Gone("server")])
        w, calls, logs = watcher([first, second])
        w._run()
    finally:
        ps_pad.RECONNECT_MIN_S = saved
    assert calls == [True, False], calls  # focus on the first connection, lost with it, still lost after reconnecting
    assert first.closed and second.reads >= 1
    assert w.source == "x11" and w.focused_app == 769
    assert any("lost X display" in m for m in logs) and sum("watching" in m for m in logs) == 2, logs


def test_focus_watcher_backs_off_while_the_display_cannot_be_opened():
    waits = []

    class Stop:
        def __init__(self):
            self.flag = False

        def is_set(self):
            return self.flag

        def wait(self, t):
            waits.append(t)
            return self.flag

        def set(self):
            self.flag = True

    w, calls, logs = watcher([OSError("no display")] * 6 + [FakeSource([None], [], on_done=lambda: w._stop.set())])
    w._stop = Stop()
    w._run()
    assert waits[:6] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0], waits
    assert calls == [] and w.focused_app is None
    assert sum("cannot open" in m for m in logs) == 1, logs  # one line per outage, not one per retry


def test_without_python_xlib_the_watcher_polls_xprop():
    polls = []

    def read_focus():
        polls.append(1)
        if len(polls) == 3:
            w._stop.set()
        return 3174227830

    w, calls, logs = watcher([ImportError("No module named 'Xlib'")], read_focus=read_focus, interval=0.0)
    w._run()
    assert w.source == "xprop" and len(polls) == 3 and calls == [True], (w.source, polls, calls)
    assert "polling xprop" in logs[0], logs


def test_a_burst_of_focus_writes_is_read_once_after_it_settles():
    src = FakeSource([769, 3174227830], [True], on_done=lambda: w._stop.set())
    w, calls, logs = watcher([src])
    w._watch(src)
    assert src.drains == 1 and w.writes_heard == 1 and calls == [True], (src.drains, w.writes_heard, calls)
    assert src.reads == 3  # once on connect, once after the burst, once after the final timeout


def test_chiaki_app_ids_are_scanned_only_when_the_focused_app_changes():
    scans, clock = [], [0.0]

    def read_ids():
        scans.append(clock[0])
        return {3174227830}

    w = ps_pad.FocusWatcher(lambda f: None, read_ids=read_ids, clock=lambda: clock[0], rescan=1.0, late_start=10.0)
    for i in range(30):  # Steam's UI stays focused for 30 s
        clock[0] = float(i)
        w.update(769)
    assert scans == [float(i) for i in range(10)], scans  # the change, then once a second for 10 s (Chiaki may start late)
    scans.clear()
    for i in range(30, 60):
        clock[0] = float(i)
        w.update(3174227830)
    assert scans == [30.0], scans  # Chiaki found at once: no more scans while it stays focused
    w.update(None)
    assert scans == [30.0], scans  # no app: nothing to look up


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
