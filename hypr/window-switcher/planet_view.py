import math
import os
import subprocess
import ctypes
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell

import cairo

import globe_builder
from celestial import Sky, mix

THEME_SWITCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "theme-switch")
FALLBACK_COLORS = {
    "background": "#2c0809",
    "foreground": "#f3e6e4",
    "surface": "#460f11",
    "primary": "#800020",
    "secondary": "#893f45",
    "accent": "#c06a73",
}
MAC_ICON_THEMES = ("WhiteSur-dark", "WhiteSur")
FALLBACK_ICON = "application-x-executable"
ICON_PIXELS = 192
MAX_ICON_SIZE = 68
MIN_ICON_SIZE = 40
SELECTED_GROWTH = 0.3
APP_SPACING_DEGREES = 40.0
APP_LATITUDES = (14, -4, 28, 6, 22, -10, 16, 0, 32, 10, 24, -2)
TURN_RATE = 9.5
SCALE_RATE = 18.0
GLOBE_PITCH = 14.0
MAX_GLOBE_SIZE = 480
LABEL_SPACE = 110
DAWN_ORANGE = (1.0, 0.58, 0.3)
FONT = "Noto Sans"


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))


def load_active_theme():
    try:
        if THEME_SWITCH_DIR not in sys.path:
            sys.path.insert(0, THEME_SWITCH_DIR)
        import theme_switch
        name = theme_switch.current_theme() or theme_switch.DEFAULT_THEME
        _, palette = theme_switch.load_palette(name)
        colors = {key: palette.get(key, value) for key, value in FALLBACK_COLORS.items()}
        return colors, name
    except Exception:
        return dict(FALLBACK_COLORS), "default"


def pretty_app_name(window_class):
    name = (window_class or "App").split(".")[-1].replace("-", " ").replace("_", " ").strip()
    return name.title() if name.islower() else name or "App"


