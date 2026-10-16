#!/usr/bin/env python3
import fcntl
import json
import math
import os
import socket
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

import cairo

CONFIG_DIR = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
COLORS_FILE = os.path.join(CONFIG_DIR, "hypr", "window-frame", "colors.json")
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK_FILE = os.path.join(RUNTIME_DIR, "kewl-window-frame.lock")
FALLBACK_COLORS = {
    "background": "#261f30",
    "foreground": "#fbeef3",
    "primary": "#e27aa0",
    "secondary": "#559cbe",
    "accent": "#f5a9c4",
    "urgent": "#ffcc66",
}
TERMINAL_CLASSES = {
    "kitty", "foot", "footclient", "alacritty", "org.wezfurlong.wezterm", "com.mitchellh.ghostty",
    "konsole", "org.kde.konsole",
}
REFRESH_EVENTS = {
    "openwindow", "closewindow", "movewindow", "movewindowv2", "workspace", "workspacev2", "focusedmon",
    "focusedmonv2", "activewindowv2", "changefloatingmode", "fullscreen", "activespecial", "activespecialv2",
    "windowtitlev2", "moveworkspace", "moveworkspacev2", "pin", "togglegroup", "minimized",
}
RESTART_EVENTS = {"monitoradded", "monitoraddedv2", "monitorremoved", "monitorremovedv2"}
EVENT_DELAY_MS = 30
SETTLE_DELAY_MS = 320
POLL_INTERVAL_MS = 400
INSET = 5
CORNER = 22


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))


def load_colors():
    try:
        with open(COLORS_FILE, encoding="utf-8") as colors_file:
            loaded = json.load(colors_file)
    except (OSError, ValueError):
        loaded = {}
    colors = {**FALLBACK_COLORS, **{key: value for key, value in loaded.items() if isinstance(value, str)}}
    rgb = {"style": loaded.get("style") if isinstance(loaded.get("style"), str) else "ornate"}
    for key, value in colors.items():
        if key == "style":
            continue
        try:
            rgb[key] = hex_to_rgb(value)
        except ValueError:
            rgb[key] = hex_to_rgb(FALLBACK_COLORS.get(key, "#ffffff"))
    return rgb


def colors_modified():
    try:
        return os.stat(COLORS_FILE).st_mtime_ns
    except OSError:
        return None


def hyprland_socket(name):
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    return os.path.join(RUNTIME_DIR, "hypr", signature, name)


def hyprland_request(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1.0)
        connection.connect(hyprland_socket(".socket.sock"))
        connection.sendall(command.encode())
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks) or b"null")


def stacking_order(windows):
    tiled = [window for window in windows if not window["floating"] and not window["fullscreen"]]
    floating = sorted((window for window in windows if window["floating"] and not window["fullscreen"]),
                      key=lambda window: -window["focusHistoryID"])
    fullscreen = [window for window in windows if window["fullscreen"]]
    return tiled + floating + fullscreen


def diamond(cr, x, y, radius):
    cr.move_to(x, y - radius)
    cr.line_to(x + radius, y)
    cr.line_to(x, y + radius)
    cr.line_to(x - radius, y)
    cr.close_path()
    cr.fill()


def star(cr, x, y, radius):
    for step in range(10):
        angle = -math.pi / 2 + step * math.pi / 5
        length = radius if step % 2 == 0 else radius * 0.42
        point = (x + math.cos(angle) * length, y + math.sin(angle) * length)
        if step == 0:
            cr.move_to(*point)
        else:
            cr.line_to(*point)
    cr.close_path()
    cr.fill()


