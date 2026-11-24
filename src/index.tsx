import { ButtonItem, Dropdown, Field, PanelSection, PanelSectionRow, SliderField, ToggleField } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { makeThrottle, mergeStatus, Throttled } from "./panelLogic";

interface HardwareStats {
    vol_pct?: number;
    vol_muted?: boolean;
    top_bright_pct?: number;
    bot_bright_pct?: number;
    bat_cap?: number;
    bat_watts?: number;
    cpu_load?: number;
    cpu_temp?: number;
    gpu_mhz?: number;
    gpu_temp?: number;
    ram_used_gb?: number;
    ram_total_gb?: number;
}

interface Telemetry {
    mouse_moves?: number;
    scrolls?: number;
    clicks_left?: number;
    clicks_right?: number;
    keystrokes?: number;
}

interface Status {
    enabled: boolean;
    mode: string;
    sensitivity: number;
    glide: boolean;
    friction: number;
    scroll_speed: number;
    tap_to_click: boolean;
    long_press_right_click: boolean;
    long_press_delay_ms: number;
    two_finger_right_click: boolean;
    three_finger_middle_click: boolean;
    three_finger_swipe_enabled: boolean;
    mirror_dim: boolean;
    keyboard_repeat_delay_ms: number;
    keyboard_repeat_interval_ms: number;
    keyboard_caps_window_ms: number;
    gleipnir_ribbon: boolean;
    gleipnir_available: boolean;
    ps_mode_auto: boolean;
    ps_focused: boolean;
    haptics: boolean;
    haptics_available: boolean;
    pen_mode: string;
    cursor_stay_visible_active?: boolean;
    telemetry: Telemetry;
    hardware_stats: HardwareStats;
    touch_device: string;
    state: string;
}

interface Diagnostics {
    all_passed?: boolean;
    checks?: Record<string, unknown>;
}

const getStatus = callable<[], Partial<Status>>("get_status");
const setEnabled = callable<[enabled: boolean], Partial<Status>>("set_enabled");
const setMode = callable<[mode: string], unknown>("set_mode");
const setSettings = callable<[settings: Partial<Status>], unknown>("set_settings");
const setVolume = callable<[volume: number], unknown>("set_volume");
const toggleMute = callable<[], { vol_muted?: boolean }>("toggle_mute");
const setBrightness = callable<[target: string, percent: number], unknown>("set_brightness");
const setPenMode = callable<[mode: string], unknown>("set_pen_mode");
const runDiagnostics = callable<[], Diagnostics>("run_diagnostics");

