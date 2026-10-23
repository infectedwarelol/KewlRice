#!/usr/bin/env bash
socket="$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock"

socat -U - "UNIX-CONNECT:$socket" | while IFS= read -r line; do
    case "$line" in
        minimized\>\>*,1)
            address="${line#minimized>>}"
            address="${address%,1}"
            hyprctl dispatch "hl.dsp.window.move({ workspace = \"special:minimized\", window = \"address:0x${address#0x}\", follow = false })" >/dev/null
            ;;
    esac
done