def ornate_corner(cr, size):
    cr.move_to(0, size * 1.7)
    cr.line_to(0, size * 0.5)
    cr.curve_to(0, size * 0.2, size * 0.2, 0, size * 0.5, 0)
    cr.line_to(size * 1.7, 0)
    cr.stroke()
    cr.move_to(size * 0.42, size * 1.25)
    cr.curve_to(size * 0.42, size * 0.62, size * 0.62, size * 0.42, size * 1.25, size * 0.42)
    cr.stroke()
    cr.arc(size * 1.25, size * 0.56, size * 0.14, -math.pi / 2, math.pi)
    cr.stroke()
    cr.arc(size * 0.56, size * 1.25, size * 0.14, math.pi, math.pi * 2.5)
    cr.stroke()
    cr.arc(size * 0.62, size * 0.62, size * 0.11, 0, 2 * math.pi)
    cr.fill()
    diamond(cr, size * 1.7, 0, size * 0.12)
    diamond(cr, 0, size * 1.7, size * 0.12)


def neon_corner(cr, size):
    for offset in (0, size * 0.28):
        cr.move_to(offset, size * 1.6)
        cr.line_to(offset, offset)
        cr.line_to(size * 1.6, offset)
        cr.stroke()
    diamond(cr, size * 0.28, size * 0.28, size * 0.12)


def gothic_corner(cr, size):
    cr.move_to(0, size * 1.8)
    cr.line_to(0, 0)
    cr.line_to(size * 1.8, 0)
    cr.stroke()
    cr.move_to(size * 0.15, size * 0.15)
    cr.line_to(size * 0.95, size * 0.95)
    cr.stroke()
    cr.move_to(size * 0.95, size * 0.55)
    cr.line_to(size * 1.15, size * 0.95)
    cr.line_to(size * 0.95, size * 1.35)
    cr.line_to(size * 0.75, size * 0.95)
    cr.close_path()
    cr.fill()
    cr.move_to(size * 0.55, size * 0.95)
    cr.line_to(size * 1.35, size * 0.95)
    cr.stroke()
    for x, y in ((size * 1.8, 0), (0, size * 1.8)):
        cr.move_to(x, y)
        cr.line_to(x + (size * 0.3 if y == 0 else 0), y + (size * 0.3 if x == 0 else 0))
        cr.stroke()


def frost_corner(cr, size):
    cr.move_to(0, size * 1.5)
    cr.line_to(0, 0)
    cr.line_to(size * 1.5, 0)
    cr.stroke()
    center = size * 0.7
    for step in range(6):
        angle = step * math.pi / 3
        dx, dy = math.cos(angle), math.sin(angle)
        cr.move_to(center, center)
        cr.line_to(center + dx * size * 0.5, center + dy * size * 0.5)
        tick_x, tick_y = center + dx * size * 0.32, center + dy * size * 0.32
        for side in (-1, 1):
            branch = angle + side * math.pi / 4
            cr.move_to(tick_x, tick_y)
            cr.line_to(tick_x + math.cos(branch) * size * 0.14, tick_y + math.sin(branch) * size * 0.14)
    cr.stroke()


def hud_corner(cr, size):
    cr.save()
    cr.set_line_width(cr.get_line_width() * 2.2)
    cr.move_to(0, size * 1.3)
    cr.line_to(0, 0)
    cr.line_to(size * 1.3, 0)
    cr.stroke()
    cr.restore()
    for step in range(3):
        position = size * (1.6 + step * 0.35)
        cr.move_to(position, size * 0.25)
        cr.line_to(position, size * 0.45)
        cr.move_to(size * 0.25, position)
        cr.line_to(size * 0.45, position)
    cr.stroke()
    cr.rectangle(size * 0.3, size * 0.3, size * 0.22, size * 0.22)
    cr.fill()


def vine_corner(cr, size):
    cr.move_to(0, size * 1.8)
    cr.curve_to(0, size * 0.6, size * 0.6, 0, size * 1.8, 0)
    cr.stroke()
    for t, side in ((0.25, 1), (0.5, -1), (0.75, 1)):
        x = size * 1.8 * t * t
        y = size * 1.8 * (1 - t) * (1 - t)
        cr.save()
        cr.translate(x + side * size * 0.12, y + side * size * 0.12)
        cr.rotate(-math.pi / 4)
        cr.scale(size * 0.22, size * 0.1)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        cr.fill()
    cr.arc(size * 0.42, size * 0.42, size * 0.1, 0, 2 * math.pi)
    cr.fill()


