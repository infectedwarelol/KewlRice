#!/usr/bin/env python3
import math
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/hypr/window-switcher"))

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_foreign("cairo")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, PangoCairo

from desktop_icons import icon_names_by_window_class
from task_layout import TITLE_HEIGHT, layout
from window_thumbnails import capture_all, focused_monitor, list_windows, switch_to

PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "task-view.pid")
SOUND = os.path.expanduser("~/.config/hypr/sounds/overview.mp3")
MARGIN = 60
RADIUS = 10
ICON_SIZE = 20


def play_sound():
    subprocess.Popen(["pw-play", SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def already_running():
    try:
        pid = int(open(PID_FILE).read().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class TaskView(Gtk.Window):
    def __init__(self, windows, thumbnails, monitor):
        super().__init__(title="Task View")
        self.windows = windows
        self.hover = None
        self.closing = False
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "task-view")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        width = monitor["width"] / monitor["scale"]
        height = monitor["height"] / monitor["scale"]
        sizes = [
            (t.get_width(), t.get_height()) if t else (max(1, w["size"][0]), max(1, w["size"][1]))
            for w, t in zip(windows, thumbnails)
        ]
        self.rects = layout(sizes, MARGIN, MARGIN, width - 2 * MARGIN, height - 2 * MARGIN)
        self.images = [
            t.scale_simple(max(1, int(r[2])), max(1, int(r[3])), GdkPixbuf.InterpType.HYPER) if t else None
            for t, r in zip(thumbnails, self.rects)
        ]
        icons = icon_names_by_window_class()
        theme = Gtk.IconTheme.get_default()
        self.icons = []
        for w in windows:
            name = icons.get(w["class"].lower(), w["class"].lower())
            try:
                self.icons.append(theme.load_icon(name, ICON_SIZE, Gtk.IconLookupFlags.FORCE_SIZE))
            except Exception:
                self.icons.append(None)

        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("button-press-event", self.on_click)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.show_all()

    def index_at(self, x, y):
        for index, (rx, ry, rw, rh) in enumerate(self.rects):
            if rx <= x <= rx + rw and ry - TITLE_HEIGHT <= y <= ry + rh:
                return index
        return None

    def on_draw(self, _widget, cr):
        cr.set_source_rgba(17 / 255, 20 / 255, 30 / 255, 0.6)
        cr.paint()
        for index, (window, image, icon, rect) in enumerate(zip(self.windows, self.images, self.icons, self.rects)):
            x, y, w, h = rect
            hovered = index == self.hover
            for spread in range(12, 0, -2):
                rounded_rect(cr, x - spread, y - spread + 4, w + 2 * spread, h + 2 * spread, RADIUS + spread)
                cr.set_source_rgba(0, 0, 0, 0.03)
                cr.fill()
            cr.save()
            rounded_rect(cr, x, y, w, h, RADIUS)
            cr.clip()
            if image:
                Gdk.cairo_set_source_pixbuf(cr, image, x, y)
                cr.paint()
            else:
                cr.set_source_rgba(43 / 255, 58 / 255, 74 / 255, 0.9)
                cr.paint()
            if hovered:
                cr.set_source_rgba(1, 1, 1, 0.08)
                cr.paint()
            cr.restore()
            rounded_rect(cr, x, y, w, h, RADIUS)
            cr.set_source_rgba(230 / 255, 237 / 255, 243 / 255, 0.9 if hovered else 0.12)
            cr.set_line_width(2.5 if hovered else 1)
            cr.stroke()

            text_x = x
            if icon:
                Gdk.cairo_set_source_pixbuf(cr, icon, x, y - TITLE_HEIGHT + (TITLE_HEIGHT - ICON_SIZE) / 2 - 2)
                cr.paint()
                text_x = x + ICON_SIZE + 8
            text = PangoCairo.create_layout(cr)
            text.set_font_description(Pango.FontDescription("Noto Sans 10"))
            text.set_text(window["title"] or window["class"], -1)
            text.set_width(int(max(10, x + w - text_x) * Pango.SCALE))
            text.set_ellipsize(Pango.EllipsizeMode.END)
            text.set_single_paragraph_mode(True)
            _, logical = text.get_pixel_extents()
            cr.move_to(text_x, y - TITLE_HEIGHT + (TITLE_HEIGHT - logical.height) / 2 - 2)
            cr.set_source_rgba(230 / 255, 237 / 255, 243 / 255, 1.0 if hovered else 0.85)
            PangoCairo.show_layout(cr, text)
        return False

    def on_motion(self, _widget, event):
        index = self.index_at(event.x, event.y)
        if index != self.hover:
            self.hover = index
            self.area.queue_draw()
        return True

    def on_click(self, _widget, event):
        if event.button != 1:
            return False
        index = self.index_at(event.x, event.y)
        if index is None:
            self.close_view()
        else:
            self.pick(index)
        return True

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_view()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.pick(self.hover if self.hover is not None else 0)
            return True
        return False

    def pick(self, index):
        if self.closing:
            return
        self.closing = True
        window = self.windows[index]
        self.hide()
        play_sound()
        GLib.timeout_add(60, lambda: (switch_to(window), Gtk.main_quit(), False)[2])

    def close_view(self):
        if self.closing:
            return
        self.closing = True
        self.hide()
        play_sound()
        Gtk.main_quit()


def main():
    running = already_running()
    if running:
        os.kill(running, signal.SIGUSR1)
        return
    windows = list_windows()
    if not windows:
        return
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-icon-theme-name", "breeze-dark")
        thumbnails = capture_all(windows)
        play_sound()
        view = TaskView(windows, thumbnails, focused_monitor())
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: (view.close_view(), False)[1])
        Gtk.main()
    finally:
        try:
            if open(PID_FILE).read().strip() == str(os.getpid()):
                os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
