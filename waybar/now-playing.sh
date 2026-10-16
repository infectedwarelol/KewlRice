#!/usr/bin/env bash
format='{{status}}'$'\t''{{title}}'$'\t''{{artist}}'$'\t''{{mpris:length}}'$'\t''{{position}}'
width=14
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

shorten() {
    local text="$1" limit="$2"
    if [ "${#text}" -gt "$limit" ]; then
        printf -v "$3" '%s…' "${text:0:limit-1}"
    else
        printf -v "$3" '%s' "$text"
    fi
}

clock() {
    local seconds=$(( ${1:-0} / 1000000 ))
    printf -v "$2" '%d:%02d' $((seconds / 60)) $((seconds % 60))
}

previous=""
while true; do
    metadata=$(playerctl metadata --format "$format" 2>/dev/null)
    IFS=$'\t' read -r status title artist length position <<< "$metadata"
    if [[ "$status" != "Playing" && "$status" != "Paused" ]] || [ -z "$title" ]; then
        line='{"text":"","class":"stopped"}'
        delay=3
    else
        [[ "$length" =~ ^[0-9]+$ ]] || length=0
        [[ "$position" =~ ^[0-9]+$ ]] || position=0
        filled=0
        [ "$length" -gt 0 ] && filled=$(( position * width / length ))
        [ "$filled" -gt "$width" ] && filled=$width
        printf -v done_bar '%*s' "$filled" ''
        printf -v left_bar '%*s' $((width - filled)) ''
        done_bar="${done_bar// /━}"
        left_bar="${left_bar// /━}"
        shorten "$title" 22 short_title
        label="$short_title"
        if [ -n "$artist" ]; then
            shorten "$artist" 14 short_artist
            label="$label · $short_artist"
        fi
        escape "$label" safe_label
        escape "$title — $artist" safe_tooltip
        clock "$position" elapsed
        clock "$length" total
        line="{\"text\":\"<span weight='bold'>$safe_label</span>\\n<span size='7.5pt'>${done_bar}<span fgalpha='30%'>${left_bar}</span>  $elapsed/$total</span>\",\"class\":\"${status,,}\",\"tooltip\":\"$safe_tooltip\"}"
        delay=1
    fi
    if [ "$line" != "$previous" ]; then
        printf '%s\n' "$line"
        previous="$line"
    fi
    read -r -t "$delay" -u 9 || true
done
