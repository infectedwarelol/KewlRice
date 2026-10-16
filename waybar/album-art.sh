#!/usr/bin/env bash
cache="${XDG_CACHE_HOME:-$HOME/.cache}/kewlrice/album-art"
IFS=$'\t' read -r status url < <(playerctl metadata --format '{{status}}'$'\t''{{mpris:artUrl}}' 2>/dev/null)
if [[ "$status" != "Playing" && "$status" != "Paused" ]] || [ -z "$url" ]; then
    exit 0
fi
if [[ "$url" == file://* ]]; then
    path="${url#file://}"
    printf '%b\n' "${path//%/\\x}"
    exit 0
fi
read -r hash _ < <(printf '%s' "$url" | sha1sum)
target="$cache/$hash.img"
if [ -f "$target" ]; then
    printf '%s\n' "$target"
    exit 0
fi
mkdir -p "$cache"
(
    curl -sfL --max-time 8 "$url" -o "$target.$$" && mv -f "$target.$$" "$target" || rm -f "$target.$$"
    ls -1t "$cache"/*.img 2>/dev/null | tail -n +101 | xargs -r rm -f
) >/dev/null 2>&1 &
