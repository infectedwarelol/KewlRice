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

[ -f "$sound" ] || exit 1
pw-play "$sound" &

repeat_rate=$(hyprctl getoption input:repeat_rate 2>/dev/null | awk '/^int:/ {print $2}')
repeat_delay=$(hyprctl getoption input:repeat_delay 2>/dev/null | awk '/^int:/ {print $2}')
[[ "$repeat_rate" =~ ^[0-9]+$ ]] || repeat_rate=25
[[ "$repeat_delay" =~ ^[0-9]+$ ]] || repeat_delay=600

if [ "$repeat_rate" -le 0 ]; then
    rm -f "$stop_marker"
    exit 0
fi

repeat_interval=$(awk -v rate="$repeat_rate" 'BEGIN { printf "%.4f", 1 / rate }')
delay_seconds=$(awk -v delay="$repeat_delay" 'BEGIN { printf "%.4f", delay / 1000 }')

sleep "$delay_seconds"
for _ in $(seq 1 3000); do
    [ -e "$stop_marker" ] && break
    pw-play "$sound" &
    sleep "$repeat_interval"
done

rm -f "$stop_marker"
