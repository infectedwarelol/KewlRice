#!/usr/bin/env bash
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
lock_file="$runtime_dir/kewl-launcher.lock"
started_file="$runtime_dir/kewl-launcher.started"
double_press_window_ms=400

exec 9>"$lock_file"
if ! flock -n 9; then
    started_at=$(cat "$started_file" 2>/dev/null)
    [[ "$started_at" =~ ^[0-9]+$ ]] || started_at=0
    elapsed_ms=$(( ($(date +%s%N) - started_at) / 1000000 ))
    if [ "$elapsed_ms" -gt "$double_press_window_ms" ]; then
        pkill -x wofi
    fi
    exit 0
fi

date +%s%N > "$started_file"
wofi --show drun 9>&-
