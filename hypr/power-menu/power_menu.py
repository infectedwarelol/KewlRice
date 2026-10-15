#!/usr/bin/env python3
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell


try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
    unix_signal_add = GLibUnix.signal_add
except (ValueError, ImportError):
    unix_signal_add = GLib.unix_signal_add

import cairo

HOME = Path.home()
THEME_SWITCH_DIR = Path(__file__).resolve().parent.parent / "theme-switch"
SOUNDS_DIR = HOME / ".config" / "hypr" / "sounds"
LOCK_SCRIPT = HOME / ".config" / "hypr" / "lock" / "lock.sh"
PID_FILE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "kewl-power-menu.pid"
LOGOUT_COMMAND = "command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'"
FALLBACK_COLORS = {"background": "#2c0809", "foreground": "#f3e6e4", "surface": "#460f11", "primary": "#800020", "accent": "#c06a73", "urgent": "#ffc857"}
ICON_THEMES = ("WhiteSur-dark", "WhiteSur")
ICON_PIXELS = 128
TILE_SIZE = 150
TILE_GAP = 34
FOCUS_GROWTH = 0.12
EASE_RATE = 16.0
FONT = "Noto Sans"
ACTIONS = (
    {"key": "lock", "label": "Lock", "icons": ("system-lock-screen", "changes-prevent"), "confirm": False},
    {"key": "logout", "label": "Log out", "icons": ("system-log-out", "application-exit"), "confirm": True},
    {"key": "reboot", "label": "Restart", "icons": ("system-reboot", "view-refresh"), "confirm": True},
    {"key": "shutdown", "label": "Shut down", "icons": ("system-shutdown", "system-shutdown-symbolic"), "confirm": True},
)
CONFIRM_TEXT = {"logout": "Press again to log out", "reboot": "Press again to restart", "shutdown": "Press again to shut down"}


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))


def load_colors():
    try:
        sys.path.insert(0, str(THEME_SWITCH_DIR))
        import theme_switch
        name = theme_switch.current_theme() or theme_switch.DEFAULT_THEME
        _, palette = theme_switch.load_palette(name)
        return {key: hex_to_rgb(palette.get(key, value)) for key, value in FALLBACK_COLORS.items()}
    except Exception:
        return {key: hex_to_rgb(value) for key, value in FALLBACK_COLORS.items()}


