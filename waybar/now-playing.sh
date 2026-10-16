#!/usr/bin/env bash
format='{{status}}'$'\t''{{title}}'$'\t''{{artist}}'$'\t''{{mpris:length}}'$'\t''{{position}}'
IFS=$'\t' read -r status title artist length position < <(playerctl metadata --format "$format" 2>/dev/null)
if [[ "$status" != "Playing" && "$status" != "Paused" ]] || [ -z "$title" ]; then
    printf '{"text":"","class":"stopped"}\n'
    exit 0
fi
escape() {
    local text="$1"
    text="${text//&/&amp;}"
    text="${text//</&lt;}"
    text="${text//>/&gt;}"
    text="${text//\\/\\\\}"
    text="${text//\"/\\\"}"
    printf '%s' "$text"
}
shorten() {
    local text="$1" limit="$2"
    if [ "${#text}" -gt "$limit" ]; then
        printf '%s…' "${text:0:limit-1}"
    else
        printf '%s' "$text"
    fi
}
clock() {
    local seconds=$(( ${1:-0} / 1000000 ))
    printf '%d:%02d' $((seconds / 60)) $((seconds % 60))
}
[[ "$length" =~ ^[0-9]+$ ]] || length=0
[[ "$position" =~ ^[0-9]+$ ]] || position=0
width=14
filled=0
[ "$length" -gt 0 ] && filled=$(( position * width / length ))
[ "$filled" -gt "$width" ] && filled=$width
bar_done=$(printf '%*s' "$filled" '' | tr ' ' '-')
bar_left=$(printf '%*s' $((width - filled)) '' | tr ' ' '-')
bar_done="${bar_done//-/━}"
bar_left="${bar_left//-/━}"
line="$(shorten "$title" 22)"
[ -n "$artist" ] && line="$line · $(shorten "$artist" 14)"
text="<span weight='bold'>$(escape "$line")</span>\\n<span size='7.5pt'>${bar_done}<span fgalpha='30%'>${bar_left}</span>  $(clock "$position")/$(clock "$length")</span>"
printf '{"text":"%s","class":"%s","tooltip":"%s"}\n' "$text" "${status,,}" "$(escape "$title — $artist")"
