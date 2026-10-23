import json
import os
import subprocess

WINDOWED_APPS = {"brave-browser", "firefox", "chromium", "google-chrome"}


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def list_windows():
    clients = [c for c in json.loads(hyprctl("clients", "-j")) if c.get("mapped", True) and c.get("workspace", {}).get("name") != "special:hidden"]
    return sorted(clients, key=lambda c: c["focusHistoryID"])


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
    if not window["fullscreen"] and window["class"].lower() not in WINDOWED_APPS:
        hyprctl("dispatch", 'hl.dsp.window.fullscreen({ action = "set" })')
