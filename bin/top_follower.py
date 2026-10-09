"""Decides from the top panel's backlight alone when Steam's idle dim has started and when it is over.

Pure logic (no I/O, no clock): feed it (time, level) with level = brightness / max_brightness.
"""
from __future__ import annotations


class TopFollower:
    """Answers "dim", "restore" or None for each (time, level) it is given.

    - dim: the level has been falling steadily (never rising by more than a hair) for `fall_s` seconds, by at least
      `fall_drop` of where it started, and is below `peak_ratio` of its recent peak. Steam's idle ramp is 254 -> 7 over about 30 s, so it
      shows this in the first seconds. A user sliding the brightness down looks the same at first.
    - restore: the level rose by `rise` from its lowest point, or is back within `back_ratio` of the peak (a wake, input),
      or it stopped falling above `floor_ratio` for `settle_s` (a slider move that ended, not an idle ramp).
    After `suppress()` (the bottom panel was touched) it will not dim again until the top has recovered to its peak.
    """

    def __init__(self, fall_s: float = 2.5, fall_drop: float = 0.06, peak_ratio: float = 0.95, back_ratio: float = 0.97,
                 rise: float = 0.15, settle_s: float = 4.0, floor_ratio: float = 0.06, keep_s: float = 120.0) -> None:
        self.fall_s, self.fall_drop, self.peak_ratio, self.back_ratio, self.rise = fall_s, fall_drop, peak_ratio, back_ratio, rise
        self.settle_s, self.floor_ratio, self.keep_s = settle_s, floor_ratio, keep_s
        self.reset()

    def reset(self) -> None:
        self._hist: list[tuple[float, float]] = []
        self.dimmed = False
        self._lowest = 1.0
        self._since = 0.0
        self._latched = False

    def suppress(self) -> None:
        """The bottom was touched while dimmed: stay up until the top has recovered, whatever it does meanwhile."""
        self.dimmed = False
        self._latched = True

    def update(self, now: float, level: float) -> str | None:
        self._hist.append((now, level))
        while self._hist and now - self._hist[0][0] > self.keep_s:
            self._hist.pop(0)
        peak = max(lv for _t, lv in self._hist)
        if self._latched and level >= self.back_ratio * peak:
            self._latched = False
        if self.dimmed:
            self._lowest = min(self._lowest, level)
            if level >= self._lowest + self.rise or level >= self.back_ratio * peak:
                self.dimmed = False
                return "restore"
            if level > self.floor_ratio and now - self._since >= self.settle_s:
                recent = [lv for t, lv in self._hist if now - t <= self.settle_s]
                if len(recent) >= 3 and max(recent) - min(recent) < 0.01:
                    self.dimmed = False  # it stopped above the floor: a slider move, not Steam's idle ramp
                    return "restore"
            return None
        if self._latched:
            return None
        window = [(t, lv) for t, lv in self._hist if now - t <= self.fall_s]
        if len(window) >= 3 and now - window[0][0] >= self.fall_s * 0.8:
            steady = all(b[1] <= a[1] + 0.005 for a, b in zip(window, window[1:]))
            if steady and window[0][1] > 0 and (window[0][1] - level) / window[0][1] >= self.fall_drop and level <= self.peak_ratio * peak:
                self.dimmed, self._lowest, self._since = True, level, now
                return "dim"
        return None