def constellation_corner(cr, size):
    points = ((size * 0.2, size * 0.2), (size * 1.1, size * 0.45), (size * 0.5, size * 1.0), (size * 1.7, size * 0.15), (size * 0.15, size * 1.7))
    cr.save()
    cr.set_line_width(cr.get_line_width() * 0.6)
    cr.move_to(*points[3])
    cr.line_to(*points[1])
    cr.line_to(*points[0])
    cr.line_to(*points[2])
    cr.line_to(*points[4])
    cr.stroke()
    cr.restore()
    for index, (x, y) in enumerate(points):
        star(cr, x, y, size * (0.22 if index == 0 else 0.13))


def celtic_corner(cr, size):
    cr.move_to(0, size * 1.8)
    cr.line_to(0, 0)
    cr.line_to(size * 1.8, 0)
    cr.stroke()
    for x, y in ((size * 0.55, size * 0.85), (size * 0.85, size * 0.55)):
        cr.arc(x, y, size * 0.32, 0, 2 * math.pi)
        cr.stroke()
    cr.rectangle(size * 0.45, size * 0.45, size * 0.5, size * 0.5)
    cr.stroke()


def flame_corner(cr, size):
    cr.move_to(0, size * 1.6)
    cr.line_to(0, 0)
    cr.line_to(size * 1.6, 0)
    cr.stroke()
    for scale, angle in ((1.0, 0.0), (0.7, 0.5), (0.7, -0.5)):
        cr.save()
        cr.translate(size * 0.6, size * 0.6)
        cr.rotate(math.pi / 4 + angle)
        cr.scale(scale, scale)
        cr.move_to(0, -size * 0.55)
        cr.curve_to(size * 0.28, -size * 0.2, size * 0.22, size * 0.15, 0, size * 0.2)
        cr.curve_to(-size * 0.22, size * 0.15, -size * 0.28, -size * 0.2, 0, -size * 0.55)
        cr.restore()
        cr.fill()
    for x, y in ((size * 1.35, size * 0.35), (size * 0.35, size * 1.35), (size * 1.05, size * 0.95)):
        cr.arc(x, y, size * 0.06, 0, 2 * math.pi)
        cr.fill()


def deco_corner(cr, size):
    for step in range(3):
        offset = step * size * 0.22
        cr.move_to(offset, size * 1.7)
        cr.line_to(offset, offset)
        cr.line_to(size * 1.7, offset)
    cr.stroke()
    for step in range(5):
        angle = step * math.pi / 8
        cr.move_to(size * 0.66, size * 0.66)
        cr.line_to(size * 0.66 + math.cos(angle) * size * 0.6, size * 0.66 + math.sin(angle) * size * 0.6)
    cr.stroke()


def synth_corner(cr, size):
    cr.move_to(0, size * 1.8)
    cr.line_to(0, 0)
    cr.line_to(size * 1.8, 0)
    cr.stroke()
    for radius in (0.45, 0.75, 1.05):
        cr.arc(0, 0, size * radius, 0, math.pi / 2)
        cr.stroke()
    cr.arc(0, 0, size * 0.3, 0, math.pi / 2)
    cr.line_to(0, 0)
    cr.close_path()
    cr.fill()


def retro_corner(cr, size):
    radius = size * 0.7
    for offset in (0, size * 0.25):
        cr.move_to(offset, size * 1.7)
        cr.line_to(offset, offset + radius)
        cr.arc(offset + radius, offset + radius, radius, math.pi, 1.5 * math.pi)
        cr.line_to(size * 1.7, offset)
        cr.stroke()


