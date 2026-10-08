const manifest = { "name": "Ratatoskr" };
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to loader API.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
} catch {
    api = internalAPIConnection.connect(1, manifest.name);
}
const call = api.call;
const toaster = api.toaster;
const definePlugin = (fn) => (...args) => fn(...args);

const getStatus = () => call("get_status");
const setEnabled = (enabled) => call("set_enabled", enabled);
const setMode = (mode) => call("set_mode", mode);
const setSettings = (settings) => call("set_settings", settings);
const setVolume = (volume) => call("set_volume", volume);
const toggleMute = () => call("toggle_mute");
const setBrightness = (target, percent) => call("set_brightness", target, percent);
const toggleHud = () => call("toggle_hud");
const setPenMode = (mode) => call("set_pen_mode", mode);
const runDiagnostics = () => call("run_diagnostics");

// --- panel logic (pure functions, tested by tests/test_panel_logic.cjs) ---
const HOLD_MS = 3000;
const HARDWARE_KEYS = ["vol_pct", "vol_muted", "top_bright_pct", "bot_bright_pct"];

// The 2 s status poll must not undo a change that was just made: for HOLD_MS after a control is touched, the value
// the user set wins over what the poll brought back (the driver may not have applied it yet).
function mergeStatus(prev, next, editedAt, now) {
    const held = (key) => key in editedAt && now - editedAt[key] < HOLD_MS;
    const out = { ...prev, ...next };
    for (const key of Object.keys(next)) {
        if (key !== "hardware_stats" && held(key)) out[key] = prev[key];
    }
    if (next.hardware_stats) {
        const before = prev.hardware_stats || {};
        const hw = { ...before, ...next.hardware_stats };
        for (const key of HARDWARE_KEYS) {
            if (held(key) && key in before) hw[key] = before[key];
        }
        out.hardware_stats = hw;
    }
    return out;
}

