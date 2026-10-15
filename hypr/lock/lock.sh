#!/usr/bin/env bash
if ! command -v hyprlock >/dev/null 2>&1; then
    notify-send -a "Lock screen" "Lock screen" "hyprlock is not installed: sudo pacman -S hyprlock"
    exit 1
fi
pidof hyprlock >/dev/null && exit 0
avatar="$HOME/.config/hypr/lock/avatar.png"
if [ ! -f "$avatar" ]; then
    for source in "$HOME/.face" /usr/share/sddm/themes/kewlrice/assets/avatar.png /usr/share/sddm/themes/purple-rice/assets/avatar.png; do
        [ -f "$source" ] && cp "$source" "$avatar" && break
    done
fi
sound="$HOME/.config/hypr/sounds/power-lock.mp3"
[ -f "$sound" ] && ( pw-play "$sound" >/dev/null 2>&1 & )
exec hyprlock
