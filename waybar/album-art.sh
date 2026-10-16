#!/usr/bin/env bash
cache="${XDG_CACHE_HOME:-$HOME/.cache}/kewlrice/albumart"
status=$(playerctl status 2>/dev/null)
url=$(playerctl metadata mpris:artUrl 2>/dev/null)
if [[ "$status" != "Playing" && "$status" != "Paused" ]] || [ -z "$url" ]; then
    exit 0
fi
if [[ "$url" == file://* ]]; then
    path="${url#file://}"
    printf '%b\n' "${path//%/\\x}"
    exit 0
fi
mkdir -p "$cache"
target="$cache/$(printf '%s' "$url" | sha1sum | cut -c1-20).img"
if [ ! -f "$target" ]; then
    ( curl -sfL --max-time 8 "$url" -o "$target.$$" && mv -f "$target.$$" "$target" || rm -f "$target.$$" ) >/dev/null 2>&1 &
    exit 0
fi
printf '%s\n' "$target"
