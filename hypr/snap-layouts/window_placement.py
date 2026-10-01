import json
import subprocess

OUTER_GAP = 20
INNER_GAP = 10


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def dispatch(expression):
    hyprctl("dispatch", expression)


def usable_area():
    monitor = next(m for m in json.loads(hyprctl("monitors", "-j")) if m["focused"])
    left, top, right, bottom = monitor["reserved"]
    scale = monitor["scale"]
    width = monitor["width"] / scale
    height = monitor["height"] / scale
    x = monitor["x"] + left + OUTER_GAP
    y = monitor["y"] + top + OUTER_GAP
    return x, y, width - left - right - 2 * OUTER_GAP, height - top - bottom - 2 * OUTER_GAP


def zone_geometry(zone, area):
    _, zx, zy, zw, zh = zone
    ax, ay, aw, ah = area
    x = ax + zx * aw + (INNER_GAP / 2 if zx > 0 else 0)
    y = ay + zy * ah + (INNER_GAP / 2 if zy > 0 else 0)
    right = ax + (zx + zw) * aw - (INNER_GAP / 2 if zx + zw < 0.999 else 0)
    bottom = ay + (zy + zh) * ah - (INNER_GAP / 2 if zy + zh < 0.999 else 0)
    return round(x), round(y), round(right - x), round(bottom - y)


def place(window, zone, area, workspace):
    target = "address:" + window["address"]
    if window["workspace"]["name"] != workspace:
        dispatch(f'hl.dsp.window.move({{ workspace = "{workspace}", window = "{target}", follow = false }})')
    if window["fullscreen"]:
        dispatch(f'hl.dsp.focus({{ window = "{target}" }})')
        dispatch('hl.dsp.window.fullscreen({ action = "unset" })')
    x, y, w, h = zone_geometry(zone, area)
    dispatch(f'hl.dsp.window.float({{ action = "set", window = "{target}" }})')
    dispatch(f'hl.dsp.window.resize({{ x = {w}, y = {h}, window = "{target}" }})')
    dispatch(f'hl.dsp.window.move({{ x = {x}, y = {y}, window = "{target}" }})')
