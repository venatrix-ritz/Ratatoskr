#!/usr/bin/env python3
"""Configures Artemis client on AYN Thor for optimal 1080p 120Hz streaming."""
import configparser
import os
from pathlib import Path

CONF_PATH = Path("/var/home/armada/.config/Artemis Desktop Project/Artemis.conf")
INI_PATH_1 = Path("/var/home/armada/.config/Artemis Desktop Project/artemis-settings.ini")
INI_PATH_2 = Path("/var/home/armada/.config/Artemis Desktop Project/Artemis/artemis-settings.ini")

def update_artemis_conf():
    if not CONF_PATH.exists():
        print(f"Error: {CONF_PATH} does not exist")
        return

    # Use raw string preservation for QSettings INI format
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str  # Preserve case
    cfg.read(CONF_PATH)

    if not cfg.has_section("General"):
        cfg.add_section("General")

    settings = {
        "width": "1920",
        "height": "1080",
        "fps": "120",
        "bitrate": "40000",
        "unlockbitrate": "true",
        "autoadjustbitrate": "false",
        "vsync": "true",
        "gameopts": "true",
        "hostaudio": "false",
        "multicontroller": "true",
        "mdns": "true",
        "quitAppAfter": "false",
        "mouseacceleration": "false",
        "abstouchmode": "true",
        "framepacing": "false",
        "connwarnings": "true",
        "confwarnings": "false",
        "richpresence": "true",
        "gamepadmouse": "true",
        "packetsize": "1392",
        "detectnetblocking": "true",
        "showperfoverlay": "false",
        "swapmousebuttons": "false",
        "muteonfocusloss": "false",
        "backgroundgamepad": "false",
        "reversescroll": "false",
        "swapfacebuttons": "false",
        "capturesyskeys": "1",
        "keepawake": "true",
        "audiocfg": "0",
        "hdr": "false",
        "yuv444": "false",
        "videocfg": "0",       # Auto
        "videodec": "0",       # Auto (prevents fatal hardware decode preflight abort on Armada)
        "windowmode": "0",     # Fullscreen
        "uidisplaymode": "2",  # Fullscreen
        "language": "0",
        "rendererbackend": "0",
        "defaultver": "2",
        "virtualdisplay": "true",
        "fractionalrefreshrate": "false",
        "customrefreshrate": "120.0",
        "resolutionscaling": "false",
        "resolutionscalefactor": "1.0",
    }

    for k, v in settings.items():
        cfg.set("General", k, v)

    with open(CONF_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)

    print(f"Updated {CONF_PATH}")

def update_artemis_ini():
    content = """[ClientDisplay]
customRefreshRate=120
fractionalRefreshRateEnabled=false
resolutionScaleFactor=1
resolutionScalingEnabled=false
virtualDisplayEnabled=true

[ClipboardSync]
bidirectional=true
enabled=true
maxSize=1048576

[ServerCommands]
enabled=true
showAdvanced=true

[InputOnly]
enabled=false
"""
    for p in (INI_PATH_1, INI_PATH_2):
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Wrote {p}")

if __name__ == "__main__":
    update_artemis_conf()
    update_artemis_ini()