// A slider fires onChange for every step. Send the first value at once, then at most one more per gapMs, always the
// latest, so a drag costs a handful of backend calls instead of dozens. flush() sends what is still waiting.
function makeThrottle(setTimer, gapMs) {
    const slots = {};
    function next(key) {
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
    function throttled(key, send) {
        const slot = slots[key];
        if (slot) {
            slot.pending = send;
            return;
        }
        slots[key] = { pending: null, timer: setTimer(() => next(key), gapMs) };
        send();
    }
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
// --- end panel logic ---

function Content() {
    const [status, setStatus] = SP_REACT.useState({
        enabled: false,
        mode: "trackpad",
        sensitivity: 1.5,
        glide: true,
        friction: 5,
        scroll_speed: 3,
        tap_to_click: true,
        long_press_right_click: false,
        long_press_delay_ms: 450,
        two_finger_right_click: true,
        three_finger_middle_click: false,
        pinch_zoom_enabled: false,
        three_finger_swipe_enabled: false,
        drag_lock_enabled: false,
        mirror_dim: false,
        pen_mode: "off",
        debug_hud: false,
        telemetry: {},
        hardware_stats: {},
        touch_device: "",
        state: "IDLE"
    });
    const [loading, setLoading] = SP_REACT.useState(true);
    const [inFlight, setInFlight] = SP_REACT.useState(false);
    const [diagRunning, setDiagRunning] = SP_REACT.useState(false);
    const editedAt = SP_REACT.useRef({});
    const sendRef = SP_REACT.useRef(null);
    if (sendRef.current === null) sendRef.current = makeThrottle((fn, ms) => setTimeout(fn, ms), 120);
    const markEdited = (key) => { editedAt.current[key] = Date.now(); };

    const refreshStatus = SP_REACT.useCallback(async () => {
        if (inFlight) return;
        try {
            const s = await getStatus();
            if (s && !inFlight) setStatus((prev) => mergeStatus(prev, s, editedAt.current, Date.now()));
        } catch (e) {
            console.error("[touch-master] getStatus error:", e);
        } finally {
            setLoading(false);
        }
    }, [inFlight]);

    SP_REACT.useEffect(() => {
        refreshStatus();
        const interval = setInterval(refreshStatus, 2000);
        return () => {
            clearInterval(interval);
            sendRef.current.flush();
        };
    }, [refreshStatus]);

    const handleToggleEnabled = async (val) => {
        setInFlight(true);
        setStatus((prev) => ({ ...prev, enabled: val }));
        try {
            const res = await setEnabled(val);
            if (res) setStatus((prev) => ({ ...prev, ...res }));
        } catch (e) {
            toaster.toast({ title: "Ratatoskr", body: "Failed to toggle: " + String(e) });
            refreshStatus();
        } finally {
            setInFlight(false);
        }
    };

    const handleModeChange = async (newMode) => {
        markEdited("mode");
        setStatus((prev) => ({ ...prev, mode: newMode }));
        try {
            await setMode(newMode);
        } catch (e) {
            toaster.toast({ title: "Ratatoskr", body: "Failed to set mode: " + String(e) });
            refreshStatus();
        }
    };

    const updateSetting = async (key, val) => {
        markEdited(key);
        setStatus((prev) => ({ ...prev, [key]: val }));
        sendRef.current(key, async () => {
            try {
                await setSettings({ [key]: val });
            } catch (e) {
                console.error(`[touch-master] setSettings (${key}) error:`, e);
            }
            // two settings exclude each other in the driver (press-and-hold / two-finger right click): pick up the other one
            setTimeout(refreshStatus, 700);
        });
    };

    const handleVolumeChange = async (val) => {
        const rounded = Math.round(val);
        markEdited("vol_pct");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, vol_pct: rounded }
        }));
        sendRef.current("vol_pct", async () => {
            try {
                await setVolume(rounded);
            } catch (e) {
                console.error("[touch-master] setVolume error:", e);
            }
        });
    };

    const handlePenMode = async (mode) => {
        markEdited("pen_mode");
        setStatus((prev) => ({ ...prev, pen_mode: mode }));
        try {
            await setPenMode(mode);
        } catch (e) {
            console.error("[touch-master] setPenMode error:", e);
        }
    };

    const handleMuteToggle = async () => {
        markEdited("vol_muted");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, vol_muted: !(prev.hardware_stats || {}).vol_muted }
        }));
        try {
            const res = await toggleMute();
            if (res && res.vol_muted !== undefined) {
                setStatus((prev) => ({
                    ...prev,
                    hardware_stats: { ...prev.hardware_stats, vol_muted: res.vol_muted }
                }));
            }
        } catch (e) {
            console.error("[touch-master] toggleMute error:", e);
        }
    };

    const handleTopBrightnessChange = async (val) => {
        const rounded = Math.round(val);
        markEdited("top_bright_pct");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, top_bright_pct: rounded }
        }));
        sendRef.current("top_bright_pct", async () => {
            try {
                await setBrightness("top", rounded);
            } catch (e) {
                console.error("[touch-master] setBrightness top error:", e);
            }
        });
    };

    const handleBotBrightnessChange = async (val) => {
        const rounded = Math.round(val);
        markEdited("bot_bright_pct");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, bot_bright_pct: rounded }
        }));
        sendRef.current("bot_bright_pct", async () => {
            try {
                await setBrightness("bottom", rounded);
            } catch (e) {
                console.error("[touch-master] setBrightness bot error:", e);
            }
        });
    };

    const handleHudToggle = async () => {
        markEdited("debug_hud");
        setStatus((prev) => ({ ...prev, debug_hud: !prev.debug_hud }));
        try {
            const res = await toggleHud();
            if (res && res.debug_hud !== undefined) {
                setStatus((prev) => ({ ...prev, debug_hud: res.debug_hud }));
            }
        } catch (e) {
            toaster.toast({ title: "Ratatoskr", body: "Failed to toggle HUD: " + String(e) });
        }
    };

    const handleRunDiagnostics = async () => {
        setDiagRunning(true);
        try {
            const rep = await runDiagnostics();
            if (rep && rep.all_passed) {
                toaster.toast({
                    title: "Diagnostics: PASSED [DBG-000]",
                    body: "uinput, touchscreen digitizer, and secondary display all healthy."
                });
            } else {
                toaster.toast({
                    title: "Diagnostics: WARNING",
                    body: JSON.stringify(rep?.checks || {})
                });
            }
        } catch (e) {
            toaster.toast({ title: "Diagnostics Error", body: String(e) });
        } finally {
            setDiagRunning(false);
            refreshStatus();
        }
    };

    const modeOptions = [
        { data: "trackpad", label: "Trackpad" },
        { data: "split", label: "Split (Mouse + Keyboard)" },
        { data: "keyboard", label: "Keyboard" },
        { data: "settings", label: "Quick Settings & Controls" }
    ];

    const telem = status.telemetry || {};
    const hw = status.hardware_stats || {};

    return SP_JSX.jsxs(SP_JSX.Fragment, {
        children: [
            SP_JSX.jsxs(DFL.PanelSection, {
                title: "Ratatoskr: Mode & Status",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Enable Bottom Screen",
                            description: "Turns bottom AMOLED screen into virtual trackpad & keyboard",
                            checked: status.enabled,
                            disabled: loading || inFlight,
                            onChange: handleToggleEnabled
                        })
                    }),
                    status.enabled && SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.Field, {
                            label: "Input Mode",
                            childrenLayout: "below",
                            childrenContainerWidth: "max",
                            children: SP_JSX.jsx(DFL.Dropdown, {
                                selectedOption: status.mode,
                                rgOptions: modeOptions,
                                onChange: (opt) => handleModeChange(opt.data)
                            })
                        })
                    })
                ]
            }),
            status.enabled && SP_JSX.jsxs(DFL.PanelSection, {
                title: "Quick Hardware Controls",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Master Volume: ${hw.vol_pct ?? 40}%` + (hw.vol_muted ? " [MUTED]" : ""),
                            value: hw.vol_pct ?? 40,
                            min: 0,
                            max: 100,
                            step: 5,
                            showValue: true,
                            onChange: handleVolumeChange
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Mute Audio",
                            checked: hw.vol_muted ?? false,
                            onChange: handleMuteToggle
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Top Screen Brightness: ${hw.top_bright_pct ?? 100}%`,
                            value: hw.top_bright_pct ?? 100,
                            min: 5,
                            max: 100,
                            step: 5,
                            showValue: true,
                            onChange: handleTopBrightnessChange
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Bottom AMOLED Brightness: ${hw.bot_bright_pct ?? 100}%`,
                            value: hw.bot_bright_pct ?? 100,
                            min: 5,
                            max: 100,
                            step: 5,
                            showValue: true,
                            onChange: handleBotBrightnessChange
                        })
                    })
                ]
            }),
            status.enabled && status.mode !== "keyboard" && status.mode !== "settings" && SP_JSX.jsxs(DFL.PanelSection, {
                title: "Trackpad & Pointer Dynamics",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Pointer Sensitivity: ${status.sensitivity}x`,
                            value: status.sensitivity,
                            min: 0.5,
                            max: 3.5,
                            step: 0.1,
                            showValue: true,
                            onChange: (val) => updateSetting("sensitivity", Math.round(val * 10) / 10)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Momentum Glide (Ball Mode)",
                            description: "Cursor coasts smoothly when flicked across the glass",
                            checked: status.glide,
                            onChange: (val) => updateSetting("glide", val)
                        })
                    }),
                    status.glide && SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Glide Friction: ${status.friction ?? 5}/10 ` + (status.friction <= 3 ? "(Slick)" : status.friction >= 8 ? "(Heavy Drag)" : "(Balanced)"),
                            description: "Adjust deceleration rate when flicking the cursor",
                            value: status.friction ?? 5,
                            min: 1,
                            max: 10,
                            step: 1,
                            showValue: true,
                            onChange: (val) => updateSetting("friction", Math.round(val))
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Scroll Speed: ${status.scroll_speed ?? 3}/5`,
                            description: "Precision vs fast scrolling velocity",
                            value: status.scroll_speed ?? 3,
                            min: 1,
                            max: 5,
                            step: 1,
                            showValue: true,
                            onChange: (val) => updateSetting("scroll_speed", Math.round(val))
                        })
                    })
                ]
            }),
            status.enabled && status.mode !== "keyboard" && status.mode !== "settings" && SP_JSX.jsxs(DFL.PanelSection, {
                title: "Gestures & Clicks",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Tap to Click",
                            description: "1-finger tap performs primary left click",
                            checked: status.tap_to_click ?? true,
                            onChange: (val) => updateSetting("tap_to_click", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Long-Press for Right Click",
                            description: "Hold 1 finger still to trigger secondary right click",
                            checked: status.long_press_right_click ?? false,
                            onChange: (val) => updateSetting("long_press_right_click", val)
                        })
                    }),
                    (status.long_press_right_click ?? false) && SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: `Long-Press Delay: ${status.long_press_delay_ms ?? 450} ms`,
                            value: status.long_press_delay_ms ?? 450,
                            min: 250,
                            max: 900,
                            step: 50,
                            showValue: true,
                            onChange: (val) => updateSetting("long_press_delay_ms", Math.round(val))
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Two-Finger Right Click Tap",
                            description: "2-finger tap emits right click",
                            checked: status.two_finger_right_click ?? true,
                            onChange: (val) => updateSetting("two_finger_right_click", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Three-Finger Middle Click Tap",
                            description: "3-finger tap emits middle click",
                            checked: status.three_finger_middle_click ?? false,
                            onChange: (val) => updateSetting("three_finger_middle_click", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Pinch to Zoom",
                            description: "Not implemented yet: this switch is saved but does nothing",
                            checked: status.pinch_zoom_enabled ?? false,
                            onChange: (val) => updateSetting("pinch_zoom_enabled", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Three-Finger Navigation Swipes",
                            description: "Up = Super/Steam, Down = Escape, Left/Right = Alt+Tab",
                            checked: status.three_finger_swipe_enabled ?? false,
                            onChange: (val) => updateSetting("three_finger_swipe_enabled", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Drag Lock",
                            description: "Not implemented yet: this switch is saved but does nothing",
                            checked: status.drag_lock_enabled ?? false,
                            onChange: (val) => updateSetting("drag_lock_enabled", val)
                        })
                    })
                ]
            }),
            SP_JSX.jsxs(DFL.PanelSection, {
                title: "Screens",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Dim bottom screen with the top",
                            description: "Dims the bottom screen after Steam's idle-dim delay (Steam > Settings > Display) and restores it on any input",
                            checked: status.mirror_dim ?? false,
                            onChange: (val) => updateSetting("mirror_dim", val)
                        })
                    })
                ]
            }),
            status.enabled && SP_JSX.jsxs(DFL.PanelSection, {
                title: "Pen",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Pen mode",
                            description: "For a stylus: one touch moves the pointer, double-tap clicks, hold right-clicks, the edge strips scroll. Gestures are off.",
                            checked: (status.pen_mode ?? "off") !== "off",
                            onChange: (val) => handlePenMode(val ? ((status.pen_mode ?? "off") === "pen_plus" ? "pen_plus" : "pen") : "off")
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Pen +",
                            description: (status.pen_mode ?? "off") === "pen_plus"
                                ? (status.cursor_stay_visible_active
                                    ? "On: Game Mode no longer hides the pointer, so no nudges are needed."
                                    : "On, but the running Game Mode still has the old setting. Reboot or restart Game Mode to apply; until then Pen's nudges stay on.")
                                : "Also keeps Game Mode's pointer visible so scrolling needs no nudges. Takes effect the next time Game Mode starts.",
                            checked: (status.pen_mode ?? "off") === "pen_plus",
                            onChange: (val) => handlePenMode(val ? "pen_plus" : ((status.pen_mode ?? "off") === "off" ? "off" : "pen"))
                        })
                    })
                ]
            }),
            SP_JSX.jsxs(DFL.PanelSection, {
                title: "Diagnostics & Telemetry",
                children: [
                    status.enabled && SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.Field, {
                            label: "System Health Monitor",
                            description: `Bat: ${hw.bat_cap ?? 0}% (${hw.bat_watts ?? 0}W) | CPU: ${hw.cpu_load ?? 0}% (${hw.cpu_temp ?? 0}°C) | GPU: ${hw.gpu_mhz ?? 0}M (${hw.gpu_temp ?? 0}°C) | RAM: ${hw.ram_used_gb ?? 0}/${hw.ram_total_gb ?? 0}G`
                        })
                    }),
                    status.enabled && SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Bottom Screen HUD Overlay",
                            description: "Renders live coordinates, FPS, and event stats on glass",
                            checked: status.debug_hud,
                            onChange: handleHudToggle
                        })
                    }),
                    status.enabled && SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.Field, {
                            label: "Input Telemetry Stats",
                            description: `Moves: ${telem.mouse_moves || 0} | Scrolls: ${telem.scrolls || 0} | Clicks: ${(telem.clicks_left || 0) + (telem.clicks_right || 0)} | Keys: ${telem.keystrokes || 0}`
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ButtonItem, {
                            layout: "below",
                            disabled: diagRunning,
                            onClick: handleRunDiagnostics,
                            children: diagRunning ? "Testing..." : "Run Self-Test Diagnostics"
                        })
                    })
                ]
            })
        ]
    });
}

const index = definePlugin((serverApi) => {
    return {
        name: "Ratatoskr",
        content: SP_JSX.jsx(Content, {}),
        icon: SP_JSX.jsx("svg", {
            xmlns: "http://www.w3.org/2000/svg",
            viewBox: "0 0 24 24",
            width: "24",
            height: "24",
            fill: "none",
            stroke: "currentColor",
            strokeWidth: "2",
            strokeLinecap: "round",
            strokeLinejoin: "round",
            children: [
                SP_JSX.jsx("rect", { x: "2", y: "4", width: "20", height: "16", rx: "3" }),
                SP_JSX.jsx("path", { d: "M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10" })
            ]
        }),
        onDismount() {}
    };
});

export { index as default };
