#!/usr/bin/env bash
json_escape() {
    local text="${1//\\/\\\\}"
    text="${text//\"/\\\"}"
    text="${text//$'\t'/ }"
    printf '%s' "$text"
}

emit() {
    local status="$1" details="$2"
    case "$status" in
        Playing|Paused) ;;
        *) status="Stopped" details="Nothing playing" ;;
    esac
    [ -n "$details" ] && [ "$details" != " - " ] || details="$status"
    printf '{"text":"%s","alt":"%s","class":"%s","tooltip":"%s"}\n' \
        "$status" "$status" "${status,,}" "$(json_escape "$details")"
}

format='{{status}}'$'\t''{{artist}} - {{title}}'
while true; do
    line=$(playerctl metadata --format "$format" 2>/dev/null)
    emit "${line%%$'\t'*}" "${line#*$'\t'}"
    while IFS= read -r line; do
        emit "${line%%$'\t'*}" "${line#*$'\t'}"
    done < <(playerctl --follow metadata --format "$format" 2>/dev/null)
    sleep 2
done
