#!/usr/bin/env python3
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.expanduser("~/.config/hypr/window-switcher"))

from desktop_icons import icon_names_by_window_class
from layout_icons import icon_path
from layouts import LAYOUTS
from window_placement import dispatch, hyprctl, place, usable_area

LAYOUT_MENU_THEME = (
    "listview { columns: 4; lines: 2; spacing: 6px; } "
    "element { orientation: vertical; padding: 8px; } "
    "element-icon { size: 112px; } "
    "element-text { horizontal-align: 0.5; }"
)
APP_MENU_THEME = "message { border: 0; padding: 4px 8px; } mainbox { children: [ inputbar, message, listview ]; }"


def rofi(rows, extra):
    menu = subprocess.run(
        ["rofi", "-dmenu", "-i", "-p", "", "-format", "i", *extra],
        input="".join(rows),
        capture_output=True,
        text=True,
    )
    choice = menu.stdout.strip()
    return int(choice) if menu.returncode == 0 and choice.isdigit() else None


def pick_layout():
    rows = [f"{name}\0icon\x1f{icon_path(i, zones)}\n" for i, (name, zones) in enumerate(LAYOUTS)]
    return rofi(rows, ["-theme-str", LAYOUT_MENU_THEME])


def pick_window(candidates, zones, zone_index, icons):
    rows = [
        f"{w['class']}   {w['title']}\0icon\x1f{icons.get(w['class'].lower(), w['class'].lower())}\n"
        for w in candidates
    ]
    zone_name = zones[zone_index][0]
    message = f"Pick the app for zone {zone_index + 1}: {zone_name}"
    return rofi(rows, ["-mesg", message, "-theme-str", APP_MENU_THEME])


def main():
    active = json.loads(hyprctl("activewindow", "-j") or "{}")
    if not active.get("address"):
        return
    layout_index = pick_layout()
    if layout_index is None:
        return
    _, zones = LAYOUTS[layout_index]
    workspace = active["workspace"]["name"]
    area = usable_area()
    place(active, zones[0], area, workspace)

    windows = sorted(
        (c for c in json.loads(hyprctl("clients", "-j")) if c.get("mapped", True)),
        key=lambda c: c["focusHistoryID"],
    )
    candidates = [w for w in windows if w["address"] != active["address"]]
    icons = icon_names_by_window_class()
    for zone_index in range(1, len(zones)):
        if not candidates:
            break
        choice = pick_window(candidates, zones, zone_index, icons)
        if choice is None:
            break
        place(candidates.pop(choice), zones[zone_index], area, workspace)

    dispatch(f'hl.dsp.focus({{ window = "address:{active["address"]}" }})')


if __name__ == "__main__":
    main()
