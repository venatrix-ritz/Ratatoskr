// Tests for the Decky panel's pure helpers (run: node tests/test_panel_logic.cjs). Loads only the block between the
// "panel logic" markers of dist/index.js; the rest of that file needs Decky's runtime.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const src = fs.readFileSync(path.join(__dirname, "..", "dist", "index.js"), "utf8");
const start = src.indexOf("// --- panel logic");
const end = src.indexOf("// --- end panel logic ---");
assert(start >= 0 && end > start, "panel logic markers not found");
const ctx = vm.createContext({});
vm.runInContext(src.slice(start, end) + "\nthis.mergeStatus = mergeStatus; this.makeThrottle = makeThrottle; this.HOLD_MS = HOLD_MS;", ctx);
const { mergeStatus, makeThrottle, HOLD_MS } = ctx;

let passed = 0;
function test(name, fn) {
    fn();
    passed += 1;
    console.log("ok", name);
}

function fakeTimers() {
    const queue = [];
    return {
        setTimer: (fn, ms) => { queue.push({ fn, ms }); return queue.length; },
        tick: () => { const t = queue.shift(); if (t) t.fn(); return !!t; },
        pending: () => queue.length,
    };
}

test("a poll does not undo a value that was just set", () => {
    const prev = { sensitivity: 2.0, glide: true, hardware_stats: { bot_bright_pct: 70, vol_pct: 30 } };
    const next = { sensitivity: 1.5, glide: true, hardware_stats: { bot_bright_pct: 40, vol_pct: 30 } };
    const out = mergeStatus(prev, next, { sensitivity: 1000, bot_bright_pct: 1000 }, 1000 + 500);
    assert.strictEqual(out.sensitivity, 2.0);
    assert.strictEqual(out.hardware_stats.bot_bright_pct, 70);
    assert.strictEqual(out.hardware_stats.vol_pct, 30);
});

test("after the hold the poll wins again", () => {
    const prev = { sensitivity: 2.0, hardware_stats: { bot_bright_pct: 70 } };
    const next = { sensitivity: 1.5, hardware_stats: { bot_bright_pct: 40 } };
    const out = mergeStatus(prev, next, { sensitivity: 1000, bot_bright_pct: 1000 }, 1000 + HOLD_MS + 1);
    assert.strictEqual(out.sensitivity, 1.5);
    assert.strictEqual(out.hardware_stats.bot_bright_pct, 40);
});

test("untouched values always follow the poll, and missing stats do not crash", () => {
    assert.strictEqual(mergeStatus({ mode: "trackpad" }, { mode: "keyboard" }, {}, 5).mode, "keyboard");
    const out = mergeStatus({}, { hardware_stats: { vol_pct: 10 } }, { vol_pct: 4 }, 5);
    assert.strictEqual(out.hardware_stats.vol_pct, 10);            // nothing local to keep
    assert.strictEqual(mergeStatus({ a: 1 }, {}, {}, 5).a, 1);
});

test("a drag of 30 steps costs the first value plus one per gap, and the last value is sent", () => {
    const t = fakeTimers();
    const throttled = makeThrottle(t.setTimer, 120);
    const sent = [];
    for (let v = 1; v <= 30; v++) throttled("bright", () => sent.push(v));
    assert.deepStrictEqual(sent, [1]);                              // only the first went out at once
    t.tick();                                                       // the gap passes: the latest pending value goes
    assert.deepStrictEqual(sent, [1, 30]);
    t.tick();                                                       // nothing new arrived: the slot is released
    assert.strictEqual(t.pending(), 0);                             // the slot is free and no timer is left running
    throttled("bright", () => sent.push(31));                       // a later drag starts fresh
    assert.strictEqual(sent[sent.length - 1], 31);
});

test("different controls throttle independently", () => {
    const t = fakeTimers();
    const throttled = makeThrottle(t.setTimer, 120);
    const sent = [];
    throttled("a", () => sent.push("a1"));
    throttled("b", () => sent.push("b1"));
    throttled("a", () => sent.push("a2"));
    assert.deepStrictEqual(sent, ["a1", "b1"]);
});

test("flush sends the value still waiting (panel closed mid-drag)", () => {
    const t = fakeTimers();
    const throttled = makeThrottle(t.setTimer, 120);
    const sent = [];
    throttled("x", () => sent.push(1));
    throttled("x", () => sent.push(2));
    throttled("x", () => sent.push(3));
    throttled.flush();
    assert.deepStrictEqual(sent, [1, 3]);
    throttled.flush();
    assert.deepStrictEqual(sent, [1, 3]);                           // nothing left to send twice
});

console.log(`${passed} panel checks passed`);
