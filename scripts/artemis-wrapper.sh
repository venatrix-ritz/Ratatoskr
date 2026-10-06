#!/bin/bash
# Artemis Game Mode launcher for AYN Thor (Armada OS)

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"

export LD_LIBRARY_PATH="${HERE}/lib:${LD_LIBRARY_PATH}"
export XDG_DATA_DIRS="${HERE}/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

# In Steam Game Mode, Gamescope manages nested X11 clients (borderless fullscreen)
if [ -z "$DISPLAY" ]; then
    if [ -S "/tmp/.X11-unix/X1" ]; then
        export DISPLAY=:1
    elif [ -S "/tmp/.X11-unix/X0" ]; then
        export DISPLAY=:0
    fi
fi

# Ensure Qt and SDL use Gamescope's managed X11 display instead of raw Wayland CSD
unset QT_QPA_PLATFORM
unset WAYLAND_DISPLAY
unset GAMESCOPE_WAYLAND_DISPLAY
# SDL video driver for Gamescope nested X11
export SDL_VIDEODRIVER=x11

exec "${HERE}/bin/artemis.bin" "$@"
