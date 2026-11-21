"""Tests for PS mode's pad, buttons and Chiaki-NG focus detection (run: python tests/test_ps_pad.py)."""
import os
import subprocess
import sys
import tempfile

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


def make(active=True):
    pad = ps_pad.PsPad(Bridge(), ps_pad.PsLayout(168.0, 1240.0, 1080.0))
    pad.set_active(active)
    return pad


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
    assert [b[0] for b in lay.buttons] == ["create", "ps", "options", "click", "mic"]
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
    for name, code in (("ps", ESC), ("options", O), ("create", F), ("click", T)):
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


def test_click_while_touching_presses_the_touchpad_at_the_finger():
    pad = make()
    pad.touch_down(1, *centre(pad, "pad"))
    pad.touch_down(2, *centre(pad, "click"))
    assert pad.bridge.ev[-1] == (T, "down") and pad.finger == 1


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
