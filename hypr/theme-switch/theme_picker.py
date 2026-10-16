import hashlib
import math
import os
import signal
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell


try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
    unix_signal_add = GLibUnix.signal_add
except (ValueError, ImportError):
    unix_signal_add = GLib.unix_signal_add

import cairo

PID_FILE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "kewl-theme-picker.pid"
THUMBNAIL_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kewlrice" / "thumbnails"
THUMBNAIL_HEIGHT = 720
THUMBNAIL_LIMIT = 40
DOT_KEYS = ("background", "surface", "primary", "secondary", "accent", "foreground")
SCROLL_RATE = 12.0
FOCUS_GROWTH = 0.16
CARD_MARGIN = 40
FONT = "Noto Sans"


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))


def is_theme_switcher(pid):
    try:
        return b"theme_switch" in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def close_running_picker():
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid() or not is_theme_switcher(pid):
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


def load_thumbnail(wallpaper):
    if not wallpaper:
        return None
    try:
        stat = wallpaper.stat()
        key = hashlib.sha1(f"{wallpaper}:{stat.st_mtime_ns}:{stat.st_size}:{THUMBNAIL_HEIGHT}".encode()).hexdigest()
        cached = THUMBNAIL_DIR / f"{key}.png"
        if cached.is_file():
            cached.touch()
            return GdkPixbuf.Pixbuf.new_from_file(str(cached))
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(wallpaper), -1, THUMBNAIL_HEIGHT, True)
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_name(f".{key}.{os.getpid()}.png")
        pixbuf.savev(str(temporary), "png", [], [])
        os.replace(temporary, cached)
        prune_thumbnails()
        return pixbuf
    except (OSError, GLib.Error):
        return None


