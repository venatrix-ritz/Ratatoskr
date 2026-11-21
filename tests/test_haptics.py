"""Tests for the haptics pulses; no real device is opened (run: python tests/test_haptics.py)."""
import errno
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import haptics  # noqa: E402

DEVICES = """I: Bus=0019 Vendor=0000 Product=0000 Version=0000
N: Name="gpio-keys-ayn"
H: Handlers=kbd event3
B: EV=3

I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="qcom-hv-haptics"
P: Phys=
H: Handlers=event8
B: EV=200001
B: FF=100070000 0
"""


class FakeDevice:
    def __init__(self, upload_error=None, effect_id=0):
        self.calls, self.writes, self.closed = [], [], False
        self.upload_error, self.effect_id = upload_error, effect_id

    def ioctl(self, fd, request, arg, mutate=False):
        if request == haptics.EVIOCSFF:
            self.calls.append(("upload", haptics.FF_EFFECT.unpack(bytes(arg))))
            if self.upload_error:
                raise OSError(self.upload_error, os.strerror(self.upload_error))
            struct.pack_into("=h", arg, 2, self.effect_id)
        elif request == haptics.EVIOCRMFF:
            self.calls.append(("erase", arg))
        return 0

    def write(self, fd, data):
        self.writes.append(haptics.EVENT.unpack(data)[2:])
        self.calls.append(("play",))
        return len(data)


def make(dev, path="/dev/input/event8"):
    h = haptics.Haptics(find=lambda: path, open_fn=lambda p, flags: 7, ioctl=dev.ioctl, write=dev.write,
                        sleep=lambda s: None, close=lambda fd: setattr(dev, "closed", True))
    return h


def test_struct_matches_the_64_bit_kernel_layout():
    assert haptics.FF_EFFECT.size == 48
    assert haptics.EVIOCSFF == 0x40304580 and haptics.EVIOCRMFF == 0x40044581


def test_find_device_reads_proc_bus_input_devices():
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(DEVICES)
    try:
        assert haptics.find_device(devices_path=f.name) == "/dev/input/event8"
        assert haptics.find_device("no such pad", devices_path=f.name) is None
    finally:
        os.unlink(f.name)
    assert haptics.find_device(devices_path=os.path.join(ROOT, "no-such-file")) is None


def test_a_pulse_uploads_plays_and_erases_one_rumble():
    dev = FakeDevice(effect_id=3)
    h = make(dev)
    h.fd = 7
    assert h.play_once() is True
    kind, fields = dev.calls[0]
    assert kind == "upload" and fields[0] == haptics.FF_RUMBLE and fields[1] == -1
    assert fields[5] == haptics.PULSE_MS and fields[7] == haptics.STRENGTH
    assert dev.calls[1:] == [("play",), ("erase", 3)]
    assert dev.writes == [(haptics.EV_FF, 3, 1)] and h.pulses == 1


def test_a_busy_slot_skips_the_pulse_quietly():
    dev = FakeDevice(upload_error=errno.ENOSPC)
    logged = []
    h = make(dev)
    h.logger = type("L", (), {"log": lambda self, code, text: logged.append(text)})()
    h.fd = 7
    assert h.play_once() is False
    assert [c[0] for c in dev.calls] == ["upload"] and h.failures == 1 and logged == []


def test_pulse_does_nothing_when_off_or_without_a_device():
    h = make(FakeDevice())
    h.pulse()
    assert not h._wake.is_set(), "no device opened yet"
    h.fd = 7
    h.enabled = False
    h.pulse()
    assert not h._wake.is_set()
    h.enabled = True
    h.pulse()
    assert h._wake.is_set()


def test_start_without_the_device_stays_silent():
    logged = []
    h = haptics.Haptics(logger=type("L", (), {"log": lambda self, code, text: logged.append(text)})(),
                        find=lambda: None, ioctl=lambda *a: 0)
    assert h.start() is False and not h.available and len(logged) == 1
    h.pulse()
    h.stop()


def test_start_plays_pulses_on_its_thread_and_stop_closes():
    dev = FakeDevice()
    h = make(dev)
    assert h.start() is True and h.available
    h.pulse()
    for _ in range(200):
        if h.pulses:
            break
        import time
        time.sleep(0.01)
    h.stop()
    assert h.pulses == 1 and dev.closed and not h.available


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
