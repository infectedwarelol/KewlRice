#!/usr/bin/env python3
import fcntl
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib

BARS_PATH = "/tmp/kewlrice-visualizer.png"
DISC_PATH = "/tmp/kewlrice-disc.png"
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK_FILE = os.path.join(RUNTIME_DIR, "kewl-visualizer.lock")
CONFIG_DIR = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
COLORS_FILE = os.path.join(CONFIG_DIR, "waybar", "colors.css")
ALBUM_ART_SCRIPT = os.path.join(CONFIG_DIR, "waybar", "album-art.sh")
FALLBACK_ACCENT = "#f0a050"
BAR_COUNT = 5
FRAMERATE = 30
FRAME_INTERVAL = 0.05
MAX_LEVEL = 1000
BARS_CANVAS = 64
BAR_WIDTH = 5.0
BAR_GAP = 7.0
MIN_HEIGHT = BAR_WIDTH
SMOOTHING = 0.35
DISC_CANVAS = 104
SECONDS_PER_TURN = 8.0
STATUS_INTERVAL = 1.0
CAVA_CONFIG = f"""
[general]
bars = {BAR_COUNT}
framerate = {FRAMERATE}
sleep_timer = 0

[output]
method = raw
channels = mono
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = {MAX_LEVEL}
bar_delimiter = 59
frame_delimiter = 10

[smoothing]
noise_reduction = 66
monstercat = 1
"""


def run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def accent_rgb():
    try:
        with open(COLORS_FILE, encoding="utf-8") as colors:
            match = re.search(r"@define-color\s+kewl_accent\s+#([0-9a-fA-F]{6})", colors.read())
    except OSError:
        match = None
    color = match.group(1) if match else FALLBACK_ACCENT.lstrip("#")
    return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))


def player_status():
    status = run("playerctl", "status")
    return status if status in ("Playing", "Paused") else None


def fullscreen_active():
    try:
        workspace = json.loads(run("hyprctl", "activeworkspace", "-j") or "{}")
    except ValueError:
        return False
    return bool(workspace.get("hasfullscreen"))


def album_art_path():
    path = run(ALBUM_ART_SCRIPT).splitlines()
    return path[0] if path and os.path.isfile(path[0]) else ""


def load_art(path):
    if not path:
        return None
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    except GLib.Error:
        return None
    side = min(pixbuf.get_width(), pixbuf.get_height())
    if side <= 0:
        return None
    square = pixbuf.new_subpixbuf((pixbuf.get_width() - side) // 2, (pixbuf.get_height() - side) // 2, side, side)
    return square.scale_simple(DISC_CANVAS, DISC_CANVAS, GdkPixbuf.InterpType.BILINEAR)


def write_png(surface, path):
    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".kewlrice-", suffix=".png")
    os.close(descriptor)
    try:
        surface.write_to_png(temporary)
        os.replace(temporary, path)
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def rounded_bar(context, x, y, width, height):
    radius = width / 2
    context.new_sub_path()
    context.arc(x + radius, y + radius, radius, math.pi, 0)
    context.arc(x + radius, y + height - radius, radius, 0, math.pi)
    context.close_path()


def render_bars(levels, color):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, BARS_CANVAS, BARS_CANVAS)
    context = cairo.Context(surface)
    context.set_source_rgb(*color)
    total_width = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP
    start_x = (BARS_CANVAS - total_width) / 2
    for index, level in enumerate(levels):
        height = max(MIN_HEIGHT, level * BARS_CANVAS * 0.9)
        rounded_bar(context, start_x + index * (BAR_WIDTH + BAR_GAP), (BARS_CANVAS - height) / 2, BAR_WIDTH, height)
    context.fill()
    write_png(surface, BARS_PATH)


def render_disc(art, angle, color):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, DISC_CANVAS, DISC_CANVAS)
    context = cairo.Context(surface)
    center = DISC_CANVAS / 2
    context.translate(center, center)
    context.rotate(angle)
    context.arc(0, 0, center, 0, 2 * math.pi)
    context.clip()
    if art is not None:
        Gdk.cairo_set_source_pixbuf(context, art, -art.get_width() / 2, -art.get_height() / 2)
    else:
        context.set_source_rgb(*color)
    context.paint()
    write_png(surface, DISC_PATH)


def parse(line):
    values = []
    for part in line.strip().split(";"):
        if part.isdigit():
            values.append(min(int(part), MAX_LEVEL) / MAX_LEVEL)
    return values if len(values) == BAR_COUNT else None


def clear():
    remove(BARS_PATH)
    remove(DISC_PATH)


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)

    config_path = os.path.join(RUNTIME_DIR, "kewl-visualizer-cava.conf")
    with open(config_path, "w", encoding="utf-8") as config:
        config.write(CAVA_CONFIG)

    cava = subprocess.Popen(["cava", "-p", config_path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def stop(*_args):
        cava.terminate()
        clear()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    color = accent_rgb()
    smoothed = [0.0] * BAR_COUNT
    status = player_status()
    fullscreen = fullscreen_active()
    art_path = album_art_path() if status else ""
    art = load_art(art_path)
    angle = 0.0
    last_status_check = time.monotonic()
    last_frame = 0.0
    if status is None:
        clear()

    for line in cava.stdout:
        now = time.monotonic()
        if now - last_status_check >= STATUS_INTERVAL:
            last_status_check = now
            previous_status = status
            status = player_status()
            fullscreen = fullscreen_active()
            color = accent_rgb()
            if status is None:
                if previous_status is not None:
                    clear()
                art_path, art = "", None
            else:
                current_path = album_art_path()
                if current_path != art_path:
                    art_path, art = current_path, load_art(current_path)

        levels = parse(line)
        if levels is not None:
            smoothed = [previous + (target - previous) * (1 - SMOOTHING) for previous, target in zip(smoothed, levels)]

        if status is None or fullscreen:
            last_frame = 0.0
            continue
        if now - last_frame < FRAME_INTERVAL:
            continue

        if status == "Playing" and last_frame:
            angle = (angle + (now - last_frame) * 2 * math.pi / SECONDS_PER_TURN) % (2 * math.pi)
        last_frame = now

        render_bars(smoothed, color)
        render_disc(art, angle, color)

    clear()


if __name__ == "__main__":
    main()
