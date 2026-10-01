import json
import os
import subprocess

CLICK_SOUND = os.path.expanduser("~/.config/hypr/sounds/click.mp3")


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def list_windows():
    clients = [c for c in json.loads(hyprctl("clients", "-j")) if c.get("mapped", True)]
    return sorted(clients, key=lambda c: c["focusHistoryID"])


def switcher_menu_is_open():
    layers = json.loads(hyprctl("layers", "-j"))
    return any(
        layer.get("namespace") == "rofi"
        for monitor in layers.values()
        for level in monitor["levels"].values()
        for layer in level
    )


def active_window_address():
    return json.loads(hyprctl("activewindow", "-j") or "{}").get("address")


def switch_to_window(window):
    target = "address:" + window["address"]
    if window["workspace"]["name"].startswith("special:"):
        current = json.loads(hyprctl("activeworkspace", "-j"))["name"]
        hyprctl("dispatch", f'hl.dsp.window.move({{ workspace = "{current}", window = "{target}", follow = false }})')
    hyprctl("dispatch", f'hl.dsp.focus({{ window = "{target}" }})')
    if active_window_address() != window["address"]:
        return
    if window["fullscreen"]:
        subprocess.Popen(["pw-play", CLICK_SOUND])
    else:
        hyprctl("dispatch", 'hl.dsp.window.fullscreen({ action = "set" })')