def play(sound):
    path = SOUNDS_DIR / sound
    if path.is_file():
        subprocess.Popen(["pw-play", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def is_power_menu(pid):
    try:
        return Path(__file__).name.encode() in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def close_running_menu():
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid() or not is_power_menu(pid):
        PID_FILE.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return False
    except PermissionError:
        return False
    return True


def rounded_rectangle(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


class PowerMenu:
    def __init__(self):
        self.colors = load_colors()
        self.selected = 0
        self.focus = [1.0 if index == 0 else 0.0 for index in range(len(ACTIONS))]
        self.armed = None
        self.choice = None
        self.opacity = 0.0
        self.last_frame_time = None
        self.hit_boxes = []
        self.icon_themes = []
        for theme_name in ICON_THEMES:
            theme = Gtk.IconTheme()
            theme.set_custom_theme(theme_name)
            self.icon_themes.append(theme)
        self.icons = [self.load_icon(action["icons"]) for action in ACTIONS]
        self.build_window()

    def load_icon(self, names):
        for theme in self.icon_themes:
            for name in names:
                try:
                    pixbuf = theme.load_icon(name, ICON_PIXELS, Gtk.IconLookupFlags.FORCE_SIZE)
                except GLib.Error:
                    continue
                if pixbuf:
                    surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, 1, None)
                    return surface
        return None

    def build_window(self):
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self.window, "kewl-power")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("motion-notify-event", self.on_motion)
        self.window.connect("key-press-event", self.on_key)
        self.window.add(self.area)

    def select(self, index):
        index %= len(ACTIONS)
        if index != self.selected:
            self.selected = index
            self.armed = None

    def activate(self, index):
        action = ACTIONS[index]
        if action["confirm"] and self.armed != index:
            self.selected = index
            self.armed = index
            return
        self.choice = action["key"]
        Gtk.main_quit()

    def cancel(self):
        self.choice = None
        Gtk.main_quit()

    def on_key(self, _widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.cancel()
        elif key in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_h, Gdk.KEY_k):
            self.select(self.selected - 1)
        elif key in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Tab, Gdk.KEY_l, Gdk.KEY_j):
            self.select(self.selected + 1)
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.activate(self.selected)
        elif Gdk.KEY_1 <= key <= Gdk.KEY_4:
            self.activate(key - Gdk.KEY_1)
        return True

    def hit_test(self, x, y):
        for index, (left, top, size) in self.hit_boxes:
            if left <= x <= left + size and top <= y <= top + size:
                return index
        return None

    def on_click(self, _widget, event):
        index = self.hit_test(event.x, event.y)
        if index is None:
            self.cancel()
        else:
            self.activate(index)
        return True

    def on_motion(self, _widget, event):
        index = self.hit_test(event.x, event.y)
        if index is not None:
            self.select(index)
        return True

    def on_frame(self, _widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        elapsed = 0.0 if self.last_frame_time is None else min(0.1, max(0.0, now - self.last_frame_time))
        self.last_frame_time = now
        blend = 1 - math.exp(-EASE_RATE * elapsed)
        moving = False
        for index in range(len(ACTIONS)):
            target = 1.0 if index == self.selected else 0.0
            if abs(target - self.focus[index]) > 0.002:
                self.focus[index] += (target - self.focus[index]) * blend
                moving = True
        if self.opacity < 0.999:
            self.opacity += (1.0 - self.opacity) * blend
            moving = True
        if moving or self.armed is not None:
            self.area.queue_draw()
        return True

    def draw_text(self, cr, text, cx, y, size, color, alpha, bold=False):
        cr.new_path()
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(size)
        extents = cr.text_extents(text)
        cr.move_to(cx - extents.width / 2 - extents.x_bearing, y)
        cr.set_source_rgba(*color, alpha)
        cr.show_text(text)
        cr.new_path()

    def on_draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        colors = self.colors
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*colors["background"], 0.55 * self.opacity)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.push_group()
        count = len(ACTIONS)
        total = count * TILE_SIZE + (count - 1) * TILE_GAP
        left_edge = (width - total) / 2
        cy = height / 2 - 10
        self.hit_boxes = []
        for index, action in enumerate(ACTIONS):
            focus = self.focus[index]
            size = TILE_SIZE * (1 + FOCUS_GROWTH * focus)
            cx = left_edge + index * (TILE_SIZE + TILE_GAP) + TILE_SIZE / 2
            left, top = cx - size / 2, cy - size / 2
            danger = action["key"] in ("reboot", "shutdown") and self.armed == index
            border = colors["urgent"] if danger else colors["accent"]
            rounded_rectangle(cr, left, top, size, size, size * 0.24)
            cr.set_source_rgba(*colors["surface"], 0.78 + 0.17 * focus)
            cr.fill_preserve()
            cr.set_source_rgba(*border, 0.25 + 0.75 * focus)
            cr.set_line_width(1.5 + 1.5 * focus)
            cr.stroke()
            icon = self.icons[index]
            if icon is not None:
                icon_size = size * 0.48
                scale = icon_size / ICON_PIXELS
                cr.save()
                cr.translate(cx - icon_size / 2, top + size * 0.18)
                cr.scale(scale, scale)
                cr.set_source_surface(icon, 0, 0)
                cr.get_source().set_filter(cairo.FILTER_GOOD)
                cr.paint()
                cr.restore()
            self.draw_text(cr, action["label"], cx, top + size * 0.86, 15 + 2 * focus, colors["foreground"], 0.75 + 0.25 * focus, focus > 0.5)
            self.hit_boxes.append((index, (left, top, size)))
        if self.armed is not None:
            pulse = 0.65 + 0.35 * math.sin(time.monotonic() * 5)
            self.draw_text(cr, CONFIRM_TEXT[ACTIONS[self.armed]["key"]], width / 2, cy + TILE_SIZE * 0.95, 16, colors["urgent"], pulse, True)
        else:
            self.draw_text(cr, "Arrows to choose  ·  Enter to confirm  ·  Esc to close", width / 2, cy + TILE_SIZE * 0.95, 13, colors["foreground"], 0.55)
        cr.pop_group_to_source()
        cr.paint_with_alpha(self.opacity)
        return False

    def run(self):
        self.window.show_all()
        self.area.add_tick_callback(self.on_frame)
        unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: self.cancel() or False)
        play("app-open.mp3")
        Gtk.main()
        self.window.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration()
        return self.choice


def perform(choice):
    if choice is None:
        play("app-close.mp3")
        return
    play(f"power-{choice}.mp3")
    if choice == "lock":
        subprocess.Popen([str(LOCK_SCRIPT)], start_new_session=True)
        return
    time.sleep(0.7)
    if choice == "logout":
        subprocess.Popen(["sh", "-c", LOGOUT_COMMAND], start_new_session=True)
    elif choice == "reboot":
        subprocess.Popen(["systemctl", "reboot"], start_new_session=True)
    elif choice == "shutdown":
        subprocess.Popen(["systemctl", "poweroff"], start_new_session=True)


def main():
    if close_running_menu():
        return 0
    PID_FILE.write_text(str(os.getpid()))
    try:
        choice = PowerMenu().run()
    finally:
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
    perform(choice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
