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
TAG_FONT = "JetBrainsMono Nerd Font"
TAG_HEIGHT = 18
TITLE_LIMIT = 32
CHECK_GLYPH = ""
WARNING_GLYPH = ""


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
    rgb = {}
    for key, value in colors.items():
        try:
            rgb[key] = hex_to_rgb(value)
        except ValueError:
            rgb[key] = hex_to_rgb(FALLBACK_COLORS.get(key, "#ffffff"))
    return rgb


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


def shorten(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def stacking_order(windows):
    tiled = [window for window in windows if not window["floating"] and not window["fullscreen"]]
    floating = sorted((window for window in windows if window["floating"] and not window["fullscreen"]),
                      key=lambda window: -window["focusHistoryID"])
    fullscreen = [window for window in windows if window["fullscreen"]]
    return tiled + floating + fullscreen


def flourish(cr, size):
    cr.move_to(0, size * 1.7)
    cr.line_to(0, size * 0.5)
    cr.curve_to(0, size * 0.2, size * 0.2, 0, size * 0.5, 0)
    cr.line_to(size * 1.7, 0)
    cr.stroke()
    cr.move_to(size * 0.42, size * 1.25)
    cr.curve_to(size * 0.42, size * 0.62, size * 0.62, size * 0.42, size * 1.25, size * 0.42)
    cr.stroke()
    cr.arc(size * 1.25, size * 0.42 + size * 0.14, size * 0.14, -math.pi / 2, math.pi)
    cr.stroke()
    cr.arc(size * 0.42 + size * 0.14, size * 1.25, size * 0.14, math.pi, math.pi * 2.5)
    cr.stroke()
    cr.arc(size * 0.62, size * 0.62, size * 0.11, 0, 2 * math.pi)
    cr.fill()
    cr.move_to(size * 1.7, -size * 0.12)
    cr.line_to(size * 1.82, 0)
    cr.line_to(size * 1.7, size * 0.12)
    cr.line_to(size * 1.58, 0)
    cr.close_path()
    cr.fill()
    cr.move_to(-size * 0.12, size * 1.7)
    cr.line_to(0, size * 1.82)
    cr.line_to(size * 0.12, size * 1.7)
    cr.line_to(0, size * 1.58)
    cr.close_path()
    cr.fill()


def rounded_rectangle(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


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
            self.draw_frame(cr, x, y, width, height, title, workspace_id, address == self.active_address)
        return False

    def draw_frame(self, cr, x, y, width, height, title, workspace_id, focused):
        accent, primary, background = self.colors["accent"], self.colors["primary"], self.colors["background"]
        alpha = 1.0 if focused else 0.55
        left, top = x + INSET, y + INSET
        right, bottom = x + width - INSET, y + height - INSET
        cr.save()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_width(1.0)
        cr.set_source_rgba(*accent, 0.75 * alpha)
        span = CORNER * 1.9
        for start, end in (((left + span, top), (right - span, top)), ((left + span, bottom), (right - span, bottom)),
                           ((left, top + span), (left, bottom - span)), ((right, top + span), (right, bottom - span))):
            cr.move_to(*start)
            cr.line_to(*end)
        cr.stroke()
        cr.set_source_rgba(*primary, 0.45 * alpha)
        cr.rectangle(left + 3.5, top + 3.5, right - left - 7, bottom - top - 7)
        cr.stroke()
        cr.set_line_width(1.6)
        cr.set_source_rgba(*accent, alpha)
        for corner_x, corner_y, scale_x, scale_y in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
            cr.save()
            cr.translate(corner_x, corner_y)
            cr.scale(scale_x, scale_y)
            flourish(cr, CORNER)
            cr.restore()
        middle = (left + right) / 2
        cr.set_source_rgba(*accent, alpha)
        for offset, radius in ((-14, 2.2), (0, 4.2), (14, 2.2)):
            cr.move_to(middle + offset, top - radius)
            cr.line_to(middle + offset + radius, top)
            cr.line_to(middle + offset, top + radius)
            cr.line_to(middle + offset - radius, top)
            cr.close_path()
            cr.fill()
        self.draw_tag(cr, f"{CHECK_GLYPH}  {shorten(title, TITLE_LIMIT) or 'system'}", right - span, bottom, "right", focused)
        self.draw_tag(cr, f"{WARNING_GLYPH}  ws {workspace_id}", left + span, bottom, "left", focused)
        cr.restore()

    def draw_tag(self, cr, text, anchor_x, center_y, align, focused):
        accent, background, foreground = self.colors["accent"], self.colors["background"], self.colors["foreground"]
        urgent = self.colors["urgent"]
        cr.select_font_face(TAG_FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.5)
        extents = cr.text_extents(text)
        width = extents.x_advance + 18
        x = anchor_x - width if align == "right" else anchor_x
        y = center_y - TAG_HEIGHT / 2
        rounded_rectangle(cr, x, y, width, TAG_HEIGHT, TAG_HEIGHT / 2)
        cr.set_source_rgba(*background, 0.92)
        cr.fill_preserve()
        cr.set_line_width(1.0)
        cr.set_source_rgba(*accent, 1.0 if focused else 0.55)
        cr.stroke()
        cr.move_to(x + 9 - extents.x_bearing, center_y + 3.8)
        if align == "left":
            cr.set_source_rgba(*urgent, 1.0 if focused else 0.6)
        else:
            cr.set_source_rgba(*foreground, 1.0 if focused else 0.6)
        cr.show_text(text)
        cr.new_path()


class WindowFrames:
    def __init__(self):
        self.colors = load_colors()
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
