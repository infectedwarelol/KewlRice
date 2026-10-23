#!/usr/bin/env bash
format='{{status}}'$'\t''{{title}}'$'\t''{{mpris:length}}'$'\t''{{position}}'
exec 9<> <(:)

escape() {
    local text="$1"
    text="${text//&/&amp;}"
    text="${text//</&lt;}"
    text="${text//>/&gt;}"
    text="${text//\\/\\\\}"
    text="${text//\"/\\\"}"
    printf -v "$2" '%s' "$text"
}

clock() {
    local seconds=$(( ${1:-0} / 1000000 ))
    printf -v "$2" '%02d:%02d' $((seconds / 60)) $((seconds % 60))
}

shorten() {
    local text="$1" limit="$2"
    if [ "${#text}" -gt "$limit" ]; then
        printf -v "$3" '%s…' "${text:0:limit-1}"
    else
        printf -v "$3" '%s' "$text"
    fi
}

previous=""
while true; do
    metadata=$(playerctl metadata --format "$format" 2>/dev/null)
    IFS=$'\t' read -r status title length position <<< "$metadata"
    if [[ "$status" != "Playing" && "$status" != "Paused" ]] || [ -z "$title" ]; then
        line='{"text":"","class":"stopped"}'
        delay=3
    else
        [[ "$length" =~ ^[0-9]+$ ]] || length=0
        [[ "$position" =~ ^[0-9]+$ ]] || position=0
        bare_title="${title%% (*}"
        bare_title="${bare_title%% [*}"
        [ -n "$bare_title" ] || bare_title="$title"
        shorten "$bare_title" 28 short_title
        escape "$short_title" safe_label
        escape "$title" safe_tooltip
        time_text=""
        if [ "$length" -gt 0 ]; then
            [ "$position" -gt "$length" ] && position=$length
            clock "$position" elapsed_clock
            clock "$length" length_clock
            time_text="  <span fgalpha='60%'>$elapsed_clock / $length_clock</span>"
        fi
        line="{\"text\":\"<span weight='bold'>$safe_label</span>$time_text\",\"class\":\"${status,,}\",\"tooltip\":\"$safe_tooltip\\nScroll to seek\"}"
        delay=1
    fi
    if [ "$line" != "$previous" ]; then
        printf '%s\n' "$line"
        previous="$line"
    fi
    read -r -t "$delay" -u 9 || true
done
