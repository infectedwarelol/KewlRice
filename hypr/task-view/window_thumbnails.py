import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf


def hyprctl_json(*args):
    output = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True).stdout
    return json.loads(output) if output.strip() else None


def hyprctl_dispatch(expression):
    subprocess.run(["hyprctl", "dispatch", expression], capture_output=True)


def list_windows():
    clients = [c for c in hyprctl_json("clients") or [] if c.get("mapped", True)]
    return sorted(clients, key=lambda c: c["focusHistoryID"])


def focused_monitor():
    monitors = hyprctl_json("monitors")
    return next((m for m in monitors if m["focused"]), monitors[0])


def capture(window):
    try:
        raw = subprocess.run(
            ["grim", "-T", str(window["stableId"]), "-t", "ppm", "-"],
            capture_output=True,
            timeout=3,
        ).stdout
        if not raw:
            return None
        loader = GdkPixbuf.PixbufLoader.new_with_type("pnm")
        loader.write(raw)
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None


def capture_all(windows):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(capture, windows))


def switch_to(window):
    target = "address:" + window["address"]
    if window["workspace"]["name"].startswith("special:"):
        current = hyprctl_json("activeworkspace")["name"]
        hyprctl_dispatch(f'hl.dsp.window.move({{ workspace = "{current}", window = "{target}", follow = false }})')
    hyprctl_dispatch(f'hl.dsp.focus({{ window = "{target}" }})')