def squircle_path(cr, x, y, size):
    radius = size * 0.2237
    cr.new_sub_path()
    cr.arc(x + size - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + size - radius, y + size - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + size - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def wrap_degrees(value):
    return (value + 180) % 360 - 180


def start_globe_build(name):
    builder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "globe_builder.py")
    try:
        subprocess.Popen(
            [sys.executable, builder, name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        pass


class GlobeRenderer:
    def __init__(self, colors, theme_name):
        self.ready = False
        self.size = 0
        directory = globe_builder.cache_dir(colors)
        if not globe_builder.is_ready(directory):
            if globe_builder.geodata_available():
                start_globe_build(theme_name)
            return
        try:
            self.library = globe_builder.load_renderer()
            self.texture = globe_builder.load_texture(directory)
        except (OSError, RuntimeError, ValueError):
            return
        self.texture_pointer = ctypes.addressof((ctypes.c_char * len(self.texture)).from_buffer(self.texture))
        self.ready = True

    def prepare(self, size):
        if not self.ready or size == self.size:
            return
        self.size = size
        count = size * size
        self.u = (ctypes.c_float * count)()
        self.v = (ctypes.c_float * count)()
        self.coverage = (ctypes.c_float * count)()
        self.library.globe_prepare(
            size, GLOBE_PITCH, globe_builder.RUNTIME_WIDTH, globe_builder.RUNTIME_HEIGHT, self.u, self.v, self.coverage,
        )
        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        self.output = self.surface.get_data()
        self.output_pointer = ctypes.addressof((ctypes.c_char * len(self.output)).from_buffer(self.output))

    def set_lighting(self, surface):
        self.lighting = surface
        self.lighting_data = surface.get_data()
        self.lighting_pointer = ctypes.addressof((ctypes.c_char * len(self.lighting_data)).from_buffer(self.lighting_data))

    def render(self, yaw):
        shift = (yaw % 360) / 360 * globe_builder.RUNTIME_WIDTH
        self.surface.flush()
        self.library.globe_render(
            self.texture_pointer, globe_builder.RUNTIME_WIDTH, globe_builder.RUNTIME_HEIGHT, self.u, self.v,
            self.coverage, self.size, self.output_pointer, self.surface.get_stride(),
            self.lighting_pointer, self.lighting.get_stride(), shift,
        )
        self.surface.mark_dirty()
        return self.surface


class PlanetSwitcher:
    def __init__(self, windows, icon_names, tabs_pressed, alt_released):
        self.windows = windows
        self.count = len(windows)
        self.tabs_pressed = tabs_pressed
        self.alt_released = alt_released
        self.offset = 0
        self.tab_count = max(1, tabs_pressed())
        self.choice = None
        self.colors, theme_name = load_active_theme()
        self.rgb = {key: hex_to_rgb(value) for key, value in self.colors.items()}
        self.sky = Sky()
        self.globe = GlobeRenderer(self.colors, theme_name)
        self.mac_themes = []
        for name in MAC_ICON_THEMES:
            theme = Gtk.IconTheme()
            theme.set_custom_theme(name)
            self.mac_themes.append(theme)
        self.app_positions = self.place_apps()
        self.icon_sprites = [self.icon_sprite(window, icon_names) for window in windows]
        self.yaw = self.app_positions[self.selected_index()][0]
        self.scales = [1.0 if index == self.selected_index() else 0.0 for index in range(self.count)]
        self.lighting = None
        self.layout = None
        self.hit_boxes = []
        self.last_selected = None
        self.last_frame_time = None
        self.build_window()

    def place_apps(self):
        spacing = min(360.0 / self.count, APP_SPACING_DEGREES)
        return [(wrap_degrees(index * spacing), APP_LATITUDES[index % len(APP_LATITUDES)]) for index in range(self.count)]

    def icon_candidates(self, window, icon_names):
        window_class = (window.get("class") or "").lower()
        names = [icon_names.get(window_class), window_class, window_class.split(".")[-1]]
        return [name for index, name in enumerate(names) if name and name not in names[:index]]

    def load_icon(self, window, icon_names):
        candidates = self.icon_candidates(window, icon_names)
        for theme in self.mac_themes:
            for name in candidates:
                if os.path.isabs(name):
                    continue
                try:
                    pixbuf = theme.load_icon(name, ICON_PIXELS, Gtk.IconLookupFlags.FORCE_SIZE)
                except GLib.Error:
                    continue
                if pixbuf:
                    return pixbuf, True
        default = Gtk.IconTheme.get_default()
        for name in candidates + [FALLBACK_ICON]:
            try:
                if os.path.isabs(name):
                    if os.path.isfile(name):
                        return GdkPixbuf.Pixbuf.new_from_file_at_scale(name, ICON_PIXELS, ICON_PIXELS, True), False
                    continue
                pixbuf = default.load_icon(name, ICON_PIXELS, Gtk.IconLookupFlags.FORCE_SIZE)
                if pixbuf:
                    return pixbuf, False
            except GLib.Error:
                continue
        return None, False

    def icon_sprite(self, window, icon_names):
        pixbuf, native = self.load_icon(window, icon_names)
        size = ICON_PIXELS
        padding = int(size * 0.12)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size + 2 * padding, size + 2 * padding)
        cr = cairo.Context(surface)
        if native and pixbuf:
            scale = size / max(pixbuf.get_width(), pixbuf.get_height())
            cr.save()
            cr.translate(padding, padding)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            squircle_path(cr, padding, padding, size)
            tile = cairo.LinearGradient(0, padding, 0, padding + size)
            tile.add_color_stop_rgb(0, 0.99, 0.99, 1.0)
            tile.add_color_stop_rgb(1, 0.89, 0.89, 0.92)
            cr.set_source(tile)
            cr.fill()
            if pixbuf:
                inner = size * 0.7
                scale = inner / max(pixbuf.get_width(), pixbuf.get_height())
                cr.save()
                cr.translate(padding + (size - pixbuf.get_width() * scale) / 2, padding + (size - pixbuf.get_height() * scale) / 2)
                cr.scale(scale, scale)
                Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
                cr.paint()
                cr.restore()
        surface.flush()
        return surface, padding

    def build_window(self):
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self.window, "kewl-switcher")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        area = Gtk.DrawingArea()
        area.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        area.connect("draw", self.on_draw)
        area.connect("button-press-event", self.on_click)
        area.connect("motion-notify-event", self.on_motion)
        area.connect("scroll-event", self.on_scroll)
        self.window.connect("key-press-event", self.on_key)
        self.window.add(area)
        self.area = area

    def tab_index(self):
        return self.tab_count % self.count

    def selected_index(self):
        return (self.tab_index() + self.offset) % self.count

    def select(self, index):
        self.offset = index - self.tab_index()

    def finish(self, choice):
        self.choice = choice
        Gtk.main_quit()

    def compute_layout(self, width, height):
        radius = int(min(height * 0.24, MAX_GLOBE_SIZE / 2))
        cx, cy = width / 2, height / 2 + height * 0.11
        margin = MAX_ICON_SIZE * (1 + SELECTED_GROWTH)
        dirty = (
            int(cx - radius - margin), int(cy - radius - margin),
            int(2 * (radius + margin)), int(2 * radius + 2 * margin + LABEL_SPACE),
        )
        return {"width": width, "height": height, "cx": cx, "cy": cy, "radius": radius, "dirty": dirty}

    def on_frame(self, _widget, frame_clock):
        now = frame_clock.get_frame_time() / 1_000_000
        elapsed = 0.0 if self.last_frame_time is None else min(0.1, max(0.0, now - self.last_frame_time))
        self.last_frame_time = now
        return self.tick(elapsed)

    def tick(self, elapsed=1 / 60):
        if self.choice is not None or self.alt_released():
            if self.choice is None:
                self.tab_count = max(1, self.tabs_pressed())
                self.finish(self.selected_index())
            return False
        self.tab_count = max(1, self.tabs_pressed())
        selected = self.selected_index()
        changed = selected != self.last_selected
        turn = 1 - math.exp(-TURN_RATE * elapsed)
        grow = 1 - math.exp(-SCALE_RATE * elapsed)
        difference = wrap_degrees(self.app_positions[selected][0] - self.yaw)
        if abs(difference) > 0.02:
            self.yaw = wrap_degrees(self.yaw + difference * turn)
            changed = True
        for index in range(self.count):
            target = 1.0 if index == selected else 0.0
            if abs(target - self.scales[index]) > 0.002:
                self.scales[index] += (target - self.scales[index]) * grow
                changed = True
        if changed and self.layout:
            self.area.queue_draw_area(*self.layout["dirty"])
        self.last_selected = selected
        return True

    def on_key(self, _widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.finish(None)
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.finish(self.selected_index())
        elif key in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.offset -= 1
        elif key in (Gdk.KEY_Right, Gdk.KEY_Down):
            self.offset += 1
        return True

    def hit_test(self, x, y):
        for index, (left, top, size) in reversed(self.hit_boxes):
            if left <= x <= left + size and top <= y <= top + size:
                return index
        return None

    def on_click(self, _widget, event):
        index = self.hit_test(event.x, event.y)
        if index is not None:
            self.finish(index)
        elif event.button == 3:
            self.finish(None)
        return True

    def on_motion(self, _widget, event):
        index = self.hit_test(event.x, event.y)
        if index is not None and index != self.selected_index():
            self.select(index)
        return True

    def on_scroll(self, _widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.offset -= 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.offset += 1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, _, delta = event.get_scroll_deltas()
            if abs(delta) >= 0.5:
                self.offset += 1 if delta > 0 else -1
        return True

    def draw_globe(self, cr, cx, cy, radius):
        if self.globe.ready:
            cr.set_source_surface(self.globe.render(self.yaw), cx - radius, cy - radius)
            cr.paint()
            return
        else:
            sphere = cairo.RadialGradient(cx - radius * 0.3, cy - radius * 0.3, 0, cx, cy, radius)
            sphere.add_color_stop_rgb(0, *mix(self.rgb["primary"], (1, 1, 1), 0.1))
            sphere.add_color_stop_rgb(1, *mix(self.rgb["background"], (0, 0, 0), 0.6))
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.set_source(sphere)
            cr.fill()
        cr.set_source_surface(self.lighting, cx - radius, cy - radius)
        cr.paint()

    def render_lighting(self, radius):
        period = self.sky.time_of_day
        size = int(2 * radius)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surface)
        cx = cy = size / 2
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.clip()
        if period == "night":
            cr.set_source_rgba(0.02, 0.04, 0.12, 0.28)
            cr.paint()
            shade = cairo.RadialGradient(cx, cy, radius * 0.45, cx, cy, radius)
            shade.add_color_stop_rgba(0, 0, 0, 0, 0)
            shade.add_color_stop_rgba(1, 0.0, 0.02, 0.08, 0.6)
        else:
            lx, ly, _ = self.sky.light
            lit_x, lit_y = cx + lx * radius * 0.8, cy - ly * radius * 0.8
            warmth = DAWN_ORANGE if period in ("dawn", "dusk") else (1.0, 0.96, 0.9)
            darkness = 0.82 if period in ("dawn", "dusk") else 0.6
            shade = cairo.RadialGradient(lit_x, lit_y, 0, lit_x, lit_y, radius * 2.1)
            shade.add_color_stop_rgba(0, *warmth, 0.3 if period == "day" else 0.35)
            shade.add_color_stop_rgba(0.3, *warmth, 0.05)
            shade.add_color_stop_rgba(0.6, 0, 0, 0, darkness * 0.45)
            shade.add_color_stop_rgba(1, 0, 0, 0, darkness)
        cr.set_source(shade)
        cr.paint()
        surface.flush()
        self.lighting = surface

    def draw_icons(self, cr, cx, cy, radius):
        base = max(MIN_ICON_SIZE, min(MAX_ICON_SIZE, radius * 1.2 / math.sqrt(self.count)))
        placed = []
        for index, (lon, lat) in enumerate(self.app_positions):
            dlon = math.radians(lon - self.yaw)
            latitude = math.radians(lat)
            pitch = math.radians(GLOBE_PITCH)
            x = math.cos(latitude) * math.sin(dlon)
            world_y = math.sin(latitude)
            world_z = math.cos(latitude) * math.cos(dlon)
            y = world_y * math.cos(pitch) - world_z * math.sin(pitch)
            z = world_y * math.sin(pitch) + world_z * math.cos(pitch)
            if z > 0.08:
                placed.append((z, index, x, y))
        placed.sort()
        self.hit_boxes = []
        for z, index, x, y in placed:
            highlight = self.scales[index]
            size = base * (0.55 + 0.45 * z) * (1 + SELECTED_GROWTH * highlight)
            left = cx + x * radius - size / 2
            top = cy - y * radius - size / 2
            alpha = min(1.0, (z - 0.08) / 0.3)
            sprite, padding = self.icon_sprites[index]
            scale = size / ICON_PIXELS
            cr.save()
            cr.translate(left - padding * scale, top - padding * scale)
            cr.scale(scale, scale)
            cr.set_source_surface(sprite, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint_with_alpha(alpha)
            cr.restore()
            self.hit_boxes.append((index, (left, top, size)))

    def draw_text(self, cr, text, cx, y, size, alpha, bold=False, max_width=None):
        text = "".join(character for character in text if ord(character) <= 0xFFFF and not 0x2600 <= ord(character) <= 0x27BF).strip()
        cr.new_path()
        cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(size)
        if max_width:
            while len(text) > 4 and cr.text_extents(text).width > max_width:
                text = text[:-2].rstrip() + "…"
        extents = cr.text_extents(text)
        x = cx - extents.width / 2 - extents.x_bearing
        for dx, dy, shadow in ((0, 2, 0.55), (1, 1, 0.35), (-1, 1, 0.35)):
            cr.move_to(x + dx, y + dy)
            cr.set_source_rgba(0, 0, 0, shadow * alpha)
            cr.show_text(text)
        cr.move_to(x, y)
        cr.set_source_rgba(*self.rgb["foreground"], alpha)
        cr.show_text(text)
        cr.new_path()

    def on_draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        if not self.layout or self.layout["width"] != width or self.layout["height"] != height:
            self.layout = self.compute_layout(width, height)
            self.render_lighting(self.layout["radius"])
            if self.globe.ready:
                self.globe.prepare(2 * self.layout["radius"])
                self.globe.set_lighting(self.lighting)
        layout = self.layout
        cx, cy, radius = layout["cx"], layout["cy"], layout["radius"]
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.draw_globe(cr, cx, cy, radius)
        self.draw_icons(cr, cx, cy, radius)
        selected = self.windows[self.selected_index()]
        app_name = pretty_app_name(selected.get("class"))
        title = selected.get("title") or ""
        label_top = cy + radius + 52
        self.draw_text(cr, app_name, cx, label_top, 22, 1.0, True, width * 0.4)
        if title.strip().lower() != app_name.lower():
            self.draw_text(cr, title, cx, label_top + 24, 13, 0.8, False, width * 0.4)
        return False

    def run(self):
        self.window.show_all()
        self.area.add_tick_callback(self.on_frame)
        Gtk.main()
        self.window.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration()
        return self.choice


def choose_window(windows, icon_names, tabs_pressed, alt_released):
    return PlanetSwitcher(windows, icon_names, tabs_pressed, alt_released).run()
