#!/usr/bin/env python3
import math
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell

import cairo

SWEEP_SECONDS = 0.6
EDGE_WIDTH = 260.0
GLOW_WIDTH = 90.0
WAIT_FOR_GO_SECONDS = 4.0


def hex_to_rgb(color):
    color = color.lstrip("#")
    try:
        return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return (1.0, 1.0, 1.0)


def ease_in_out(progress):
    return 0.5 - 0.5 * math.cos(math.pi * progress)


def capture_screen():
    try:
        data = subprocess.run(["grim", "-t", "ppm", "-"], capture_output=True, timeout=2).stdout
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except (OSError, subprocess.TimeoutExpired, GLib.Error):
        return None


def snapshot_surface(screen, monitor):
    geometry = monitor.get_geometry()
    scale = monitor.get_scale_factor()
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, geometry.width * scale, geometry.height * scale)
    surface.set_device_scale(scale, scale)
    cr = cairo.Context(surface)
    cr.scale(1 / scale, 1 / scale)
    Gdk.cairo_set_source_pixbuf(cr, screen, -geometry.x * scale, -geometry.y * scale)
    cr.paint()
    surface.flush()
    return surface


class Sweep:
    def __init__(self, monitor, snapshot, accent):
        geometry = monitor.get_geometry()
        self.width, self.height = geometry.width, geometry.height
        self.snapshot = snapshot
        self.accent = accent
        self.started = None
        self.running = False
        self.done = False
        self.shown = False
        self.drawn_front = None
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self.window, "kewl-theme-transition")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_monitor(self.window, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.on_draw)
        self.window.connect("realize", lambda window: window.input_shape_combine_region(cairo.Region()))
        self.window.show_all()

    def start(self):
        self.running = True
        self.window.add_tick_callback(self.on_tick)

    def front(self):
        return -EDGE_WIDTH + self.progress() * (self.width + EDGE_WIDTH + GLOW_WIDTH)

    def on_tick(self, widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        if self.started is None:
            self.started = now
        current = self.front()
        previous = current if self.drawn_front is None else self.drawn_front
        left = int(min(previous, current) - EDGE_WIDTH - GLOW_WIDTH) - 2
        right = int(max(previous, current) + GLOW_WIDTH) + 2
        widget.queue_draw_area(max(0, left), 0, max(1, min(self.width, right) - max(0, left)), self.height)
        if now - self.started >= SWEEP_SECONDS:
            widget.queue_draw()
            self.done = True
            return False
        return True

    def progress(self):
        if not self.running or self.started is None:
            return 0.0
        clock = self.window.get_frame_clock()
        now = clock.get_frame_time() / 1_000_000 if clock else self.started
        return ease_in_out(min(1.0, max(0.0, (now - self.started) / SWEEP_SECONDS)))

    def on_draw(self, _widget, cr):
        self.shown = True
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if self.running and self.progress() >= 1.0:
            return False
        front = self.front() if self.running else -EDGE_WIDTH
        self.drawn_front = front
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.rectangle(max(0.0, front), 0, self.width, self.height)
        cr.set_source_surface(self.snapshot, 0, 0)
        cr.fill()
        if not self.running:
            return False
        band_left = front - EDGE_WIDTH
        mask = cairo.LinearGradient(band_left, 0, front, 0)
        mask.add_color_stop_rgba(0, 0, 0, 0, 0)
        mask.add_color_stop_rgba(1, 0, 0, 0, 1)
        cr.save()
        cr.rectangle(band_left, 0, EDGE_WIDTH, self.height)
        cr.clip()
        cr.set_source_surface(self.snapshot, 0, 0)
        cr.mask(mask)
        cr.restore()
        strength = math.sin(math.pi * self.progress())
        glow = cairo.LinearGradient(front - GLOW_WIDTH, 0, front + GLOW_WIDTH * 0.35, 0)
        glow.add_color_stop_rgba(0, *self.accent, 0)
        glow.add_color_stop_rgba(0.72, *self.accent, 0.45 * strength)
        glow.add_color_stop_rgba(0.8, 1, 1, 1, 0.55 * strength)
        glow.add_color_stop_rgba(1, *self.accent, 0)
        cr.rectangle(front - GLOW_WIDTH, 0, GLOW_WIDTH * 1.35, self.height)
        cr.set_source(glow)
        cr.fill()
        return False


def main(arguments):
    accent = hex_to_rgb(arguments[0]) if arguments else (1.0, 1.0, 1.0)
    display = Gdk.Display.get_default()
    screen = capture_screen()
    if display is None or screen is None:
        print("ready", flush=True)
        return 1
    sweeps = [
        Sweep(display.get_monitor(index), snapshot_surface(screen, display.get_monitor(index)), accent)
        for index in range(display.get_n_monitors())
    ]
    state = {"announced": False}

    def announce():
        if not state["announced"] and all(sweep.shown for sweep in sweeps):
            state["announced"] = True
            try:
                print("ready", flush=True)
            except BrokenPipeError:
                pass
        if all(sweep.done for sweep in sweeps):
            Gtk.main_quit()
            return False
        return True

    def go(*_arguments):
        for sweep in sweeps:
            if not sweep.running:
                sweep.start()
        return False

    GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, go)
    GLib.timeout_add(16, announce)
    GLib.timeout_add(int(WAIT_FOR_GO_SECONDS * 1000), go)
    GLib.timeout_add(int((WAIT_FOR_GO_SECONDS + SWEEP_SECONDS + 1) * 1000), lambda: Gtk.main_quit() or False)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
