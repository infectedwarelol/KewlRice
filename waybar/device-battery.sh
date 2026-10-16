#!/usr/bin/env bash
for supply in /sys/class/power_supply/*; do
    [ -r "$supply/capacity" ] || continue
    [ "$(cat "$supply/type" 2>/dev/null)" = "Battery" ] || continue
    capacity=$(cat "$supply/capacity" 2>/dev/null)
    [[ "$capacity" =~ ^[0-9]+$ ]] || continue
    name=$(cat "$supply/model_name" 2>/dev/null)
    status=$(cat "$supply/status" 2>/dev/null)
    scope=$(cat "$supply/scope" 2>/dev/null)
    lowered="${name,,}"
    if [ "$scope" != "Device" ]; then
        kind="default"
    elif [[ "$lowered" == *mouse* || "$lowered" == *superlight* ]]; then
        kind="mouse"
    elif [[ "$lowered" == *keyboard* || "$lowered" == *keys* ]]; then
        kind="keyboard"
    else
        kind="headset"
    fi
    level="normal"
    [ "$capacity" -le 40 ] && level="medium"
    [ "$capacity" -le 20 ] && level="low"
    [ "$capacity" -le 10 ] && level="critical"
    [ "$status" = "Charging" ] && level="charging"
    name="${name//\\/}"
    name="${name//\"/}"
    printf '{"text":"%s%%","alt":"%s","class":"%s","tooltip":"%s  %s%% (%s)"}\n' \
        "$capacity" "$kind" "$level" "${name:-Battery}" "$capacity" "${status:-Unknown}"
    exit 0
done
printf '{"text":""}\n'
