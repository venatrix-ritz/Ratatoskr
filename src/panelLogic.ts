// Pure helpers for the Decky panel, kept free of Decky and React so tests/test_panel_logic.mjs can import this file
// with Node's type stripping (erasable TypeScript only: no enums, namespaces or parameter properties).

export const HOLD_MS = 3000;
const HARDWARE_KEYS = ["vol_pct", "vol_muted", "top_bright_pct", "bot_bright_pct"];

type Fields = Record<string, unknown>;

// The 2 s status poll must not undo a change that was just made: for HOLD_MS after a control is touched, the value
// the user set wins over what the poll brought back (the driver may not have applied it yet).
export function mergeStatus<T extends object>(prev: T, next: Partial<T>, editedAt: Record<string, number>, now: number): T {
    const held = (key: string): boolean => key in editedAt && now - editedAt[key] < HOLD_MS;
    const before = prev as Fields;
    const incoming = next as Fields;
    const out: Fields = { ...before, ...incoming };
    for (const key of Object.keys(incoming)) {
        if (key !== "hardware_stats" && held(key)) out[key] = before[key];
    }
    if (incoming.hardware_stats) {
        const prevHw = (before.hardware_stats || {}) as Fields;
        const hw: Fields = { ...prevHw, ...(incoming.hardware_stats as Fields) };
        for (const key of HARDWARE_KEYS) {
            if (held(key) && key in prevHw) hw[key] = prevHw[key];
        }
        out.hardware_stats = hw;
    }
    return out as T;
}

export type SetTimer = (fn: () => void, ms: number) => unknown;

export interface Throttled {
    (key: string, send: () => void): void;
    flush: () => void;
}

interface Slot {
    pending: (() => void) | null;
    timer: unknown;
}

// A slider fires onChange for every step. Send the first value at once, then at most one more per gapMs, always the
// latest, so a drag costs a handful of backend calls instead of dozens. flush() sends what is still waiting.
export function makeThrottle(setTimer: SetTimer, gapMs: number): Throttled {
    const slots: Record<string, Slot> = {};
    function next(key: string): void {
        const slot = slots[key];
        if (!slot) return;
        if (slot.pending) {
            const send = slot.pending;
            slot.pending = null;
            slot.timer = setTimer(() => next(key), gapMs);
            send();
        } else {
            delete slots[key];
        }
    }
    const throttled = ((key: string, send: () => void): void => {
        const slot = slots[key];
        if (slot) {
            slot.pending = send;
            return;
        }
        slots[key] = { pending: null, timer: setTimer(() => next(key), gapMs) };
        send();
    }) as Throttled;
    throttled.flush = () => {
        for (const key of Object.keys(slots)) {
            const slot = slots[key];
            if (slot.pending) {
                const send = slot.pending;
                slot.pending = null;
                send();
            }
        }
    };
    return throttled;
}
