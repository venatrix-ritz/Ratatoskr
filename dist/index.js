const manifest = { "name": "Touch Master" };
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
const runDiagnostics = () => call("run_diagnostics");

function Content() {
    const [status, setStatus] = SP_REACT.useState({
        enabled: false,
        mode: "trackpad",
        sensitivity: 1.5,
        glide: true,
        friction: 5,
        scroll_speed: 3,
        edge_scroll: false,
        tap_to_click: true,
        long_press_right_click: true,
        long_press_delay_ms: 450,
        two_finger_right_click: true,
        three_finger_middle_click: true,
        pinch_zoom_enabled: true,
        three_finger_swipe_enabled: true,
        drag_lock_enabled: true,
        debug_hud: false,
        telemetry: {},
        hardware_stats: {},
        touch_device: "",
        state: "IDLE"
    });
    const [loading, setLoading] = SP_REACT.useState(true);
    const [inFlight, setInFlight] = SP_REACT.useState(false);
    const [diagRunning, setDiagRunning] = SP_REACT.useState(false);

    const refreshStatus = SP_REACT.useCallback(async () => {
        if (inFlight) return;
        try {
            const s = await getStatus();
            if (s && !inFlight) setStatus((prev) => ({ ...prev, ...s }));
        } catch (e) {
            console.error("[touch-master] getStatus error:", e);
        } finally {
            setLoading(false);
        }
    }, [inFlight]);

    SP_REACT.useEffect(() => {
        refreshStatus();
        const interval = setInterval(refreshStatus, 2000);
        return () => clearInterval(interval);
    }, [refreshStatus]);

    const handleToggleEnabled = async (val) => {
        setInFlight(true);
        setStatus((prev) => ({ ...prev, enabled: val }));
        try {
            const res = await setEnabled(val);
            if (res) setStatus((prev) => ({ ...prev, ...res }));
        } catch (e) {
            toaster.toast({ title: "Touch Master", body: "Failed to toggle: " + String(e) });
            refreshStatus();
        } finally {
            setInFlight(false);
        }
    };

    const handleModeChange = async (newMode) => {
        setStatus((prev) => ({ ...prev, mode: newMode }));
        try {
            await setMode(newMode);
        } catch (e) {
            toaster.toast({ title: "Touch Master", body: "Failed to set mode: " + String(e) });
            refreshStatus();
        }
    };

    const updateSetting = async (key, val) => {
        setStatus((prev) => ({ ...prev, [key]: val }));
        try {
            await setSettings({ [key]: val });
        } catch (e) {
            console.error(`[touch-master] setSettings (${key}) error:`, e);
        }
    };

    const handleVolumeChange = async (val) => {
        const rounded = Math.round(val);
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, vol_pct: rounded }
        }));
        try {
            await setVolume(rounded);
        } catch (e) {
            console.error("[touch-master] setVolume error:", e);
        }
    };

    const handleMuteToggle = async () => {
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
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, top_bright_pct: rounded }
        }));
        try {
            await setBrightness("top", rounded);
        } catch (e) {
            console.error("[touch-master] setBrightness top error:", e);
        }
    };

    const handleBotBrightnessChange = async (val) => {
        const rounded = Math.round(val);
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, bot_bright_pct: rounded }
        }));
        try {
            await setBrightness("bottom", rounded);
        } catch (e) {
            console.error("[touch-master] setBrightness bot error:", e);
        }
    };

    const handleHudToggle = async () => {
        try {
            const res = await toggleHud();
            if (res && res.debug_hud !== undefined) {
                setStatus((prev) => ({ ...prev, debug_hud: res.debug_hud }));
            }
        } catch (e) {
            toaster.toast({ title: "Touch Master", body: "Failed to toggle HUD: " + String(e) });
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
                title: "Touch Master: Mode & Status",
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
                title: "Scroll Mode",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Edge Scroll instead of Two-Finger",
                            description: "Draws an on-glass scrollbar on the right edge. Single finger drag in gutter scrolls; 2-finger scroll is disabled",
                            checked: status.edge_scroll ?? false,
                            onChange: (val) => updateSetting("edge_scroll", val)
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
                            checked: status.long_press_right_click ?? true,
                            onChange: (val) => updateSetting("long_press_right_click", val)
                        })
                    }),
                    (status.long_press_right_click ?? true) && SP_JSX.jsx(DFL.PanelSectionRow, {
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
                            checked: status.three_finger_middle_click ?? true,
                            onChange: (val) => updateSetting("three_finger_middle_click", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Pinch to Zoom",
                            description: "2-finger pinch emits Ctrl+Wheel zoom",
                            checked: status.pinch_zoom_enabled ?? true,
                            onChange: (val) => updateSetting("pinch_zoom_enabled", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Three-Finger Navigation Swipes",
                            description: "Up = Super/Steam, Down = Escape, Left/Right = Alt+Tab",
                            checked: status.three_finger_swipe_enabled ?? true,
                            onChange: (val) => updateSetting("three_finger_swipe_enabled", val)
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Drag Lock",
                            description: "Double-tap and drag to hold left mouse button",
                            checked: status.drag_lock_enabled ?? true,
                            onChange: (val) => updateSetting("drag_lock_enabled", val)
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
        name: "Touch Master",
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