def ribbon_corner(cr, size):
    cr.move_to(0, size * 1.6)
    cr.line_to(0, 0)
    cr.line_to(size * 1.6, 0)
    cr.stroke()
    x, y, heart = size * 0.62, size * 0.62, size * 0.32
    cr.save()
    if cr.get_matrix().yy < 0:
        cr.translate(x, y)
        cr.scale(1, -1)
        cr.translate(-x, -y)
    cr.move_to(x, y + heart * 0.9)
    cr.curve_to(x - heart * 1.3, y - heart * 0.1, x - heart * 0.5, y - heart * 1.0, x, y - heart * 0.35)
    cr.curve_to(x + heart * 0.5, y - heart * 1.0, x + heart * 1.3, y - heart * 0.1, x, y + heart * 0.9)
    cr.fill()
    cr.restore()
    for step in range(3):
        cr.arc(size * (1.05 + step * 0.25), size * 0.18, size * 0.07, 0, 2 * math.pi)
        cr.fill()
        cr.arc(size * 0.18, size * (1.05 + step * 0.25), size * 0.07, 0, 2 * math.pi)
        cr.fill()


STYLES = {
    "ornate": (ornate_corner, "double"),
    "neon": (neon_corner, "glow"),
    "gothic": (gothic_corner, "double"),
    "frost": (frost_corner, "dashed"),
    "hud": (hud_corner, "dashed"),
    "vine": (vine_corner, "single"),
    "constellation": (constellation_corner, "dotted"),
    "celtic": (celtic_corner, "double"),
    "flame": (flame_corner, "single"),
    "deco": (deco_corner, "double"),
    "synth": (synth_corner, "glow"),
    "retro": (retro_corner, "offset"),
    "ribbon": (ribbon_corner, "dotted"),
}


class FrameOverlay:
    def __init__(self, gdk_monitor, colors):
        self.gdk_monitor = gdk_monitor
        self.colors = colors
        self.monitor = None
        self.windows = []
        self.active_address = None
        self.state = None
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self.window, "kewl-window-frame")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_monitor(self.window, gdk_monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.on_draw)
        self.window.connect("realize", self.on_realize)
        self.window.show_all()

    def on_realize(self, window):
        window.input_shape_combine_region(cairo.Region())

    def matches(self, monitor):
        geometry = self.gdk_monitor.get_geometry()
        scale = monitor.get("scale") or 1
        return (geometry.x, geometry.y) == (monitor["x"], monitor["y"]) and \
            abs(geometry.width - monitor["width"] / scale) < 2 and abs(geometry.height - monitor["height"] / scale) < 2

    def update(self, monitor, windows, active_address):
        visible = {monitor["activeWorkspace"]["id"], (monitor.get("specialWorkspace") or {}).get("id")}
        mine = [
            window for window in windows
            if window.get("mapped", True) and not window.get("hidden") and window["workspace"]["id"] in visible
        ]
        mine.sort(key=lambda window: window["workspace"]["id"] < 0)
        ordered = []
        for workspace_id in dict.fromkeys(window["workspace"]["id"] for window in mine):
            ordered.extend(stacking_order([window for window in mine if window["workspace"]["id"] == workspace_id]))
        snapshot = [
            (window["address"], tuple(window["at"]), tuple(window["size"]), window["class"], window["title"],
             window["workspace"]["id"])
            for window in ordered
        ]
        state = (monitor["x"], monitor["y"], snapshot, active_address)
        if state == self.state:
            return
        self.state = state
        self.monitor = monitor
        self.windows = snapshot
        self.active_address = active_address
        self.window.queue_draw()

    def on_draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        if not self.monitor:
            return False
        origin_x, origin_y = self.monitor["x"], self.monitor["y"]
        for address, at, size, window_class, title, workspace_id in self.windows:
            x, y = at[0] - origin_x, at[1] - origin_y
            width, height = size
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.rectangle(x, y, width, height)
            cr.fill()
            if (window_class or "").lower() not in TERMINAL_CLASSES or width < 6 * CORNER or height < 5 * CORNER:
                continue
            cr.set_operator(cairo.OPERATOR_OVER)
            self.draw_frame(cr, x, y, width, height, address == self.active_address)
        return False

    def draw_frame(self, cr, x, y, width, height, focused):
        accent, primary = self.colors["accent"], self.colors["primary"]
        corner, edge = STYLES.get(self.colors["style"], STYLES["ornate"])
        alpha = 1.0 if focused else 0.55
        left, top = x + INSET, y + INSET
        right, bottom = x + width - INSET, y + height - INSET
        span = CORNER * 1.9
        cr.save()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        edges = (((left + span, top), (right - span, top)), ((left + span, bottom), (right - span, bottom)),
                 ((left, top + span), (left, bottom - span)), ((right, top + span), (right, bottom - span)))
        if edge == "glow":
            cr.set_line_width(4.0)
            cr.set_source_rgba(*accent, 0.18 * alpha)
            self.stroke_edges(cr, edges)
        if edge == "dashed":
            cr.set_dash([10.0, 6.0])
        elif edge == "dotted":
            cr.set_dash([0.1, 7.0])
            cr.set_line_width(2.4)
        cr.set_line_width(cr.get_line_width() if edge == "dotted" else 1.0)
        cr.set_source_rgba(*accent, 0.75 * alpha)
        self.stroke_edges(cr, edges)
        cr.set_dash([])
        if edge in ("double", "offset"):
            inset = 3.5
            cr.set_line_width(1.0)
            cr.set_source_rgba(*primary, (0.8 if edge == "offset" else 0.45) * alpha)
            cr.rectangle(left + inset, top + inset, right - left - 2 * inset, bottom - top - 2 * inset)
            cr.stroke()
        cr.set_line_width(1.6)
        cr.set_source_rgba(*accent, alpha)
        for corner_x, corner_y, scale_x, scale_y in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
            cr.save()
            cr.translate(corner_x, corner_y)
            cr.scale(scale_x, scale_y)
            corner(cr, CORNER)
            cr.restore()
        cr.restore()

    def stroke_edges(self, cr, edges):
        for start, end in edges:
            cr.move_to(*start)
            cr.line_to(*end)
        cr.stroke()


