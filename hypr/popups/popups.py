#!/usr/bin/env python3
import calendar
import datetime
import hashlib
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Playerctl", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Playerctl

import cairo

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kewlrice" / "albumart"
COLORS_CSS = CONFIG_DIR / "waybar" / "colors.css"
BAR_OFFSET = 52
ART_SIZE = 168
CALENDAR_CELL = 34
POSITION_INTERVAL_MS = 500
REOPEN_GUARD_SECONDS = 0.35
FALLBACK_COLORS = """
@define-color kewl_foreground #e6edf3;
@define-color kewl_background #1a1626;
@define-color kewl_surface #2b2440;
@define-color kewl_primary #9b59ff;
@define-color kewl_accent #d090ff;
"""
STYLE = """
.kewl-popup {
    background-color: alpha(@kewl_background, 0.94);
    border: 1px solid alpha(@kewl_foreground, 0.10);
    border-radius: 16px;
    padding: 16px 18px;
    color: @kewl_foreground;
    font-family: "JetBrainsMono Nerd Font", "Noto Sans", sans-serif;
}
.kewl-popup .weekday { font-size: 20px; font-weight: bold; color: @kewl_accent; }
.kewl-popup .date { font-size: 12px; color: alpha(@kewl_foreground, 0.7); margin-bottom: 8px; }
.kewl-popup .month { font-size: 14px; font-weight: bold; }
.kewl-popup button.month-step { font-size: 12px; min-width: 30px; min-height: 30px; color: @kewl_accent; }
.kewl-popup .day-name { font-size: 11px; font-weight: bold; color: @kewl_accent; }
.kewl-popup .day { font-size: 13px; border-radius: 999px; }
.kewl-popup .day.outside { color: alpha(@kewl_foreground, 0.3); }
.kewl-popup .day.today { background-color: @kewl_accent; color: @kewl_background; font-weight: bold; }
.kewl-popup .title { font-size: 16px; font-weight: bold; }
.kewl-popup .artist { font-size: 13px; color: @kewl_accent; }
.kewl-popup .album { font-size: 11px; color: alpha(@kewl_foreground, 0.6); }
.kewl-popup .time { font-size: 10px; color: alpha(@kewl_foreground, 0.65); }
.kewl-popup button {
    background: transparent;
    border: none;
    box-shadow: none;
    color: @kewl_foreground;
    font-size: 18px;
    min-width: 40px;
    min-height: 36px;
    border-radius: 999px;
}
.kewl-popup button:hover { background-color: alpha(@kewl_accent, 0.22); }
.kewl-popup button.play { background-color: @kewl_accent; color: @kewl_background; }
.kewl-popup scale trough { background-color: alpha(@kewl_foreground, 0.15); min-height: 4px; border-radius: 999px; border: none; }
.kewl-popup scale highlight { background-color: @kewl_accent; border-radius: 999px; border: none; }
.kewl-popup scale slider { background-color: @kewl_foreground; min-width: 10px; min-height: 10px; border-radius: 999px; border: none; box-shadow: none; }
"""


def install_style():
    provider = Gtk.CssProvider()
    try:
        colors = COLORS_CSS.read_text()
    except OSError:
        colors = FALLBACK_COLORS
    try:
        provider.load_from_data((colors + STYLE).encode())
    except GLib.Error:
        provider.load_from_data((FALLBACK_COLORS + STYLE).encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)


def art_cache_path(url):
    return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")


def local_art(url):
    if not url:
        return None
    if url.startswith("file://"):
        path = Path(urllib.parse.unquote(url[7:]))
        return path if path.is_file() else None
    cached = art_cache_path(url)
    return cached if cached.is_file() else None


def download_art(url):
    if not url.startswith(("http://", "https://")):
        return None
    target = art_cache_path(url)
    if target.is_file():
        return target
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(request, timeout=8).read()
        temporary = target.with_name(f".{target.name}.{os.getpid()}")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return target
    except (OSError, ValueError):
        return None


def format_time(microseconds):
    seconds = max(0, int(microseconds // 1_000_000))
    return f"{seconds // 60}:{seconds % 60:02d}"


class Popup:
    def __init__(self, on_closed, anchor_left):
        self.on_closed = on_closed
        self.closed = False
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self.window, "kewl-popup")
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.ON_DEMAND)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.TOP, BAR_OFFSET)
        if anchor_left:
            GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_margin(self.window, GtkLayerShell.Edge.LEFT, 10)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.on_window_draw)
        self.window.connect("key-press-event", self.on_key)
        self.window.connect("focus-out-event", lambda *_: GLib.timeout_add(120, self.close_if_unfocused) and False)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.get_style_context().add_class("kewl-popup")
        self.window.add(self.box)

    def on_window_draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        return False

    def show(self):
        self.window.show_all()
        self.window.present()

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def close_if_unfocused(self):
        if not self.closed and not self.window.has_toplevel_focus():
            self.close()
        return False

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cleanup()
        self.window.destroy()
        self.on_closed(self)

    def cleanup(self):
        pass


