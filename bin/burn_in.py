"""Active OLED burn-in protection engine for Ratatoskr on the AYN Thor.

Features:
1. Orbital micro-shifter: periodic subpixel/pixel circular orbit (+-1.5 px) that moves
   rendering origins over a 90-second period, preventing sharp-edge static diode wear.
2. Trackpad hint auto-fader: smoothly fades out center hint text 5 seconds after start or the last
   mode change, to eliminate the primary burn-in hotspot in the center of the glass. A touch does not
   bring it back.
3. Idle luminance throttling (`get_luminance_scale`): returns 1.0 until 30 seconds after the last touch,
   then eases down to 40% over 5 seconds. `ThorApp._paint` draws a black veil of the missing share over
   the whole screen; the next touch (`record_touch`) brings it back to 100%.
4. Frame planning (`plan_redraw`): frames go out only when something on screen changed. The orbit is drawn in
   ORBIT_QUANTUM_PX steps, so even an idle screen gets a new frame at every step (about every 3 s) and never keeps a
   static frame; while the hint fades or the luminance eases, frames go out every TRANSITION_TICK_S.
"""
from __future__ import annotations

import math
import time

# Half a pixel: the orbit keeps its +-1.5 px reach and 90 s cycle and visits 7 positions per axis, 27 steps a cycle
# (median 3 s apart), instead of a new sub-pixel position every 1 s tick. The longest dwell, 11 s, is where both axes
# turn at once (t = 45 s of each cycle); the continuous orbit moves only 0.009 px/s there, so it was as still. Wear
# builds over hours: the time spent at each position is what matters, and quantizing leaves that the same. 0.25 px
# would cost 52 frames a cycle for a 7 s longest dwell.
ORBIT_QUANTUM_PX = 0.5
IDLE_TICK_S = 1.0         # how often the frame planner looks when nothing is fading
TRANSITION_TICK_S = 0.25  # how often it looks (and draws) while the hint fades or the luminance eases


def quantize(value: float, step: float = ORBIT_QUANTUM_PX) -> float:
    return round(value / step) * step


def plan_redraw(drawn: dict | None, want: dict, ribbon_ok: bool = True) -> str | None:
    """'full', 'ribbon' or None: what must be repainted so the screen shows `want` when `drawn` is on it.

    Both dicts hold `orbit` (quantized offset), `lum` and `hint` (rounded), `page` (whatever outside the ribbon the
    planner can see change) and `ribbon` (the status texts). Only a change of the ribbon alone can be a ribbon-only
    repaint, and only when `ribbon_ok` (nothing else is drawn over the ribbon band)."""
    if drawn is None:
        return "full"
    if any(drawn.get(k) != want.get(k) for k in ("orbit", "lum", "hint", "page")):
        return "full"
    if drawn.get("ribbon") != want.get("ribbon"):
        return "ribbon" if ribbon_ok else "full"
    return None


class BurnInProtector:
    def __init__(
        self,
        shift_radius: float = 1.5,
        cycle_seconds: float = 90.0,
        idle_timeout: float = 30.0,
        idle_floor: float = 0.4,
        hint_duration: float = 5.0,
    ) -> None:
        self.shift_radius = shift_radius
        self.cycle_seconds = cycle_seconds
        self.idle_timeout = idle_timeout
        self.idle_floor = idle_floor
        self.hint_duration = hint_duration

        self.start_time = time.monotonic()
        self.last_touch_time = self.start_time
        self.mode_change_time = self.start_time

    def record_touch(self, now: float | None = None) -> None:
        """Call whenever any touch contact lands on the digitizer."""
        self.last_touch_time = time.monotonic() if now is None else now

    def notify_mode_change(self, now: float | None = None) -> None:
        """Call whenever the user switches bottom-screen modes."""
        self.mode_change_time = time.monotonic() if now is None else now

    def get_orbital_offset(self, now: float | None = None) -> tuple[float, float]:
        """Return (dx, dy) pixel shift within +-shift_radius based on current time."""
        t = time.monotonic() if now is None else now
        phase = (t % self.cycle_seconds) / self.cycle_seconds * (2.0 * math.pi)
        dx = self.shift_radius * math.cos(phase)
        dy = self.shift_radius * math.sin(phase * 1.5)
        return (dx, dy)

    def orbit_step(self, now: float | None = None) -> tuple[float, float]:
        """The orbit offset as drawn: rounded to ORBIT_QUANTUM_PX."""
        dx, dy = self.get_orbital_offset(now)
        return quantize(dx), quantize(dy)

    def in_transition(self, now: float | None = None) -> bool:
        """True while the hint fades or the luminance eases (each frame differs from the last)."""
        t = time.monotonic() if now is None else now
        return 0.0 < self.get_hint_alpha(t) < 1.0 or self.idle_floor < self.get_luminance_scale(t) < 1.0

    def next_tick_s(self, now: float | None = None) -> float:
        """Delay until the frame planner should look again: short during a fade, and already short in the second
        before one starts so that its first frames are not late."""
        t = time.monotonic() if now is None else now
        if self.in_transition(t) or self.in_transition(t + IDLE_TICK_S):
            return TRANSITION_TICK_S
        return IDLE_TICK_S

    def get_hint_alpha(self, now: float | None = None) -> float:
        """Return 0.0 to 1.0 opacity for the center hint text. Fades out after hint_duration."""
        t = time.monotonic() if now is None else now
        elapsed = min(t - self.start_time, t - self.mode_change_time)
        if elapsed < self.hint_duration:
            return 1.0
        fade_time = 1.5
        fade_elapsed = elapsed - self.hint_duration
        if fade_elapsed >= fade_time:
            return 0.0
        return max(0.0, 1.0 - (fade_elapsed / fade_time))

    def get_luminance_scale(self, now: float | None = None) -> float:
        """Return 1.0 (active) down to idle_floor (idle rest state) after idle_timeout."""
        t = time.monotonic() if now is None else now
        idle_elapsed = t - self.last_touch_time
        if idle_elapsed <= self.idle_timeout:
            return 1.0
        fade_time = 5.0
        progress = min(1.0, (idle_elapsed - self.idle_timeout) / fade_time)
        return 1.0 - (1.0 - self.idle_floor) * progress
