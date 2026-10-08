"""Gesture engine tests with a fake output device (run: python tests/test_engine.py). No device needed."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import engine as E  # noqa: E402


class FakeBridge:
    def __init__(self):
        self.log = []

    def emit_mouse_rel(self, dx, dy):
        self.log.append(("rel", dx, dy))

    def emit_scroll(self, dx, dy):
        self.log.append(("scroll", dx, dy))

    def tap_button(self, button, *a):
        self.log.append(("click", button))

    def tap_key(self, key, *a):
        self.log.append(("tapkey", key))

    def key(self, key, down):
        self.log.append(("key", key, down))

    def mouse_button(self, button, down):
        self.log.append(("btn", button, down))


def fresh(**settings):
    bridge = FakeBridge()
    g = E.TouchGestureProcessor(bridge)
    g.set_settings(**settings)
    bridge.log.clear()
    return g, bridge


def moves(log):
    return [e for e in log if e[0] == "rel"]


def clicks(log):
    return [e for e in log if e[0] == "click"]


def finger_path(g, tid, x0, y0, steps, dx, dy, t0, dt):
    """Put a finger down at (x0, y0) at t0 and move it `steps` times by (dx, dy) every dt seconds; returns the last time."""
    g.touch_down(tid, x0, y0, t0)
    t = t0
    for i in range(1, steps + 1):
        t = t0 + dt * i
        g.touch_move(tid, x0 + dx * i, y0 + dy * i, t)
    return t


# --- tap versus move --------------------------------------------------------------------------------------

def test_quick_nudge_moves_the_cursor_and_does_not_click():
    g, b = fresh(sensitivity=1.5, glide=False)
    t = finger_path(g, 1, 300, 300, 10, 3, 0, 100.0, 0.015)      # 30 px in 0.15 s
    g.touch_up(1, t + 0.01)
    assert moves(b.log) and not clicks(b.log), b.log


def test_clean_tap_clicks_and_does_not_move_the_cursor():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 302, 301, 100.03)                            # finger jitter
    g.touch_move(1, 301, 300, 100.06)
    g.touch_up(1, 100.10)
    assert clicks(b.log) == [("click", E.BTN_LEFT)] and not moves(b.log), b.log


def test_slow_drag_moves_and_does_not_click():
    g, b = fresh(sensitivity=1.5, glide=False)
    t = finger_path(g, 1, 300, 300, 40, 3, 0, 100.0, 0.015)      # 120 px in 0.6 s
    g.touch_up(1, t + 0.01)
    assert len(moves(b.log)) > 20 and not clicks(b.log)


def test_resting_finger_is_neither_a_click_nor_a_move():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 301, 300, 100.2)
    g.touch_up(1, 100.6)                                          # held 0.6 s without travelling
    assert not clicks(b.log) and not moves(b.log), b.log


def test_a_slide_that_starts_after_a_pause_still_moves():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 301, 300, 100.1)
    for i in range(1, 11):                                        # 0.4 s after touchdown the finger slides
        g.touch_move(1, 301 + 5 * i, 300, 100.4 + 0.015 * i)
    g.touch_up(1, 100.6)
    assert len(moves(b.log)) >= 8 and not clicks(b.log)


def test_two_finger_tap_right_clicks_even_with_some_jitter():
    g, b = fresh(two_finger_right_click=True)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_down(2, 400, 300, 100.01)
    g.touch_move(1, 306, 304, 100.05)
    g.touch_move(2, 405, 303, 100.05)
    g.touch_up(1, 100.12)
    g.touch_up(2, 100.13)
    assert clicks(b.log) == [("click", E.BTN_RIGHT)], b.log


def test_tap_to_click_off_means_no_click():
    g, b = fresh(tap_to_click=False)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_up(1, 100.1)
    assert not clicks(b.log)


# --- ghost contacts (the touch controller loses a lift) ---------------------------------------------------

def test_a_ghost_contact_does_not_turn_one_finger_into_a_scroll():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(73, 877, 592, 100.0)              # a finger whose lift the controller never reports
    for i, t in enumerate((110.0, 125.0)):         # later single-finger touches, ghost still "down"
        finger_path(g, 10 + i, 300, 300, 20, 4, 0, t, 0.015)
        g.touch_up(10 + i, t + 0.4)
    assert moves(b.log), "one finger must move the cursor"
    assert not [e for e in b.log if e[0] == "scroll"], "and must not scroll"
    assert 73 not in g.active_contacts


def test_a_recent_second_finger_still_scrolls():
    g, b = fresh(scroll_speed=3)
    g.touch_down(1, 300, 300, 100.0)
    g.touch_move(1, 300, 305, 101.9)               # first finger reported 0.1 s before the second lands
    g.touch_down(2, 400, 300, 102.0)
    g.touch_move(1, 300, 320, 102.02)
    g.touch_move(2, 400, 320, 102.02)
    assert [e for e in b.log if e[0] == "scroll"], b.log


def test_a_resting_anchor_finger_survives_a_short_pause():
    g, b = fresh()
    g.touch_down(1, 300, 300, 100.0)
    g.touch_down(2, 400, 300, 101.0)               # 1.0 s of silence is still within the grace period
    assert set(g.active_contacts) == {1, 2}


def test_a_press_and_hold_is_not_cut_short_by_the_expiry():
    g, b = fresh(long_press_right_click=True, long_press_delay_ms=1200)
    g.touch_down(1, 300, 300, 100.0)
    g.expire_stale(101.2)                          # the longest long-press delay
    assert 1 in g.active_contacts


def test_ghosts_expire_while_another_finger_keeps_moving():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(111, 652, 412, 100.0)             # four fingers were down; two lifts never arrive
    g.touch_down(112, 440, 759, 100.0)
    g.touch_down(5, 300, 300, 100.5)
    t = 100.5
    for i in range(1, 200):                        # one real finger keeps sliding for 3 s
        t += 0.015
        g.expire_stale(t)
        g.touch_move(5, 300 + 2 * i, 300, t)
    assert set(g.active_contacts) == {5}, g.active_contacts
    assert len(moves(b.log)) > 100, "once the ghosts expire the finger moves the cursor"
    late_scrolls = [e for e in b.log[-60:] if e[0] == "scroll"]
    assert not late_scrolls


def test_expiring_on_idle_ticks_clears_a_lone_ghost():
    g, b = fresh()
    g.touch_down(73, 877, 592, 100.0)
    g.expire_stale(100.5)
    assert 73 in g.active_contacts
    g.expire_stale(101.6)
    assert not g.active_contacts


def test_dropping_the_only_stale_contact_resets_the_tap_state():
    g, b = fresh(glide=False)
    g.touch_down(73, 877, 592, 100.0)
    g.touch_down(5, 300, 300, 120.0)
    g.touch_up(5, 120.1)                           # a clean tap with the ghost gone
    assert clicks(b.log) == [("click", E.BTN_LEFT)], b.log


# --- a finger that lands in a dropped ghost's slot ---------------------------------------------------------

def test_a_finger_landing_in_a_dropped_ghosts_slot_moves_the_cursor():
    g, b = fresh(sensitivity=1.5, glide=False)
    g.touch_down(135, 276, 596, 100.0)             # lift lost; the kernel keeps tracking id 135 in its slot
    g.expire_stale(101.6)
    assert not g.active_contacts
    t = 110.0
    for i in range(1, 30):                         # a new finger takes the slot: same id, now moving
        t += 0.015
        g.touch_move(135, 300 + 4 * i, 300, t)
    assert moves(b.log), "the finger in the old slot must drive the cursor"
    assert 135 in g.active_contacts


def test_a_move_for_a_contact_never_seen_is_still_ignored():
    g, b = fresh()
    g.touch_move(99, 300, 300, 100.0)
    assert not b.log and not g.active_contacts


def test_a_lift_forgets_the_dropped_ghost():
    g, b = fresh()
    g.touch_down(135, 276, 596, 100.0)
    g.expire_stale(101.6)
    g.touch_up(135, 102.0)
    g.touch_move(135, 300, 300, 102.1)             # the slot was released: this is not a live contact
    assert not g.active_contacts and not b.log


# --- too many fingers ---------------------------------------------------------------------------------------

def four_down(g, t):
    for tid, x in ((1, 200), (2, 300), (3, 400), (4, 500)):
        g.touch_down(tid, x, 500, t)


def test_four_fingers_produce_no_output_and_no_click():
    g, b = fresh(three_finger_swipe_enabled=True, three_finger_middle_click=True)
    four_down(g, 100.0)
    for tid, x in ((1, 200), (2, 300), (3, 400), (4, 500)):
        g.touch_move(tid, x, 400, 100.02)          # a 100 px swipe by all four
    for tid in (1, 2, 3, 4):
        g.touch_up(tid, 100.1)
    assert not b.log, b.log
    assert not g.active_contacts and not g.misuse_lock


def test_the_lock_holds_until_the_last_finger_has_lifted():
    g, b = fresh(sensitivity=1.5, glide=False, three_finger_swipe_enabled=True)
    four_down(g, 100.0)
    g.touch_up(4, 100.05)                          # three left: they must not scroll, swipe or click
    for i in range(1, 6):
        for tid, x in ((1, 200), (2, 300), (3, 400)):
            g.touch_move(tid, x, 500 - 30 * i, 100.05 + 0.02 * i)
    for tid in (1, 2, 3):
        g.touch_up(tid, 100.4)
    assert not b.log, b.log
    finger_path(g, 7, 300, 300, 20, 4, 0, 101.0, 0.015)   # afterwards one finger works as normal
    assert moves(b.log)


def test_ghosts_left_by_a_five_finger_press_expire_and_release_the_lock():
    g, b = fresh(sensitivity=1.5, glide=False)
    for tid, x in ((1, 100), (2, 200), (3, 300), (4, 400), (5, 500)):
        g.touch_down(tid, x, 500, 100.0)           # none of the lifts ever arrives
    assert g.misuse_lock
    g.expire_stale(101.6)
    assert not g.active_contacts and not g.misuse_lock
    finger_path(g, 8, 300, 300, 20, 4, 0, 102.0, 0.015)
    assert moves(b.log) and not [e for e in b.log if e[0] == "scroll"]


# --- three-finger swipes ----------------------------------------------------------------------------------

def three_down(g, t, y=500):
    for tid, x in ((1, 300), (2, 400), (3, 500)):
        g.touch_down(tid, x, y, t)


def three_move(g, t, dx, dy, y=500):
    for tid, x in ((1, 300), (2, 400), (3, 500)):
        g.touch_move(tid, x + dx, y + dy, t)


def three_up(g, t):
    for tid in (1, 2, 3):
        g.touch_up(tid, t)


def test_three_finger_swipe_ignores_a_small_move():
    g, b = fresh(three_finger_swipe_enabled=True)
    three_down(g, 100.0)
    three_move(g, 100.02, 2, 2)
    assert not [e for e in b.log if e[0] in ("tapkey", "key")], b.log


def test_three_finger_swipe_up_sends_super_once():
    g, b = fresh(three_finger_swipe_enabled=True)
    three_down(g, 100.0)
    three_move(g, 100.02, 0, -100)
    three_move(g, 100.04, 0, -140)
    assert [e for e in b.log if e[0] == "tapkey"] == [("tapkey", E.KEY_LEFTMETA)], b.log


def test_three_finger_swipe_down_left_and_a_second_swipe_after_lifting():
    g, b = fresh(three_finger_swipe_enabled=True)
    three_down(g, 100.0)
    three_move(g, 100.02, 0, 100)
    three_up(g, 100.1)
    assert ("tapkey", E.KEY_ESC) in b.log
    b.log.clear()
    three_down(g, 101.0)
    three_move(g, 101.02, -100, 0)
    assert ("key", E.KEY_LEFTALT, True) in b.log and ("tapkey", E.KEY_TAB) in b.log and ("key", E.KEY_LEFTALT, False) in b.log


def test_three_finger_swipe_off_does_nothing():
    g, b = fresh(three_finger_swipe_enabled=False)
    three_down(g, 100.0)
    three_move(g, 100.02, 0, -200)
    assert not [e for e in b.log if e[0] in ("tapkey", "key")]


# --- scrolling wakes a hidden pointer ---------------------------------------------------------------------

def bridge_with_pipe():
    import threading
    r, w = os.pipe()
    b = E.UInputBridge.__new__(E.UInputBridge)
    b.lock = threading.Lock()
    b.logger = E.DebugLogger("test")
    b.mouse_fd = w
    b.scroll_accum_x = b.scroll_accum_y = 0.0
    b.count_scrolls = b.count_mouse_moves = b.count_pointer_wakes = 0
    b.moved_at = 0.0
    return b, r


def drain(r):
    import select
    data = b""
    while select.select([r], [], [], 0)[0] if os.name != "nt" else False:
        data += os.read(r, 4096)
    return data


def read_events(r, n):
    out = []
    data = os.read(r, E.EVENT_STRUCT.size * n)
    for off in range(0, len(data), E.EVENT_STRUCT.size):
        _, _, etype, code, value = E.EVENT_STRUCT.unpack_from(data, off)
        out.append((etype, code, value))
    return out


def test_the_first_scroll_after_a_still_spell_nudges_the_pointer_out_and_back():
    b, r = bridge_with_pipe()
    b.emit_scroll(0, -120)
    ev = read_events(r, 7)
    xs = [v for t, c, v in ev if t == E.EV_REL and c == E.REL_X]
    assert xs == [1, -1], ev
    assert ev.index((E.EV_REL, E.REL_X, 1)) < ev.index((E.EV_REL, E.REL_WHEEL_HI_RES, -120))
    assert b.count_pointer_wakes == 1


def test_scrolling_right_after_pointer_motion_does_not_nudge():
    b, r = bridge_with_pipe()
    b.emit_mouse_rel(3, 0)
    read_events(r, 3)
    b.emit_scroll(0, -60)
    ev = read_events(r, 2)
    assert not [e for e in ev if e[0] == E.EV_REL and e[1] == E.REL_X], ev
    assert b.count_pointer_wakes == 0


def test_a_long_scroll_keeps_waking_the_pointer_every_couple_of_seconds():
    b, r = bridge_with_pipe()
    b.emit_scroll(0, -60)
    read_events(r, 6)
    b.emit_scroll(0, -60)                          # straight after: no second nudge
    read_events(r, 2)
    assert b.count_pointer_wakes == 1
    b.moved_at -= E.POINTER_WAKE_S + 0.5           # the pointer has been still since
    b.emit_scroll(0, -60)
    read_events(r, 6)
    assert b.count_pointer_wakes == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
