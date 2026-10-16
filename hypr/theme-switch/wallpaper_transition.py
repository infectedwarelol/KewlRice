#!/usr/bin/env python3
import math
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell

import cairo

HOLD_SECONDS = 0.15
REVEAL_SECONDS = 0.95
ZOOM = 0.08
RING_WIDTH = 46.0
SAFETY_SECONDS = 4.0


def hex_to_rgb(color):
    color = color.lstrip("#")
    try:
        return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return (1.0, 1.0, 1.0)


def ease_in_out(progress):
    return 4 * progress ** 3 if progress < 0.5 else 1 - (-2 * progress + 2) ** 3 / 2


def cover_surface(path, width, height, scale):
    pixel_width, pixel_height = width * scale, height * scale
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, pixel_width, pixel_height)
    surface.set_device_scale(scale, scale)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0, 0, 0)
    cr.paint()
    try:
        info = GdkPixbuf.Pixbuf.get_file_info(path)
        source_width, source_height = info[1], info[2]
        ratio = max(pixel_width / source_width, pixel_height / source_height)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, math.ceil(source_width * ratio), math.ceil(source_height * ratio), True)
    except (GLib.Error, TypeError, ZeroDivisionError):
        return surface
    cr.scale(1 / scale, 1 / scale)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, (pixel_width - pixbuf.get_width()) / 2, (pixel_height - pixbuf.get_height()) / 2)
    cr.paint()
    surface.flush()
    return surface


class Transition:
    def __init__(self, monitor, old_path, new_path, accent):
        geometry = monitor.get_geometry()
        scale = monitor.get_scale_factor()
        self.width, self.height = geometry.width, geometry.height
        self.old = cover_surface(old_path, self.width, self.height, scale)
        self.new = cover_surface(new_path, self.width, self.height, scale)
        self.accent = accent
        self.started = None
        self.done = False
        self.shown = False
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_namespace(self.window, "kewl-wallpaper-transition")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_monitor(self.window, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.on_draw)
        self.window.connect("realize", lambda window: window.input_shape_combine_region(cairo.Region()))
        self.window.add_tick_callback(self.on_tick)
        self.window.show_all()

    def progress(self, now):
        if self.started is None:
            self.started = now
        elapsed = now - self.started - HOLD_SECONDS
        return min(1.0, max(0.0, elapsed / REVEAL_SECONDS))

    def on_tick(self, widget, frame_clock):
        progress = self.progress(frame_clock.get_frame_time() / 1_000_000)
        widget.queue_draw()
        if progress >= 1.0:
            self.done = True
            return False
        return True

    def on_draw(self, widget, cr):
        now = widget.get_frame_clock().get_frame_time() / 1_000_000 if widget.get_frame_clock() else 0.0
        self.shown = True
        eased = ease_in_out(self.progress(now))
        center_x, center_y = self.width / 2, self.height / 2
        radius = eased * math.hypot(center_x, center_y) * 1.05
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.old, 0, 0)
        cr.paint()
        if radius <= 0:
            return False
        cr.save()
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.clip()
        zoom = 1 + ZOOM * (1 - eased)
        cr.translate(center_x, center_y)
        cr.scale(zoom, zoom)
        cr.translate(-center_x, -center_y)
        cr.set_source_surface(self.new, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BILINEAR)
        cr.paint()
        cr.restore()
        if eased < 1.0:
            cr.set_operator(cairo.OPERATOR_OVER)
            fade = math.sin(math.pi * eased)
            ring = cairo.RadialGradient(center_x, center_y, max(0.0, radius - RING_WIDTH), center_x, center_y, radius + 4)
            ring.add_color_stop_rgba(0, *self.accent, 0)
            ring.add_color_stop_rgba(0.85, *self.accent, 0.55 * fade)
            ring.add_color_stop_rgba(1, 1, 1, 1, 0.8 * fade)
            cr.arc(center_x, center_y, radius + 4, 0, 2 * math.pi)
            cr.set_source(ring)
            cr.fill()
        return False


def main(arguments):
    if len(arguments) < 2:
        return 2
    old_path, new_path = arguments[0], arguments[1]
    accent = hex_to_rgb(arguments[2]) if len(arguments) > 2 else (1.0, 1.0, 1.0)
    display = Gdk.Display.get_default()
    if display is None:
        return 1
    transitions = [Transition(display.get_monitor(index), old_path, new_path, accent) for index in range(display.get_n_monitors())]
    announced = []

    def check():
        if not announced and all(transition.shown for transition in transitions):
            announced.append(True)
            try:
                print("ready", flush=True)
            except BrokenPipeError:
                pass
        if all(transition.done for transition in transitions):
            Gtk.main_quit()
            return False
        return True

    GLib.timeout_add(50, check)
    GLib.timeout_add(int(SAFETY_SECONDS * 1000), lambda: Gtk.main_quit() or False)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
