import os
import subprocess

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_foreign("cairo")
from gi.repository import Gdk, Gtk

SHUTTER_SOUND = os.path.expanduser("~/.config/hypr/sounds/snip.mp3")

MODES = [
    ("rectangle", "Rectangular snip", "draw-rectangle"),
    ("freeform", "Freeform snip", "draw-freehand"),
    ("window", "Window snip", "window"),
    ("fullscreen", "Fullscreen snip", "view-fullscreen"),
]


class SnipOverlay(Gtk.Window):
    def __init__(self, screenshot, monitor, windows, on_done):
        super().__init__(title="Snipping overlay")
        self.get_style_context().add_class("snip-overlay")
        self.screenshot = screenshot
        self.windows = windows
        self.on_done = on_done
        self.factor = screenshot.get_width() / (monitor["width"] / monitor["scale"])
        self.mode = "rectangle"
        self.start = None
        self.current = None
        self.points = []
        self.hover = None
        self.finished = False
        self.mode_buttons = {}

        layers = Gtk.Overlay()
        self.add(layers)

        self.area = Gtk.DrawingArea()
        self.area.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("button-release-event", self.on_release)
        layers.add(self.area)

        toolbar = Gtk.Box(spacing=4)
        toolbar.get_style_context().add_class("snip-toolbar")
        toolbar.set_halign(Gtk.Align.CENTER)
        toolbar.set_valign(Gtk.Align.START)
        toolbar.set_margin_top(16)
        for mode, tooltip, icon in MODES:
            button = Gtk.ToggleButton()
            button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
            button.set_tooltip_text(tooltip)
            button.connect("toggled", self.on_mode_toggled, mode)
            self.mode_buttons[mode] = button
            toolbar.pack_start(button, False, False, 0)
        toolbar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        close = Gtk.Button()
        close.set_image(Gtk.Image.new_from_icon_name("window-close", Gtk.IconSize.LARGE_TOOLBAR))
        close.set_tooltip_text("Close")
        close.connect("clicked", lambda _: self.finish(None))
        toolbar.pack_start(close, False, False, 0)
        layers.add_overlay(toolbar)

        self.mode_buttons["rectangle"].set_active(True)
        self.connect("key-press-event", self.on_key)
        self.fullscreen()
        self.show_all()

    def on_mode_toggled(self, button, mode):
        if not button.get_active():
            if self.mode == mode:
                button.set_active(True)
            return
        if mode == "fullscreen":
            self.finish(self.screenshot.copy())
            return
        self.mode = mode
        self.start = self.current = self.hover = None
        self.points = []
        for other, other_button in self.mode_buttons.items():
            if other != mode and other_button.get_active():
                other_button.set_active(False)
        self.area.queue_draw()

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.finish(None)
            return True
        return False

    def paint_screenshot(self, cr):
        cr.save()
        cr.scale(1 / self.factor, 1 / self.factor)
        Gdk.cairo_set_source_pixbuf(cr, self.screenshot, 0, 0)
        cr.paint()
        cr.restore()

    def selection_path(self, cr):
        if self.mode == "rectangle" and self.start and self.current:
            x, y, w, h = self.rect_from_drag()
            cr.rectangle(x, y, w, h)
            return True
        if self.mode == "freeform" and len(self.points) > 1:
            cr.move_to(*self.points[0])
            for point in self.points[1:]:
                cr.line_to(*point)
            cr.close_path()
            return True
        if self.mode == "window" and self.hover:
            cr.rectangle(*self.hover)
            return True
        return False

    def on_draw(self, _widget, cr):
        self.paint_screenshot(cr)
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.paint()
        cr.save()
        if self.selection_path(cr):
            path = cr.copy_path()
            cr.clip()
            self.paint_screenshot(cr)
            cr.restore()
            cr.new_path()
            cr.append_path(path)
            cr.set_source_rgba(0.9, 0.93, 0.95, 0.9)
            cr.set_line_width(1.5)
            cr.stroke()
        else:
            cr.restore()
        return False

    def rect_from_drag(self):
        (x1, y1), (x2, y2) = self.start, self.current
        return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)

    def window_at(self, x, y):
        for wx, wy, ww, wh in self.windows:
            if wx <= x <= wx + ww and wy <= y <= wy + wh:
                return (wx, wy, ww, wh)
        return None

    def on_press(self, _widget, event):
        if event.button != 1:
            return False
        if self.mode == "window":
            if self.hover:
                self.finish(self.crop_rect(*self.hover))
            return True
        self.start = self.current = (event.x, event.y)
        self.points = [(event.x, event.y)]
        return True

    def on_motion(self, _widget, event):
        if self.mode == "window":
            self.hover = self.window_at(event.x, event.y)
        elif self.start:
            self.current = (event.x, event.y)
            if self.mode == "freeform":
                self.points.append((event.x, event.y))
        self.area.queue_draw()
        return True

    def on_release(self, _widget, event):
        if event.button != 1 or not self.start:
            return False
        if self.mode == "rectangle":
            x, y, w, h = self.rect_from_drag()
            if w > 2 and h > 2:
                self.finish(self.crop_rect(x, y, w, h))
                return True
        elif self.mode == "freeform" and len(self.points) > 2:
            self.finish(self.crop_freeform(self.points))
            return True
        self.start = self.current = None
        self.points = []
        self.area.queue_draw()
        return True

    def to_pixels(self, x, y, w, h):
        image_w, image_h = self.screenshot.get_width(), self.screenshot.get_height()
        px = max(0, min(image_w - 1, int(round(x * self.factor))))
        py = max(0, min(image_h - 1, int(round(y * self.factor))))
        pw = max(1, min(image_w - px, int(round(w * self.factor))))
        ph = max(1, min(image_h - py, int(round(h * self.factor))))
        return px, py, pw, ph

    def crop_rect(self, x, y, w, h):
        px, py, pw, ph = self.to_pixels(x, y, w, h)
        return self.screenshot.new_subpixbuf(px, py, pw, ph).copy()

    def crop_freeform(self, points):
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        px, py, pw, ph = self.to_pixels(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
        cr = cairo.Context(surface)
        cr.move_to(points[0][0] * self.factor - px, points[0][1] * self.factor - py)
        for x, y in points[1:]:
            cr.line_to(x * self.factor - px, y * self.factor - py)
        cr.close_path()
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, self.screenshot, -px, -py)
        cr.paint()
        return Gdk.pixbuf_get_from_surface(surface, 0, 0, pw, ph)

    def finish(self, pixbuf):
        if self.finished:
            return
        self.finished = True
        if pixbuf:
            subprocess.Popen(["pw-play", SHUTTER_SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.destroy()
        self.on_done(pixbuf)