class CalendarPopup(Popup):
    def __init__(self, on_closed):
        super().__init__(on_closed, anchor_left=False)
        self.today = datetime.date.today()
        self.shown = self.today.replace(day=1)
        weekday = Gtk.Label(label=self.today.strftime("%A"))
        weekday.get_style_context().add_class("weekday")
        date = Gtk.Label(label=self.today.strftime("%B %d, %Y"))
        date.get_style_context().add_class("date")
        navigation = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER, spacing=6)
        previous = Gtk.Button(label="\uf053")
        following = Gtk.Button(label="\uf054")
        for button, step in ((previous, -1), (following, 1)):
            button.get_style_context().add_class("month-step")
            button.connect("clicked", self.on_step, step)
        self.month = Gtk.Label()
        self.month.get_style_context().add_class("month")
        self.month.set_size_request(170, -1)
        navigation.pack_start(previous, False, False, 0)
        navigation.pack_start(self.month, False, False, 0)
        navigation.pack_start(following, False, False, 0)
        self.grid = Gtk.Grid(column_spacing=4, row_spacing=4, halign=Gtk.Align.CENTER)
        for widget in (weekday, date, navigation, self.grid):
            self.box.pack_start(widget, False, False, 0)
        self.fill()
        self.show()

    def on_step(self, _button, step):
        month = self.shown.month - 1 + step
        self.shown = self.shown.replace(year=self.shown.year + month // 12, month=month % 12 + 1)
        self.fill()

    def cell(self, text, classes):
        label = Gtk.Label(label=text, xalign=0.5, yalign=0.5)
        label.set_size_request(CALENDAR_CELL, CALENDAR_CELL)
        for name in classes:
            label.get_style_context().add_class(name)
        return label

    def fill(self):
        for child in self.grid.get_children():
            self.grid.remove(child)
        self.month.set_text(self.shown.strftime("%B %Y"))
        for column, name in enumerate(calendar.day_abbr[6:] + calendar.day_abbr[:6]):
            self.grid.attach(self.cell(name[:2], ("day-name",)), column, 0, 1, 1)
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(self.shown.year, self.shown.month)
        for row, week in enumerate(weeks, start=1):
            for column, day in enumerate(week):
                classes = ["day"]
                if day.month != self.shown.month:
                    classes.append("outside")
                if day == self.today:
                    classes.append("today")
                self.grid.attach(self.cell(str(day.day), classes), column, row, 1, 1)
        self.grid.show_all()


class PlayerPopup(Popup):
    def __init__(self, on_closed):
        super().__init__(on_closed, anchor_left=True)
        self.player = None
        self.length = 0
        self.art_url = None
        self.seeking = False
        self.handlers = []
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.art = Gtk.DrawingArea()
        self.art.set_size_request(ART_SIZE, ART_SIZE)
        self.art.connect("draw", self.draw_art)
        self.art_pixbuf = None
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        details.set_size_request(260, -1)
        self.title = self.label("title")
        self.artist = self.label("artist")
        self.album = self.label("album")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("change-value", self.on_seek)
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.elapsed = self.label("time")
        self.total = self.label("time")
        self.total.set_xalign(1)
        times.pack_start(self.elapsed, True, True, 0)
        times.pack_end(self.total, True, True, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        self.play_button = None
        for glyph, action, css in (("\U000f04ae", "previous", None), ("\U000f040a", "play_pause", "play"), ("\U000f04ad", "next", None)):
            button = Gtk.Button(label=glyph)
            button.connect("clicked", self.on_control, action)
            if css:
                button.get_style_context().add_class(css)
                self.play_button = button
            controls.pack_start(button, False, False, 0)
        for widget in (self.title, self.artist, self.album):
            details.pack_start(widget, False, False, 0)
        details.pack_start(Gtk.Box(), True, True, 0)
        details.pack_start(self.scale, False, False, 0)
        details.pack_start(times, False, False, 0)
        details.pack_start(controls, False, False, 4)
        row.pack_start(self.art, False, False, 0)
        row.pack_start(details, True, True, 0)
        self.box.pack_start(row, False, False, 0)
        self.manager = Playerctl.PlayerManager()
        self.handlers.append((self.manager, self.manager.connect("name-appeared", lambda *_: self.attach())))
        self.handlers.append((self.manager, self.manager.connect("player-vanished", lambda *_: self.attach())))
        self.attach()
        self.timer = GLib.timeout_add(POSITION_INTERVAL_MS, self.update_position)
        self.show()

    def label(self, css):
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(3)
        label.set_max_width_chars(30)
        label.get_style_context().add_class(css)
        return label

    def attach(self):
        if self.player:
            for source, handler in [entry for entry in self.handlers if entry[0] is self.player]:
                source.disconnect(handler)
            self.handlers = [entry for entry in self.handlers if entry[0] is not self.player]
            self.player = None
        names = Playerctl.list_players()
        if names:
            try:
                self.player = Playerctl.Player.new_from_name(names[0])
                self.manager.manage_player(self.player)
            except GLib.Error:
                self.player = None
        if self.player:
            self.handlers.append((self.player, self.player.connect("metadata", lambda *_: self.update_metadata())))
            self.handlers.append((self.player, self.player.connect("playback-status", lambda *_: self.update_status())))
        self.update_metadata()
        self.update_status()
        return False

    def metadata_value(self, key):
        try:
            value = self.player.print_metadata_prop(key) if self.player else None
        except GLib.Error:
            value = None
        return value or ""

    def update_metadata(self):
        if not self.player:
            self.title.set_text("Nothing playing")
            self.artist.set_text("")
            self.album.set_text("")
            self.set_art(None)
            return
        self.title.set_text(self.metadata_value("xesam:title") or "Unknown title")
        self.artist.set_text(self.metadata_value("xesam:artist"))
        self.album.set_text(self.metadata_value("xesam:album"))
        length = self.metadata_value("mpris:length")
        self.length = int(length) if length.isdigit() else 0
        self.scale.set_range(0, max(1, self.length))
        self.total.set_text(format_time(self.length))
        url = self.metadata_value("mpris:artUrl")
        if url != self.art_url:
            self.art_url = url
            path = local_art(url)
            self.set_art(path)
            if path is None and url:
                threading.Thread(target=self.fetch_art, args=(url,), daemon=True).start()
        self.update_position()

    def fetch_art(self, url):
        path = download_art(url)
        if path:
            GLib.idle_add(lambda: (self.art_url == url and not self.closed and self.set_art(path)) and False)

    def set_art(self, path):
        try:
            self.art_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), ART_SIZE, ART_SIZE, False) if path else None
        except GLib.Error:
            self.art_pixbuf = None
        self.art.queue_draw()

    def draw_art(self, _widget, cr):
        radius = 14
        cr.new_sub_path()
        cr.arc(ART_SIZE - radius, radius, radius, -1.5708, 0)
        cr.arc(ART_SIZE - radius, ART_SIZE - radius, radius, 0, 1.5708)
        cr.arc(radius, ART_SIZE - radius, radius, 1.5708, 3.1416)
        cr.arc(radius, radius, radius, 3.1416, 4.7124)
        cr.close_path()
        cr.clip()
        if self.art_pixbuf:
            Gdk.cairo_set_source_pixbuf(cr, self.art_pixbuf, 0, 0)
        else:
            cr.set_source_rgba(1, 1, 1, 0.08)
        cr.paint()
        return False

    def update_status(self):
        playing = bool(self.player) and self.player.props.playback_status == Playerctl.PlaybackStatus.PLAYING
        if self.play_button:
            self.play_button.set_label("\U000f03e4" if playing else "\U000f040a")
        return False

    def update_position(self):
        if self.closed:
            return False
        if self.player and not self.seeking:
            try:
                position = self.player.get_position()
            except GLib.Error:
                position = 0
            self.scale.set_value(position)
            self.elapsed.set_text(format_time(position))
        return True

    def on_seek(self, _scale, _scroll, value):
        if self.player:
            try:
                self.player.set_position(int(max(0, min(value, self.length))))
            except GLib.Error:
                pass
        return False

    def on_control(self, _button, action):
        if not self.player:
            return
        try:
            getattr(self.player, action)()
        except GLib.Error:
            pass

    def cleanup(self):
        GLib.source_remove(self.timer)
        for source, handler in self.handlers:
            source.disconnect(handler)
        self.handlers = []


POPUPS = {"calendar": CalendarPopup, "player": PlayerPopup}


class PopupHost:
    def __init__(self):
        self.open = {}
        self.closed_at = {}
        self.styled = False

    def closed(self, name, popup):
        if self.open.get(name) is popup:
            self.open.pop(name)
        self.closed_at[name] = time.monotonic()

    def toggle(self, name):
        if name not in POPUPS:
            return False
        if not self.styled:
            install_style()
            self.styled = True
        current = self.open.pop(name, None)
        if current:
            current.close()
            return False
        if time.monotonic() - self.closed_at.get(name, 0) < REOPEN_GUARD_SECONDS:
            return False
        self.open[name] = POPUPS[name](lambda popup, key=name: self.closed(key, popup))
        return False


def main(arguments):
    if not arguments or arguments[0] not in POPUPS:
        return 2
    host = PopupHost()
    host.toggle(arguments[0])
    popup = host.open.get(arguments[0])
    if popup is None:
        return 0
    popup.window.connect("destroy", lambda *_: Gtk.main_quit())
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
