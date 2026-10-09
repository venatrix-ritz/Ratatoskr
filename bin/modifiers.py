"""Modifier keys of the on-screen keyboard: Shift, Ctrl, Alt and Win.

Pure state machine, no GTK, so it is unit-tested (tests/test_modifiers.py). Each modifier is off, latched (one-shot: it
applies to the next key and is released when that key is released) or locked (stays on; Caps Lock for Shift).

- Tap a modifier: off -> latched. Tap it again within the double-tap window: latched -> locked. A later tap while it
  is latched turns it off; a tap while it is locked turns it off.
- Hold a modifier with one finger and type with another: it stays down while that finger is down, every key typed
  meanwhile gets it, and lifting the finger releases it.

Every method returns the key events to send, as (keycode, down) pairs; the caller writes them to the virtual keyboard.
Before 2026-10-09 the release of any keyboard touch cleared Shift, so a tapped Shift never reached the next key and
Caps Lock could not be turned on.
"""
from __future__ import annotations

CODES = {"shift": 42, "ctrl": 29, "alt": 56, "super": 125}  # KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_LEFTALT, KEY_LEFTMETA

OFF, LATCHED, LOCKED = "off", "latched", "locked"

Event = tuple[int, bool]


class ModifierState:
    def __init__(self) -> None:
        self.state: dict[str, str] = {m: OFF for m in CODES}
        self.held_by: dict[str, int] = {}        # modifier -> touch id of the finger holding it
        self.used_while_held: set[str] = set()   # held modifiers that a key was typed with
        self.last_tap: dict[str, float] = {}

    # -- queries ---------------------------------------------------------------------------------------
    def active(self, mod: str) -> bool:
        return self.state[mod] != OFF

    def locked(self, mod: str) -> bool:
        return self.state[mod] == LOCKED

    def latched(self, mod: str) -> bool:
        return self.state[mod] == LATCHED

    def is_modifier_touch(self, tid: int) -> bool:
        return tid in self.held_by.values()

    # -- events ----------------------------------------------------------------------------------------
    def press(self, mod: str, tid: int, now: float, double_tap_s: float) -> list[Event]:
        """A finger landed on a modifier key."""
        self.held_by[mod] = tid
        self.used_while_held.discard(mod)
        st = self.state[mod]
        if st == OFF:
            self.state[mod] = LATCHED
            self.last_tap[mod] = now
            return [(CODES[mod], True)]
        if st == LATCHED and now - self.last_tap.get(mod, -1e9) < double_tap_s:
            self.state[mod] = LOCKED
            return []  # already down
        self.state[mod] = OFF
        self.held_by.pop(mod, None)
        return [(CODES[mod], False)]

    def release(self, tid: int) -> list[Event]:
        """A finger left a modifier key. A modifier that was held while keys were typed is released with it;
        a plain tap leaves it latched for the next key."""
        events: list[Event] = []
        for mod in [m for m, t in self.held_by.items() if t == tid]:
            del self.held_by[mod]
            if mod in self.used_while_held:
                self.used_while_held.discard(mod)
                if self.state[mod] == LATCHED:
                    self.state[mod] = OFF
                    events.append((CODES[mod], False))
        return events

    def key_typed(self) -> None:
        """A non-modifier key was pressed: every modifier held by a finger has now been used."""
        self.used_while_held.update(self.held_by)

    def key_released(self) -> list[Event]:
        """A non-modifier key was released: latched modifiers that no finger holds are used up."""
        events: list[Event] = []
        for mod, st in self.state.items():
            if st == LATCHED and mod not in self.held_by:
                self.state[mod] = OFF
                events.append((CODES[mod], False))
        return events

    def release_all(self) -> list[Event]:
        """Leave the keyboard (mode switch, stop): every modifier goes up."""
        events = [(CODES[m], False) for m, st in self.state.items() if st != OFF]
        self.state = {m: OFF for m in CODES}
        self.held_by.clear()
        self.used_while_held.clear()
        return events
