import json
import subprocess

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf


def hyprctl_json(*args):
    output = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True).stdout
    return json.loads(output) if output.strip() else None


def focused_monitor():
    monitors = hyprctl_json("monitors")
    return next((m for m in monitors if m["focused"]), monitors[0])


def capture_monitor(monitor):
    raw = subprocess.run(["grim", "-t", "ppm", "-o", monitor["name"], "-"], capture_output=True).stdout
    loader = GdkPixbuf.PixbufLoader.new_with_type("pnm")
    loader.write(raw)
    loader.close()
    return loader.get_pixbuf()


def visible_windows(monitor):
    shown = {monitor["activeWorkspace"]["id"]}
    special = monitor.get("specialWorkspace") or {}
    if special.get("id"):
        shown.add(special["id"])
    windows = [
        c for c in hyprctl_json("clients") or []
        if c.get("mapped", True) and not c.get("hidden") and c["workspace"]["id"] in shown
    ]
    windows.sort(key=lambda c: (not c["floating"], c["focusHistoryID"]))
    return [
        (c["at"][0] - monitor["x"], c["at"][1] - monitor["y"], c["size"][0], c["size"][1])
        for c in windows
    ]
