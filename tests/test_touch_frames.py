"""Touch frame parser tests (run: python tests/test_touch_frames.py). No device needed."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import touch_frames as tf  # noqa: E402


def ev(t, code, value, etype=tf.EV_ABS, sec=100):
    return tf.EVENT_STRUCT.pack(sec, int(t * 1e6), etype, code, value)


def syn(t, sec=100):
    return ev(t, tf.SYN_REPORT, 0, tf.EV_SYN, sec)


def identity(x, y):
    return float(x), float(y)


def contact(t, slot, tid, x, y):
    return (ev(t, tf.ABS_MT_SLOT, slot) + ev(t, tf.ABS_MT_TRACKING_ID, tid)
            + ev(t, tf.ABS_MT_POSITION_X, x) + ev(t, tf.ABS_MT_POSITION_Y, y))


def test_down_move_up_in_order_with_kernel_timestamps():
    p = tf.TouchFrameParser(identity)
    f1 = p.feed(contact(0.10, 0, 7, 50, 60) + syn(0.10))
    assert len(f1) == 1 and f1[0].downs == [(7, 50.0, 60.0)] and not f1[0].moves and f1[0].live == 1
    assert abs(f1[0].ts - 100.10) < 1e-6
    f2 = p.feed(ev(0.12, tf.ABS_MT_POSITION_X, 55) + syn(0.12))
    assert f2[0].moves == [(7, 55.0, 60.0)] and not f2[0].downs
    f3 = p.feed(ev(0.14, tf.ABS_MT_TRACKING_ID, -1) + syn(0.14))
    assert f3[0].ups == [7] and f3[0].live == 0


def test_frames_in_one_read_keep_their_own_timestamps():
    p = tf.TouchFrameParser(identity)
    data = contact(0.10, 0, 1, 10, 10) + syn(0.10) + ev(0.11, tf.ABS_MT_POSITION_X, 14) + syn(0.11) + ev(0.12, tf.ABS_MT_POSITION_X, 18) + syn(0.12)
    frames = p.feed(data)
    assert [round(f.ts, 2) for f in frames] == [100.10, 100.11, 100.12], "a burst must not collapse to one instant"


def test_two_slots_are_tracked_independently():
    p = tf.TouchFrameParser(identity)
    frames = p.feed(contact(0.1, 0, 1, 10, 10) + contact(0.1, 1, 2, 90, 90) + syn(0.1))
    assert sorted(frames[0].downs) == [(1, 10.0, 10.0), (2, 90.0, 90.0)] and frames[0].live == 2
    frames = p.feed(ev(0.12, tf.ABS_MT_SLOT, 1) + ev(0.12, tf.ABS_MT_TRACKING_ID, -1) + syn(0.12))
    assert frames[0].ups == [2] and frames[0].live == 1


def test_an_unchanged_position_is_not_a_move():
    p = tf.TouchFrameParser(identity)
    p.feed(contact(0.1, 0, 1, 10, 10) + syn(0.1))
    frames = p.feed(ev(0.12, tf.ABS_MT_POSITION_X, 10) + syn(0.12))
    assert not frames[0].moves and not frames[0].downs and not frames[0].ups


def test_syn_dropped_discards_state_and_is_reported():
    p = tf.TouchFrameParser(identity)
    p.feed(contact(0.1, 0, 1, 10, 10) + syn(0.1))
    frames = p.feed(ev(0.2, tf.SYN_DROPPED, 0, tf.EV_SYN))
    assert frames[0].dropped
    after = p.feed(contact(0.3, 0, 2, 40, 40) + syn(0.3))
    assert after[0].downs == [(2, 40.0, 40.0)] and not after[0].ups, "the old contact must not linger after a drop"


def test_a_read_that_ends_mid_event_is_completed_by_the_next_one():
    p = tf.TouchFrameParser(identity)
    data = contact(0.1, 0, 1, 10, 10) + syn(0.1)
    cut = len(data) - 5
    assert p.feed(data[:cut]) == []
    frames = p.feed(data[cut:])
    got = [f for f in frames if f.downs]
    assert got and got[0].downs == [(1, 10.0, 10.0)]


def test_the_screen_transform_is_applied():
    p = tf.TouchFrameParser(lambda x, y: (float(y), 1079.0 - x))
    frames = p.feed(contact(0.1, 0, 1, 100, 200) + syn(0.1))
    assert frames[0].downs == [(1, 200.0, 979.0)]


def test_resync_after_a_drop_restores_fingers_that_are_still_down():
    p = tf.TouchFrameParser(identity)
    p.feed(contact(0.1, 0, 5, 10, 20) + contact(0.1, 1, 6, 30, 40) + syn(0.1))
    p.feed(ev(0.2, tf.SYN_DROPPED, 0, tf.EV_SYN) + syn(0.2))
    frame = p.resync({0: (5, 11, 21), 1: (6, 30, 40), 2: (-1, 0, 0)}, 100.3)
    assert sorted(frame.downs) == [(5, 11.0, 21.0), (6, 30.0, 40.0)] and frame.live == 2, frame
    moved = p.feed(ev(0.4, tf.ABS_MT_SLOT, 1) + ev(0.4, tf.ABS_MT_POSITION_X, 35) + syn(0.4))
    assert moved[0].moves == [(6, 35.0, 40.0)] and not moved[0].downs, "a resynced contact must move, not land again"
    lifted = p.feed(ev(0.5, tf.ABS_MT_SLOT, 0) + ev(0.5, tf.ABS_MT_TRACKING_ID, -1) + syn(0.5))
    assert lifted[0].ups == [5]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
