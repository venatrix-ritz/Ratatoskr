"""Monochrome AMOLED stealth color palette for Ratatoskr.

Pure 0 IRE black base (#000000) with diodes completely unlit.
Hairline wireframe geometry, crisp desaturated typography, and momentary touch flare.
"""
from __future__ import annotations

# Pure black background (0 IRE - diodes physically off)
BG = (0.0, 0.0, 0.0)

# Hairline borders and dividers
BORDER_HAIRLINE = (0.14, 0.16, 0.20)
BORDER_SUBTLE = (0.10, 0.12, 0.15)
DIVIDER = (0.08, 0.09, 0.12)

# Typography (softened luminance to prevent burn-in)
TEXT_PRIMARY = (0.82, 0.85, 0.90)      # crisp neutral ice-white
TEXT_SECONDARY = (0.50, 0.54, 0.60)    # muted labels and hints
TEXT_DIM = (0.28, 0.30, 0.35)          # low-luminance corner text
TEXT_ACTIVE = (1.0, 1.0, 1.0)          # momentary highlight on press

# Button states
BTN_BORDER_INACTIVE = (0.15, 0.17, 0.22)
BTN_FILL_ACTIVE = (0.22, 0.25, 0.32)   # momentary touch flare
BTN_BORDER_ACTIVE = (0.65, 0.70, 0.82)
BTN_ACCENT_DEFAULT = (0.22, 0.25, 0.32)

# Keyboard key states
KEY_BORDER_INACTIVE = (0.14, 0.16, 0.20)
KEY_BORDER_SHIFTED = (0.25, 0.28, 0.35)
KEY_FILL_ACTIVE = (0.22, 0.25, 0.32)
KEY_BORDER_ACTIVE = (0.65, 0.70, 0.82)

# Sliders & cards
CARD_BORDER = (0.12, 0.14, 0.18)
TRACK_BORDER = (0.18, 0.20, 0.26)
SLIDER_FILL = (0.70, 0.75, 0.85)       # clean monochrome fill

# Telemetry ribbon pills (desaturated / softened to prevent burn-in)
PILL_BAT = (0.35, 0.75, 0.50)
PILL_CPU = (0.50, 0.68, 0.82)
PILL_GPU = (0.80, 0.65, 0.40)
PILL_RAM = (0.65, 0.55, 0.75)
PILL_VOL = (0.50, 0.75, 0.80)
PILL_VOL_MUTED = (0.75, 0.40, 0.40)
PILL_BRT = (0.80, 0.75, 0.45)

# Pen mode scroll strips
STRIP_BORDER = (0.65, 0.50, 0.20)
STRIP_TEXT = (0.75, 0.60, 0.25)
