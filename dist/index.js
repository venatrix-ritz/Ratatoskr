const manifest = { "name": "Thor Input" };
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
const setSettings = (sensitivity, glide, debug_hud) => call("set_settings", sensitivity, glide, debug_hud);
const toggleHud = () => call("toggle_hud");
const runDiagnostics = () => call("run_diagnostics");

function Content() {
    const [status, setStatus] = SP_REACT.useState({
        enabled: false,
        mode: "trackpad",
        sensitivity: 1.5,
        glide: true,
        debug_hud: false,
        telemetry: {},
        touch_device: "",
        state: "IDLE"
    });
    const [loading, setLoading] = SP_REACT.useState(true);
    const [diagRunning, setDiagRunning] = SP_REACT.useState(false);

    const refreshStatus = SP_REACT.useCallback(async () => {
        try {
            const s = await getStatus();
            if (s) setStatus(s);
        } catch (e) {
            console.error("[thor-input] getStatus error:", e);
        } finally {
            setLoading(false);
        }
    }, []);

    SP_REACT.useEffect(() => {
        refreshStatus();
        const interval = setInterval(refreshStatus, 2500);
        return () => clearInterval(interval);
    }, [refreshStatus]);

    const handleToggleEnabled = async (val) => {
        setStatus((prev) => ({ ...prev, enabled: val }));
        try {
            const res = await setEnabled(val);
            if (res) setStatus(res);
        } catch (e) {
            toaster.toast({ title: "Thor Input", body: "Failed to toggle: " + String(e) });
            refreshStatus();
        }
    };

    const handleModeChange = async (newMode) => {
        setStatus((prev) => ({ ...prev, mode: newMode }));
        try {
            await setMode(newMode);
        } catch (e) {
            toaster.toast({ title: "Thor Input", body: "Failed to set mode: " + String(e) });
            refreshStatus();
        }
    };

    const handleSensitivityChange = async (val) => {
        const rounded = Math.round(val * 10) / 10;
        setStatus((prev) => ({ ...prev, sensitivity: rounded }));
        try {
            await setSettings(rounded, status.glide, status.debug_hud);
        } catch (e) {
            console.error("[thor-input] setSettings error:", e);
        }
    };

    const handleGlideToggle = async (val) => {
        setStatus((prev) => ({ ...prev, glide: val }));
        try {
            await setSettings(status.sensitivity, val, status.debug_hud);
        } catch (e) {
            console.error("[thor-input] setSettings error:", e);
        }
    };

    const handleHudToggle = async () => {
        try {
            const res = await toggleHud();
            if (res && res.debug_hud !== undefined) {
                setStatus((prev) => ({ ...prev, debug_hud: res.debug_hud }));
            }
        } catch (e) {
            toaster.toast({ title: "Thor Input", body: "Failed to toggle HUD: " + String(e) });
        }
    };

    const handleRunDiagnostics = async () => {
        setDiagRunning(true);
        try {
            const rep = await runDiagnostics();
            if (rep && rep.all_passed) {
                toaster.toast({
                    title: "Diagnostics: PASSED [DBG-000]",
                    body: "uinput, touchscreen (event5), and display pipeline all healthy."
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
        { data: "keyboard", label: "Keyboard" }
    ];

    const telem = status.telemetry || {};

    return SP_JSX.jsxs(SP_JSX.Fragment, {
        children: [
            SP_JSX.jsxs(DFL.PanelSection, {
                title: "Thor Bottom Input",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Enable Bottom Screen",
                            description: "Turns bottom AMOLED screen into trackpad / keyboard",
                            checked: status.enabled,
                            disabled: loading,
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
            status.enabled && status.mode !== "keyboard" && SP_JSX.jsxs(DFL.PanelSection, {
                title: "Trackpad Settings",
                children: [
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.SliderField, {
                            label: "Pointer Sensitivity",
                            value: status.sensitivity,
                            min: 0.5,
                            max: 3.5,
                            step: 0.1,
                            showValue: true,
                            onChange: handleSensitivityChange
                        })
                    }),
                    SP_JSX.jsx(DFL.PanelSectionRow, {
                        children: SP_JSX.jsx(DFL.ToggleField, {
                            label: "Momentum Glide (Ball Mode)",
                            description: "Cursor coasts smoothly when flicked",
                            checked: status.glide,
                            onChange: handleGlideToggle
                        })
                    })
                ]
            }),
            SP_JSX.jsxs(DFL.PanelSection, {
                title: "Diagnostics & Telemetry",
                children: [
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
                            label: "Telemetry Stats",
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
        name: "Thor Input",
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
