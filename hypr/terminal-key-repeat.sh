#!/usr/bin/env bash
action="$1"
keycode="$2"
generation="$3"
sound="$4"
state_dir="${XDG_RUNTIME_DIR:-/tmp}/terminal-key-repeat"
stop_marker="$state_dir/stop-$keycode-$generation"

mkdir -p "$state_dir"

if [ "$action" = "stop" ]; then
    : > "$stop_marker"
    exit 0
fi

[[ "$generation" =~ ^[0-9]+$ ]] || exit 1
for marker in "$state_dir"/stop-*; do
    marker_generation="${marker##*-}"
    if [[ "$marker_generation" =~ ^[0-9]+$ ]] && (( marker_generation < generation - 50 || marker_generation > generation )); then
        rm -f "$marker"
    fi
done

[ -f "$sound" ] || exit 1
pw-play "$sound" &

settings_cache="$state_dir/settings"
hyprland_config="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprland.lua"
repeat_rate=""
repeat_delay=""
if [ -f "$settings_cache" ] && [ ! "$hyprland_config" -nt "$settings_cache" ]; then
    read -r repeat_rate repeat_delay < "$settings_cache"
fi
if ! [[ "$repeat_rate" =~ ^[0-9]+$ && "$repeat_delay" =~ ^[0-9]+$ ]]; then
    repeat_rate=$(hyprctl getoption input:repeat_rate 2>/dev/null | awk '/^int:/ {print $2}')
    repeat_delay=$(hyprctl getoption input:repeat_delay 2>/dev/null | awk '/^int:/ {print $2}')
    [[ "$repeat_rate" =~ ^[0-9]+$ ]] || repeat_rate=25
    [[ "$repeat_delay" =~ ^[0-9]+$ ]] || repeat_delay=600
    printf '%s %s\n' "$repeat_rate" "$repeat_delay" > "$settings_cache.$$" && mv -f "$settings_cache.$$" "$settings_cache"
fi

if [ "$repeat_rate" -le 0 ]; then
    rm -f "$stop_marker"
    exit 0
fi

printf -v delay_seconds '%d.%03d' $((repeat_delay / 1000)) $((repeat_delay % 1000))
repeat_microseconds=$((1000000 / repeat_rate))
printf -v repeat_interval '%d.%06d' $((repeat_microseconds / 1000000)) $((repeat_microseconds % 1000000))

sleep "$delay_seconds"
for ((count = 0; count < 3000; count++)); do
    [ -e "$stop_marker" ] && break
    pw-play "$sound" &
    sleep "$repeat_interval"
done

rm -f "$stop_marker"