def prune_thumbnails():
    def modified(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0
    thumbnails = sorted(THUMBNAIL_DIR.glob("*.png"), key=modified, reverse=True)
    for path in thumbnails[THUMBNAIL_LIMIT:]:
        path.unlink(missing_ok=True)


def rounded_rectangle(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def card_path(cr, cx, cy, width, height, skew):
    cr.new_path()
    cr.move_to(cx - width / 2 + skew / 2, cy - height / 2)
    cr.line_to(cx + width / 2 + skew / 2, cy - height / 2)
    cr.line_to(cx + width / 2 - skew / 2, cy + height / 2)
    cr.line_to(cx - width / 2 - skew / 2, cy + height / 2)
    cr.close_path()


class ThemePicker:
    def __init__(self, entries, current):
        self.entries = entries
        self.current = current
        names = [entry["name"] for entry in entries]
        self.selected = names.index(current) if current in names else 0
        self.position = float(self.selected)
        self.choice = None
        self.card_boxes = []
        self.layout = None
        self.background = None
        self.sprites = {}
        self.labels = {}
        self.last_frame_time = None
        self.drawn_position = None
        self.drawn_selected = None
        self.build_window()

    def build_window(self):
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self.window, "kewl-theme-picker")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        area.connect("draw", self.on_draw)
        area.connect("button-press-event", self.on_click)
        area.connect("scroll-event", self.on_scroll)
        self.window.connect("key-press-event", self.on_key)
        self.area = area
        self.window.add(area)

    def move(self, step):
        self.selected = (self.selected + step) % len(self.entries)

    def finish(self, choice):
        if self.finished:
            return
        self.finished = True
        self.choice = choice
        Gtk.main_quit()

    def on_close_signal(self):
        self.close_signal_pending = False
        self.finish(None)
        return False

    def on_frame(self, _widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        elapsed = 0.0 if self.last_frame_time is None else min(0.1, max(0.0, now - self.last_frame_time))
        self.last_frame_time = now
        difference = self.selected - self.position
        if abs(difference) > 0.0005:
            self.position += difference * (1 - math.exp(-SCROLL_RATE * elapsed))
        else:
            self.position = float(self.selected)
        if self.layout:
            if self.selected != self.drawn_selected:
                self.area.queue_draw_area(*self.layout["dirty"])
            elif self.position != self.drawn_position:
                self.area.queue_draw_area(*self.layout["cards"])
        return True

    def on_key(self, _widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.finish(None)
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.finish(self.entries[self.selected]["name"])
        elif key in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.move(-1)
        elif key in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Tab):
            self.move(1)
        return True

    def on_click(self, _widget, event):
        if event.button == 3:
            self.finish(None)
            return True
        for index, (left, top, right, bottom) in reversed(self.card_boxes):
            if left <= event.x <= right and top <= event.y <= bottom:
                if index == self.selected:
                    self.finish(self.entries[index]["name"])
                else:
                    self.selected = index
                return True
        self.finish(None)
        return True

    def on_scroll(self, _widget, event):
        if event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            self.move(-1)
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            self.move(1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, delta_x, delta_y = event.get_scroll_deltas()
            delta = delta_y if abs(delta_y) >= abs(delta_x) else delta_x
            if abs(delta) >= 0.5:
                self.move(1 if delta > 0 else -1)
        return True

    def card_sprite(self, index, focused):
        key = (index, focused)
        sprite = self.sprites.get(key)
        if sprite:
            return sprite
        layout = self.layout
        grow = 1 + FOCUS_GROWTH
        width, height, skew = layout["card_width"] * grow, layout["card_height"] * grow, layout["skew"] * grow
        box_width = width + skew
        surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, int(math.ceil(box_width)) + 2 * CARD_MARGIN, int(math.ceil(height)) + 2 * CARD_MARGIN,
        )
        cr = cairo.Context(surface)
        cx, cy = surface.get_width() / 2, surface.get_height() / 2
        entry = self.entries[index]
        palette = entry["palette"]
        if focused:
            for ring in range(6, 0, -1):
                card_path(cr, cx, cy + 8, width + ring * 5, height + ring * 5, skew)
                cr.set_source_rgba(0, 0, 0, 0.06)
                cr.fill()
        cr.save()
        card_path(cr, cx, cy, width, height, skew)
        cr.clip()
        thumbnail = entry["thumbnail"]
        if thumbnail:
            scale = max(box_width / thumbnail.get_width(), height / thumbnail.get_height())
            cr.save()
            cr.translate(cx - thumbnail.get_width() * scale / 2, cy - thumbnail.get_height() * scale / 2)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, thumbnail, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
            cr.restore()
        else:
            gradient = cairo.LinearGradient(cx - box_width / 2, cy - height / 2, cx + box_width / 2, cy + height / 2)
            gradient.add_color_stop_rgb(0, *hex_to_rgb(palette["primary"]))
            gradient.add_color_stop_rgb(1, *hex_to_rgb(palette["background"]))
            cr.set_source(gradient)
            cr.paint()
        if not focused:
            cr.set_source_rgba(0, 0, 0, 0.45)
            cr.paint()
        shine = cairo.LinearGradient(cx, cy - height / 2, cx, cy + height / 2)
        shine.add_color_stop_rgba(0, 1, 1, 1, 0.10)
        shine.add_color_stop_rgba(0.4, 1, 1, 1, 0.0)
        cr.set_source(shine)
        cr.paint()
        cr.restore()
        card_path(cr, cx, cy, width, height, skew)
        if focused:
            cr.set_source_rgba(*hex_to_rgb(palette["accent"]), 1.0)
            cr.set_line_width(3)
        else:
            cr.set_source_rgba(1, 1, 1, 0.12)
            cr.set_line_width(1)
        cr.stroke()
        surface.flush()
        self.sprites[key] = surface
        return surface

    def draw_card(self, cr, index, cx, cy, focus):
        scale = (1 + FOCUS_GROWTH * focus) / (1 + FOCUS_GROWTH)
        layers = []
        if focus < 0.995:
            layers.append((self.card_sprite(index, False), 1.0))
        if focus > 0.005:
            layers.append((self.card_sprite(index, True), 1.0 if focus >= 0.995 else focus))
        for sprite, alpha in layers:
            cr.save()
            cr.translate(cx - sprite.get_width() * scale / 2, cy - sprite.get_height() * scale / 2)
            cr.scale(scale, scale)
            cr.set_source_surface(sprite, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint_with_alpha(alpha)
            cr.restore()

    def draw_text(self, cr, text, x, y, size, color, alpha=1.0, bold=False, center=False):
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(size)
        extents = cr.text_extents(text)
        cr.move_to(x - (extents.width / 2 + extents.x_bearing if center else 0), y)
        cr.set_source_rgba(*color, alpha)
        cr.show_text(text)
        return extents.x_advance

    def draw_pill(self, cr, entry, cx, y):
        palette = entry["palette"]
        foreground = hex_to_rgb(palette["foreground"])
        label = entry["name"].replace("-", " ").replace("_", " ").title()
        badge = "Active" if entry["name"] == self.current else ""
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(15)
        label_width = cr.text_extents(label).x_advance
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        badge_width = cr.text_extents(badge).x_advance + 16 if badge else 0
        dot, gap, padding = 16, 8, 14
        width = padding * 2 + label_width + 14 + len(DOT_KEYS) * (dot + gap) - gap + (badge_width + 10 if badge else 0)
        height = 38
        left = cx - width / 2
        rounded_rectangle(cr, left, y, width, height, height / 2)
        cr.set_source_rgba(*hex_to_rgb(palette["surface"]), 0.85)
        cr.fill_preserve()
        cr.set_source_rgba(*foreground, 0.15)
        cr.set_line_width(1)
        cr.stroke()
        x = left + padding
        x += self.draw_text(cr, label, x, y + 25, 15, foreground, 1.0, True) + 14
        for key in DOT_KEYS:
            cr.new_path()
            cr.arc(x + dot / 2, y + height / 2, dot / 2, 0, 2 * math.pi)
            cr.set_source_rgb(*hex_to_rgb(palette[key]))
            cr.fill_preserve()
            cr.set_source_rgba(*foreground, 0.35)
            cr.set_line_width(1)
            cr.stroke()
            x += dot + gap
        if badge:
            x += 10 - gap
            rounded_rectangle(cr, x, y + 9, badge_width, 20, 10)
            cr.set_source_rgb(*hex_to_rgb(palette["accent"]))
            cr.fill()
            self.draw_text(cr, badge, x + 8, y + 23, 11, foreground)

    def compute_layout(self, width, height):
        card_height = height * 0.42
        card_width = card_height * 0.6
        skew = card_height * 0.22
        cx, cy = width / 2, height / 2 + 10
        top = int(cy - card_height * 0.58 - 70)
        bottom = int(cy + card_height * 0.58 + 70)
        band = card_height * (1 + FOCUS_GROWTH) / 2
        cards_top = int(cy - band - 12)
        cards_bottom = int(cy + band + 52)
        return {
            "width": width, "height": height, "card_width": card_width, "card_height": card_height,
            "skew": skew, "cx": cx, "cy": cy, "dirty": (0, top, width, bottom - top),
            "cards": (0, cards_top, width, cards_bottom - cards_top),
        }

    def label_sprite(self, index):
        sprite = self.labels.get(index)
        if sprite:
            return sprite
        layout = self.layout
        top = layout["dirty"][1]
        sprite = cairo.ImageSurface(cairo.FORMAT_ARGB32, layout["width"], layout["dirty"][3])
        cr = cairo.Context(sprite)
        cr.translate(0, -top)
        entry = self.entries[index]
        cx, cy, card_height = layout["cx"], layout["cy"], layout["card_height"]
        self.draw_pill(cr, entry, cx, cy - card_height * 0.58 - 62)
        sprite.flush()
        self.labels[index] = sprite
        return sprite

    def render_background(self):
        layout = self.layout
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, layout["width"], layout["height"])
        cr = cairo.Context(surface)
        current = next((entry for entry in self.entries if entry["name"] == self.current), self.entries[0])
        cr.set_source_rgba(*hex_to_rgb(current["palette"]["background"]), 0.6)
        cr.paint()
        surface.flush()
        self.background = surface

    def on_draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        if not self.layout or self.layout["width"] != width or self.layout["height"] != height:
            self.layout = self.compute_layout(width, height)
            self.sprites = {}
            self.labels = {}
            self.render_background()
        layout = self.layout
        entry = self.entries[self.selected]
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.background, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        card_width, card_height, skew = layout["card_width"], layout["card_height"], layout["skew"]
        cx, cy = layout["cx"], layout["cy"]
        order = sorted(range(len(self.entries)), key=lambda index: -abs(index - self.position))
        self.card_boxes = []
        for index in order:
            distance = index - self.position
            focus = max(0.0, 1 - abs(distance))
            scale = 1 + FOCUS_GROWTH * focus
            x = cx + distance * card_width * 1.02
            if x + card_width < -skew or x - card_width > width + skew:
                continue
            w, h = card_width * scale, card_height * scale
            self.draw_card(cr, index, x, cy, focus)
            self.card_boxes.append((index, (x - w / 2 - skew / 2, cy - h / 2, x + w / 2 + skew / 2, cy + h / 2)))
        labels = self.label_sprite(self.selected)
        cr.set_source_surface(labels, 0, layout["dirty"][1])
        cr.paint()
        self.drawn_position = self.position
        self.drawn_selected = self.selected
        return False

    def prerender(self):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0) if display else None
        if not monitor:
            return
        geometry = monitor.get_geometry()
        self.layout = self.compute_layout(geometry.width, geometry.height)
        self.render_background()
        for index in range(len(self.entries)):
            self.card_sprite(index, False)
            self.card_sprite(index, True)
            self.label_sprite(index)

    def run(self):
        self.prerender()
        self.window.show_all()
        self.area.add_tick_callback(self.on_frame)
        self.finished = False
        self.close_signal_pending = True
        close_signal = unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.on_close_signal)
        Gtk.main()
        if self.close_signal_pending:
            GLib.source_remove(close_signal)
        self.window.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration()
        return self.choice


def pick_theme(entries, current):
    if close_running_picker() or not entries:
        return None
    PID_FILE.write_text(str(os.getpid()))
    try:
        for entry in entries:
            entry["thumbnail"] = load_thumbnail(entry["wallpaper"])
        return ThemePicker(entries, current).run()
    finally:
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