class WindowFrames:
    def __init__(self):
        self.colors = load_colors()
        self.colors_modified = colors_modified()
        display = Gdk.Display.get_default()
        self.overlays = [FrameOverlay(display.get_monitor(index), self.colors) for index in range(display.get_n_monitors())]
        self.pending = None
        self.buffer = b""
        self.events = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.events.connect(hyprland_socket(".socket2.sock"))
        self.events.setblocking(False)
        GLib.io_add_watch(self.events.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_events)
        GLib.timeout_add(POLL_INTERVAL_MS, self.poll)
        self.refresh()

    def on_events(self, _fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            Gtk.main_quit()
            return False
        try:
            chunk = self.events.recv(65536)
        except BlockingIOError:
            return True
        except OSError:
            Gtk.main_quit()
            return False
        if not chunk:
            Gtk.main_quit()
            return False
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b"\n")
        names = {line.split(b">>", 1)[0].decode(errors="replace") for line in lines}
        if names & RESTART_EVENTS:
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])
        if names & REFRESH_EVENTS:
            self.schedule(EVENT_DELAY_MS)
            self.schedule_settle()
        return True

    def schedule(self, delay):
        if self.pending is None:
            self.pending = GLib.timeout_add(delay, self.run_pending)

    def schedule_settle(self):
        GLib.timeout_add(SETTLE_DELAY_MS, self.run_once)

    def run_pending(self):
        self.pending = None
        self.refresh()
        return False

    def run_once(self):
        self.refresh()
        return False

    def poll(self):
        modified = colors_modified()
        if modified != self.colors_modified:
            self.colors_modified = modified
            colors = load_colors()
            for overlay in self.overlays:
                overlay.colors = colors
                overlay.state = None
        self.refresh()
        return True

    def refresh(self):
        try:
            monitors = hyprland_request("j/monitors") or []
            windows = hyprland_request("j/clients") or []
            active = hyprland_request("j/activewindow") or {}
        except (OSError, ValueError):
            return
        for overlay in self.overlays:
            monitor = next((monitor for monitor in monitors if overlay.matches(monitor)), None)
            if monitor:
                overlay.update(monitor, windows, active.get("address"))


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return 1
    WindowFrames()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