function Content() {
    const [status, setStatus] = useState<Status>({
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
        three_finger_swipe_enabled: false,
        mirror_dim: false,
        keyboard_repeat_delay_ms: 350,
        keyboard_repeat_interval_ms: 60,
        keyboard_caps_window_ms: 350,
        gleipnir_ribbon: false,
        gleipnir_available: false,
        ps_mode_auto: true,
        ps_focused: false,
        haptics: true,
        haptics_available: false,
        pen_mode: "off",
        telemetry: {},
        hardware_stats: {},
        touch_device: "",
        state: "IDLE",
    });
    const [loading, setLoading] = useState(true);
    const [inFlight, setInFlight] = useState(false);
    const [diagRunning, setDiagRunning] = useState(false);
    const editedAt = useRef<Record<string, number>>({});
    const sendRef = useRef<Throttled | null>(null);
    if (sendRef.current === null) sendRef.current = makeThrottle((fn, ms) => setTimeout(fn, ms), 120);
    const send = sendRef.current;
    const markEdited = (key: string) => {
        editedAt.current[key] = Date.now();
    };

    const refreshStatus = useCallback(async () => {
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

    useEffect(() => {
        refreshStatus();
        const interval = setInterval(refreshStatus, 2000);
        return () => {
            clearInterval(interval);
            send.flush();
        };
    }, [refreshStatus]);

    const handleToggleEnabled = async (val: boolean) => {
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

    const handleModeChange = async (newMode: string) => {
        markEdited("mode");
        setStatus((prev) => ({ ...prev, mode: newMode }));
        try {
            await setMode(newMode);
        } catch (e) {
            toaster.toast({ title: "Ratatoskr", body: "Failed to set mode: " + String(e) });
            refreshStatus();
        }
    };

    const updateSetting = async <K extends keyof Status>(key: K, val: Status[K]) => {
        markEdited(key);
        setStatus((prev) => ({ ...prev, [key]: val }));
        send(key, async () => {
            try {
                await setSettings({ [key]: val } as Partial<Status>);
            } catch (e) {
                console.error(`[touch-master] setSettings (${key}) error:`, e);
            }
            // two settings exclude each other in the driver (press-and-hold / two-finger right click): pick up the other one
            setTimeout(refreshStatus, 700);
        });
    };

    const handleVolumeChange = async (val: number) => {
        const rounded = Math.round(val);
        markEdited("vol_pct");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, vol_pct: rounded },
        }));
        send("vol_pct", async () => {
            try {
                await setVolume(rounded);
            } catch (e) {
                console.error("[touch-master] setVolume error:", e);
            }
        });
    };

    const handlePenMode = async (mode: string) => {
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
            hardware_stats: { ...prev.hardware_stats, vol_muted: !(prev.hardware_stats || ({} as HardwareStats)).vol_muted },
        }));
        try {
            const res = await toggleMute();
            if (res && res.vol_muted !== undefined) {
                setStatus((prev) => ({
                    ...prev,
                    hardware_stats: { ...prev.hardware_stats, vol_muted: res.vol_muted },
                }));
            }
        } catch (e) {
            console.error("[touch-master] toggleMute error:", e);
        }
    };

    const handleTopBrightnessChange = async (val: number) => {
        const rounded = Math.round(val);
        markEdited("top_bright_pct");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, top_bright_pct: rounded },
        }));
        send("top_bright_pct", async () => {
            try {
                await setBrightness("top", rounded);
            } catch (e) {
                console.error("[touch-master] setBrightness top error:", e);
            }
        });
    };

    const handleBotBrightnessChange = async (val: number) => {
        const rounded = Math.round(val);
        markEdited("bot_bright_pct");
        setStatus((prev) => ({
            ...prev,
            hardware_stats: { ...prev.hardware_stats, bot_bright_pct: rounded },
        }));
        send("bot_bright_pct", async () => {
            try {
                await setBrightness("bottom", rounded);
            } catch (e) {
                console.error("[touch-master] setBrightness bot error:", e);
            }
        });
    };

    const handleRunDiagnostics = async () => {
        setDiagRunning(true);
        try {
            const rep = await runDiagnostics();
            if (rep && rep.all_passed) {
                toaster.toast({
                    title: "Diagnostics: PASSED [DBG-000]",
                    body: "uinput, touchscreen digitizer, and secondary display all healthy.",
                });
            } else {
                toaster.toast({
                    title: "Diagnostics: WARNING",
                    body: JSON.stringify(rep?.checks || {}),
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
        { data: "settings", label: "Quick Settings & Controls" },
        { data: "ps", label: "PS Touchpad (Chiaki-NG)" },
    ];

    const telem: Telemetry = status.telemetry || {};
    const hw: HardwareStats = status.hardware_stats || {};
    const penMode = status.pen_mode ?? "off";

    return (
        <>
            <PanelSection title="Ratatoskr: Mode & Status">
                <PanelSectionRow>
                    <ToggleField
                        label="Enable Bottom Screen"
                        description="Turns bottom AMOLED screen into virtual trackpad & keyboard"
                        checked={status.enabled}
                        disabled={loading || inFlight}
                        onChange={handleToggleEnabled}
                    />
                </PanelSectionRow>
                {status.enabled && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Haptic feedback"
                            description={
                                status.haptics_available
                                    ? "A short buzz for every tap click, key, on-screen button and PS button"
                                    : "A short buzz for every tap click, key and button (the haptics motor was not found)"
                            }
                            checked={status.haptics ?? true}
                            onChange={(val) => updateSetting("haptics", val)}
                        />
                    </PanelSectionRow>
                )}
                {status.enabled && (
                    <PanelSectionRow>
                        <Field label="Input Mode" childrenLayout="below" childrenContainerWidth="max">
                            <Dropdown
                                selectedOption={status.mode}
                                rgOptions={modeOptions}
                                onChange={(opt) => handleModeChange(opt.data)}
                            />
                        </Field>
                    </PanelSectionRow>
                )}
            </PanelSection>
            {status.enabled && (
                <PanelSection title="Quick Hardware Controls">
                    <PanelSectionRow>
                        <SliderField
                            label={`Master Volume: ${hw.vol_pct ?? 40}%` + (hw.vol_muted ? " [MUTED]" : "")}
                            value={hw.vol_pct ?? 40}
                            min={0}
                            max={100}
                            step={5}
                            showValue={true}
                            onChange={handleVolumeChange}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField label="Mute Audio" checked={hw.vol_muted ?? false} onChange={handleMuteToggle} />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <SliderField
                            label={`Top Screen Brightness: ${hw.top_bright_pct ?? 100}%`}
                            value={hw.top_bright_pct ?? 100}
                            min={1}
                            max={100}
                            step={5}
                            showValue={true}
                            onChange={handleTopBrightnessChange}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <SliderField
                            label={`Bottom AMOLED Brightness: ${hw.bot_bright_pct ?? 100}%`}
                            value={hw.bot_bright_pct ?? 100}
                            min={1}
                            max={100}
                            step={5}
                            showValue={true}
                            onChange={handleBotBrightnessChange}
                        />
                    </PanelSectionRow>
                </PanelSection>
            )}
            {status.enabled && status.mode !== "keyboard" && status.mode !== "settings" && (
                <PanelSection title="Trackpad & Pointer Dynamics">
                    <PanelSectionRow>
                        <SliderField
                            label={`Pointer Sensitivity: ${status.sensitivity}x`}
                            value={status.sensitivity}
                            min={0.5}
                            max={3.5}
                            step={0.1}
                            showValue={true}
                            onChange={(val) => updateSetting("sensitivity", Math.round(val * 10) / 10)}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField
                            label="Momentum Glide (Ball Mode)"
                            description="Cursor coasts smoothly when flicked across the glass"
                            checked={status.glide}
                            onChange={(val) => updateSetting("glide", val)}
                        />
                    </PanelSectionRow>
                    {status.glide && (
                        <PanelSectionRow>
                            <SliderField
                                label={
                                    `Glide Friction: ${status.friction ?? 5}/10 ` +
                                    (status.friction <= 3 ? "(Slick)" : status.friction >= 8 ? "(Heavy Drag)" : "(Balanced)")
                                }
                                description="Adjust deceleration rate when flicking the cursor"
                                value={status.friction ?? 5}
                                min={1}
                                max={10}
                                step={1}
                                showValue={true}
                                onChange={(val) => updateSetting("friction", Math.round(val))}
                            />
                        </PanelSectionRow>
                    )}
                    <PanelSectionRow>
                        <SliderField
                            label={`Scroll Speed: ${status.scroll_speed ?? 3}/5`}
                            description="Precision vs fast scrolling velocity"
                            value={status.scroll_speed ?? 3}
                            min={1}
                            max={5}
                            step={1}
                            showValue={true}
                            onChange={(val) => updateSetting("scroll_speed", Math.round(val))}
                        />
                    </PanelSectionRow>
                </PanelSection>
            )}
            {status.enabled && status.mode !== "keyboard" && status.mode !== "settings" && (
                <PanelSection title="Gestures & Clicks">
                    <PanelSectionRow>
                        <ToggleField
                            label="Tap to Click"
                            description="1-finger tap performs primary left click"
                            checked={status.tap_to_click ?? true}
                            onChange={(val) => updateSetting("tap_to_click", val)}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField
                            label="Long-Press for Right Click"
                            description="Hold 1 finger still to trigger secondary right click"
                            checked={status.long_press_right_click ?? false}
                            onChange={(val) => updateSetting("long_press_right_click", val)}
                        />
                    </PanelSectionRow>
                    {(status.long_press_right_click ?? false) && (
                        <PanelSectionRow>
                            <SliderField
                                label={`Long-Press Delay: ${status.long_press_delay_ms ?? 450} ms`}
                                value={status.long_press_delay_ms ?? 450}
                                min={250}
                                max={900}
                                step={50}
                                showValue={true}
                                onChange={(val) => updateSetting("long_press_delay_ms", Math.round(val))}
                            />
                        </PanelSectionRow>
                    )}
                    <PanelSectionRow>
                        <ToggleField
                            label="Two-Finger Right Click Tap"
                            description="2-finger tap emits right click"
                            checked={status.two_finger_right_click ?? true}
                            onChange={(val) => updateSetting("two_finger_right_click", val)}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField
                            label="Three-Finger Middle Click Tap"
                            description="3-finger tap emits middle click"
                            checked={status.three_finger_middle_click ?? false}
                            onChange={(val) => updateSetting("three_finger_middle_click", val)}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField
                            label="Three-Finger Navigation Swipes"
                            description="Up = Super/Steam, Down = Escape, Left/Right = Alt+Tab"
                            checked={status.three_finger_swipe_enabled ?? false}
                            onChange={(val) => updateSetting("three_finger_swipe_enabled", val)}
                        />
                    </PanelSectionRow>
                </PanelSection>
            )}
            <PanelSection title="Screens">
                <PanelSectionRow>
                    <ToggleField
                        label="Dim bottom screen with the top"
                        description="Dims the bottom screen after Steam's idle-dim delay (Steam > Settings > Display) and restores it on any input"
                        checked={status.mirror_dim ?? false}
                        onChange={(val) => updateSetting("mirror_dim", val)}
                    />
                </PanelSectionRow>
                {(status.gleipnir_available || status.gleipnir_ribbon) && (
                    <PanelSectionRow>
                        <ToggleField
                            label="Show Gleipnir in the status ribbon"
                            description="The battery item shows the 80 % cap (held, charging toward it, or off), and Quick Controls gets a Gleipnir status line. Read-only."
                            checked={status.gleipnir_ribbon ?? false}
                            onChange={(val) => updateSetting("gleipnir_ribbon", val)}
                        />
                    </PanelSectionRow>
                )}
                <PanelSectionRow>
                    <ToggleField
                        label="PS touchpad while Chiaki-NG has focus"
                        description={
                            status.ps_focused
                                ? "Chiaki-NG has focus: the bottom screen is the PS5 touchpad (tap to click, hold to keep it pressed) with Create, PS, Options and Mic"
                                : "Switches the bottom screen to the PS5 touchpad and PS buttons while Chiaki-NG streams, and back afterwards"
                        }
                        checked={status.ps_mode_auto ?? true}
                        onChange={(val) => updateSetting("ps_mode_auto", val)}
                    />
                </PanelSectionRow>
            </PanelSection>
            {status.enabled && (
                <PanelSection title="Keyboard">
                    <PanelSectionRow>
                        <SliderField
                            label={`Key Repeat Delay: ${status.keyboard_repeat_delay_ms ?? 350} ms`}
                            value={status.keyboard_repeat_delay_ms ?? 350}
                            min={150}
                            max={800}
                            step={50}
                            showValue={true}
                            onChange={(val) => updateSetting("keyboard_repeat_delay_ms", Math.round(val))}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <SliderField
                            label={`Key Repeat Interval: ${status.keyboard_repeat_interval_ms ?? 60} ms`}
                            value={status.keyboard_repeat_interval_ms ?? 60}
                            min={20}
                            max={200}
                            step={10}
                            showValue={true}
                            onChange={(val) => updateSetting("keyboard_repeat_interval_ms", Math.round(val))}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <SliderField
                            label={`Caps Lock Double-Tap: ${status.keyboard_caps_window_ms ?? 350} ms`}
                            value={status.keyboard_caps_window_ms ?? 350}
                            min={150}
                            max={800}
                            step={50}
                            showValue={true}
                            onChange={(val) => updateSetting("keyboard_caps_window_ms", Math.round(val))}
                        />
                    </PanelSectionRow>
                </PanelSection>
            )}
            {status.enabled && (
                <PanelSection title="Pen">
                    <PanelSectionRow>
                        <ToggleField
                            label="Pen mode"
                            description="For a stylus: one touch moves the pointer, double-tap clicks, hold right-clicks, the edge strips scroll. Gestures are off."
                            checked={penMode !== "off"}
                            onChange={(val) => handlePenMode(val ? (penMode === "pen_plus" ? "pen_plus" : "pen") : "off")}
                        />
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField
                            label="Pen +"
                            description={
                                penMode === "pen_plus"
                                    ? status.cursor_stay_visible_active
                                        ? "On: Game Mode no longer hides the pointer, so no nudges are needed."
                                        : "On, but the running Game Mode still has the old setting. Reboot or restart Game Mode to apply; until then Pen's nudges stay on."
                                    : "Also keeps Game Mode's pointer visible so scrolling needs no nudges. Takes effect the next time Game Mode starts."
                            }
                            checked={penMode === "pen_plus"}
                            onChange={(val) => handlePenMode(val ? "pen_plus" : penMode === "off" ? "off" : "pen")}
                        />
                    </PanelSectionRow>
                </PanelSection>
            )}
            <PanelSection title="Diagnostics & Telemetry">
                {status.enabled && (
                    <PanelSectionRow>
                        <Field
                            label="System Health Monitor"
                            description={`Bat: ${hw.bat_cap ?? 0}% (${hw.bat_watts ?? 0}W) | CPU: ${hw.cpu_load ?? 0}% (${hw.cpu_temp ?? 0}°C) | GPU: ${hw.gpu_mhz ?? 0}M (${hw.gpu_temp ?? 0}°C) | RAM: ${hw.ram_used_gb ?? 0}/${hw.ram_total_gb ?? 0}G`}
                        />
                    </PanelSectionRow>
                )}
                {status.enabled && (
                    <PanelSectionRow>
                        <Field
                            label="Input Telemetry Stats"
                            description={`Moves: ${telem.mouse_moves || 0} | Scrolls: ${telem.scrolls || 0} | Clicks: ${(telem.clicks_left || 0) + (telem.clicks_right || 0)} | Keys: ${telem.keystrokes || 0}`}
                        />
                    </PanelSectionRow>
                )}
                <PanelSectionRow>
                    <ButtonItem layout="below" disabled={diagRunning} onClick={handleRunDiagnostics}>
                        {diagRunning ? "Testing..." : "Run Self-Test Diagnostics"}
                    </ButtonItem>
                </PanelSectionRow>
            </PanelSection>
        </>
    );
}

export default definePlugin(() => ({
    name: "Ratatoskr",
    content: <Content />,
    icon: (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            width="24"
            height="24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <rect x="2" y="4" width="20" height="16" rx="3" />
            <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10" />
        </svg>
    ),
    onDismount() {},
}));
