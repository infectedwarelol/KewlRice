#!/usr/bin/env python3
import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import urllib.request
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

HOME = Path.home()
THEME_SWITCH_DIR = Path(__file__).resolve().parent.parent / "theme-switch"
POWER_MENU = HOME / ".config" / "hypr" / "power-menu" / "power_menu.py"
LOCK_SCRIPT = HOME / ".config" / "hypr" / "lock" / "lock.sh"
PID_FILE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "kewl-control-center.pid"
ART_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "kewlrice" / "album-art"
FALLBACK_COLORS = {
    "background": "#2c0809", "foreground": "#f3e6e4", "surface": "#460f11",
    "primary": "#800020", "secondary": "#893f45", "accent": "#c06a73", "urgent": "#ffc857",
}
PANEL_WIDTH = 380
ART_SIZE = 72
ART_CACHE_LIMIT = 100
REFRESH_MILLISECONDS = 1000
SINK = "@DEFAULT_AUDIO_SINK@"
SOURCE = "@DEFAULT_AUDIO_SOURCE@"


def load_palette():
    try:
        sys.path.insert(0, str(THEME_SWITCH_DIR))
        import theme_switch
        name = theme_switch.current_theme() or theme_switch.DEFAULT_THEME
        _, palette = theme_switch.load_palette(name)
        return {key: palette.get(key, value) for key, value in FALLBACK_COLORS.items()}
    except Exception:
        return dict(FALLBACK_COLORS)


def rgba(color, alpha):
    color = color.lstrip("#")
    red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def stylesheet(palette):
    return f"""
    window {{ background-color: transparent; }}
    .panel {{
        background-color: {rgba(palette['background'], 0.94)};
        border: 1px solid {rgba(palette['accent'], 0.35)};
        border-radius: 20px;
        padding: 16px;
    }}
    .panel label {{ color: {palette['foreground']}; font-family: "Noto Sans"; }}
    .title {{ font-size: 16px; font-weight: bold; }}
    .muted {{ color: {rgba(palette['foreground'], 0.6)}; font-size: 11px; }}
    .section {{
        background-color: {rgba(palette['surface'], 0.85)};
        border-radius: 14px;
        padding: 10px 12px;
    }}
    .icon-button, .tile, .media-button, .footer-button {{
        background-image: none;
        background-color: {rgba(palette['surface'], 0.9)};
        border: 1px solid {rgba(palette['foreground'], 0.08)};
        border-radius: 12px;
        color: {palette['foreground']};
        box-shadow: none;
        text-shadow: none;
        -gtk-icon-shadow: none;
    }}
    .icon-button {{ min-width: 36px; min-height: 36px; padding: 0; font-family: "JetBrainsMono Nerd Font"; font-size: 15px; }}
    .icon-button label, .media-button label {{ font-family: "JetBrainsMono Nerd Font"; }}
    .icon-button:hover, .tile:hover, .media-button:hover, .footer-button:hover {{
        background-color: {rgba(palette['accent'], 0.25)};
    }}
    .active, .active:hover {{
        background-color: {rgba(palette['accent'], 0.85)};
        color: {palette['background']};
    }}
    .active label {{ color: {palette['background']}; }}
    .tile {{ padding: 10px 12px; min-height: 52px; }}
    .tile-icon {{ font-family: "JetBrainsMono Nerd Font"; font-size: 18px; }}
    .tile-name {{ font-size: 12px; font-weight: bold; }}
    .tile-state {{ font-size: 10px; }}
    .media-button {{ min-width: 38px; min-height: 34px; padding: 0; font-size: 15px; }}
    .footer-button {{ padding: 8px 12px; }}
    scale trough {{
        background-color: {rgba(palette['foreground'], 0.12)};
        border-radius: 6px;
        min-height: 8px;
        border: none;
    }}
    scale trough highlight, scale highlight {{
        background-color: {palette['accent']};
        background-image: none;
        border-radius: 6px;
        border: none;
    }}
    scale slider {{
        background-color: {palette['foreground']};
        border-radius: 10px;
        min-width: 16px;
        min-height: 16px;
        border: none;
        box-shadow: none;
    }}
    .song {{ font-size: 13px; font-weight: bold; }}
    .art {{ border-radius: 10px; }}
    """


def run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read_volume(target):
    output = run(["wpctl", "get-volume", target])
    match = re.search(r"Volume:\s*([0-9.]+)", output)
    if not match:
        return None, False
    return round(float(match.group(1)) * 100), "MUTED" in output


def network_status():
    for line in run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"]).splitlines():
        kind, _, rest = line.partition(":")
        state, _, connection = rest.partition(":")
        if state == "connected" and kind in ("ethernet", "wifi"):
            return ("\U000f0200" if kind == "ethernet" else "\U000f05a9"), connection or kind.title()
    return "\U000f0319", "Offline"


def dnd_enabled():
    return "do-not-disturb" in run(["makoctl", "mode"]).split()


def player_state():
    status = run(["playerctl", "status"])
    if status not in ("Playing", "Paused"):
        return None
    fields = run(["playerctl", "metadata", "--format", "{{title}}\t{{artist}}\t{{mpris:artUrl}}"]).split("\t")
    fields += [""] * (3 - len(fields))
    return {"status": status, "title": fields[0], "artist": fields[1], "art": fields[2]}


def cached_art(url):
    if not url:
        return None
    if url.startswith("file://"):
        path = Path(urllib.request.url2pathname(url[7:]))
        return path if path.is_file() else None
    target = ART_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")
    if target.is_file():
        try:
            target.touch()
        except OSError:
            pass
        return target
    if not url.startswith("https://"):
        return None
    try:
        ART_CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=5) as response:
            data = response.read(5_000_000)
        temporary = target.with_name(f"{target.stem}.{os.getpid()}.tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
        prune_art_cache()
        return target
    except (OSError, ValueError):
        return None


def prune_art_cache():
    def modified(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0
    files = sorted((path for path in ART_CACHE.iterdir() if path.is_file()), key=modified, reverse=True)
    for path in files[ART_CACHE_LIMIT:]:
        path.unlink(missing_ok=True)


def collect_state():
    return {
        "volumes": {target: read_volume(target) for target in (SINK, SOURCE)},
        "network": network_status(),
        "dnd": dnd_enabled(),
        "player": player_state(),
    }


def is_control_center(pid):
    try:
        return Path(__file__).name.encode() in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


class ControlCenter:
    def __init__(self):
        self.palette = load_palette()
        self.updating = False
        self.refreshing = False
        self.refresh_pending = False
        self.closing = False
        self.art_url = None
        self.build()

    def build(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(stylesheet(self.palette).encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.Window()
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_namespace(self.window, "kewl-control")
        GtkLayerShell.set_exclusive_zone(self.window, -1)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.window, edge, True)
        visual = self.window.get_screen().get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("key-press-event", self.on_key)
        backdrop = Gtk.EventBox()
        backdrop.set_visible_window(False)
        backdrop.connect("button-press-event", lambda *_: self.close())
        self.window.add(backdrop)
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.set_transition_duration(180)
        self.revealer.set_halign(Gtk.Align.END)
        self.revealer.set_valign(Gtk.Align.START)
        self.revealer.set_margin_top(44)
        self.revealer.set_margin_end(12)
        backdrop.add(self.revealer)
        panel_events = Gtk.EventBox()
        panel_events.connect("button-press-event", lambda *_: True)
        self.revealer.add(panel_events)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.get_style_context().add_class("panel")
        panel.set_size_request(PANEL_WIDTH, -1)
        panel_events.add(panel)
        title = Gtk.Label(label="Control center", xalign=0)
        title.get_style_context().add_class("title")
        panel.pack_start(title, False, False, 0)
        self.volume_button, self.volume_scale = self.slider_row(panel, SINK, "\U000f057e")
        self.mic_button, self.mic_scale = self.slider_row(panel, SOURCE, "\U000f036c")
        tiles = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        panel.pack_start(tiles, False, False, 0)
        self.network_tile = self.tile("\U000f0200", "Network", "")
        self.dnd_tile = self.tile("\U000f009b", "Do not disturb", "")
        self.dnd_tile.connect("clicked", self.toggle_dnd)
        self.media_tile = self.tile("\U000f075a", "Media", "")
        self.media_tile.connect("clicked", lambda *_: run(["playerctl", "play-pause"]) or self.refresh())
        tiles.attach(self.network_tile, 0, 0, 1, 1)
        tiles.attach(self.dnd_tile, 1, 0, 1, 1)
        tiles.attach(self.media_tile, 0, 1, 2, 1)
        self.media_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.media_box.get_style_context().add_class("section")
        self.art = Gtk.Image()
        self.art.set_size_request(ART_SIZE, ART_SIZE)
        self.media_box.pack_start(self.art, False, False, 0)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.song = Gtk.Label(xalign=0)
        self.song.set_ellipsize(3)
        self.song.get_style_context().add_class("song")
        self.artist = Gtk.Label(xalign=0)
        self.artist.set_ellipsize(3)
        self.artist.get_style_context().add_class("muted")
        controls = Gtk.Box(spacing=6)
        for glyph, action in (("\U000f04ae", "previous"), ("\U000f040a", "play-pause"), ("\U000f04ad", "next")):
            button = Gtk.Button(label=glyph)
            button.get_style_context().add_class("media-button")
            button.connect("clicked", lambda _button, command=action: self.media(command))
            controls.pack_start(button, False, False, 0)
            if action == "play-pause":
                self.play_button = button
        details.pack_start(self.song, False, False, 0)
        details.pack_start(self.artist, False, False, 0)
        details.pack_end(controls, False, False, 0)
        self.media_box.pack_start(details, True, True, 0)
        panel.pack_start(self.media_box, False, False, 0)
        footer = Gtk.Box(spacing=10, homogeneous=True)
        for label, handler in (("\U000f033e  Lock", self.lock), ("\U000f0425  Power", self.power)):
            button = Gtk.Button(label=label)
            button.get_style_context().add_class("footer-button")
            button.get_child().set_name("footer-label")
            button.connect("clicked", handler)
            footer.pack_start(button, True, True, 0)
        panel.pack_start(footer, False, False, 0)

    def slider_row(self, panel, target, glyph):
        row = Gtk.Box(spacing=10)
        row.get_style_context().add_class("section")
        button = Gtk.Button(label=glyph)
        button.get_style_context().add_class("icon-button")
        button.connect("clicked", lambda *_: run(["wpctl", "set-mute", target, "toggle"]) or self.refresh())
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.connect("value-changed", lambda widget: self.set_volume(target, widget.get_value()))
        row.pack_start(button, False, False, 0)
        row.pack_start(scale, True, True, 0)
        panel.pack_start(row, False, False, 0)
        return button, scale

    def tile(self, glyph, name, state):
        button = Gtk.Button()
        button.get_style_context().add_class("tile")
        box = Gtk.Box(spacing=10)
        icon = Gtk.Label(label=glyph)
        icon.get_style_context().add_class("tile-icon")
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label=name, xalign=0)
        title.get_style_context().add_class("tile-name")
        value = Gtk.Label(label=state, xalign=0)
        value.set_ellipsize(3)
        value.get_style_context().add_class("tile-state")
        texts.pack_start(title, False, False, 0)
        texts.pack_start(value, False, False, 0)
        box.pack_start(icon, False, False, 0)
        box.pack_start(texts, True, True, 0)
        button.add(box)
        button.icon_label = icon
        button.value_label = value
        return button

    def set_active(self, widget, active):
        context = widget.get_style_context()
        if active:
            context.add_class("active")
        else:
            context.remove_class("active")

    def set_volume(self, target, value):
        if not self.updating:
            run(["wpctl", "set-volume", target, f"{int(value)}%"])

    def toggle_dnd(self, *_):
        run(["makoctl", "mode", "-t", "do-not-disturb"])
        self.refresh()

    def media(self, command):
        run(["playerctl", command])
        GLib.timeout_add(250, self.refresh_once)

    def refresh_once(self):
        self.refresh()
        return False

    def lock(self, *_):
        self.close()
        subprocess.Popen([str(LOCK_SCRIPT)], start_new_session=True)

    def power(self, *_):
        self.close()
        subprocess.Popen([sys.executable, str(POWER_MENU)], start_new_session=True)

    def refresh(self):
        if self.refreshing:
            self.refresh_pending = True
            return True
        self.refreshing = True
        threading.Thread(target=self.collect, daemon=True).start()
        return True

    def collect(self):
        try:
            snapshot = collect_state()
        except Exception:
            snapshot = None
        GLib.idle_add(self.apply_state, snapshot)

    def apply_state(self, snapshot):
        self.refreshing = False
        if snapshot is None:
            return False
        self.updating = True
        for target, button, scale, glyphs in (
            (SINK, self.volume_button, self.volume_scale, ("\U000f057e", "\U000f075f")),
            (SOURCE, self.mic_button, self.mic_scale, ("\U000f036c", "\U000f036d")),
        ):
            volume, muted = snapshot["volumes"][target]
            if volume is None:
                button.get_parent().hide()
                continue
            if not scale.has_grab():
                scale.set_value(min(100, volume))
            button.set_label(glyphs[1] if muted else glyphs[0])
            self.set_active(button, muted)
        self.updating = False
        icon, name = snapshot["network"]
        self.network_tile.icon_label.set_label(icon)
        self.network_tile.value_label.set_label(name)
        dnd = snapshot["dnd"]
        self.dnd_tile.value_label.set_label("On" if dnd else "Off")
        self.set_active(self.dnd_tile, dnd)
        state = snapshot["player"]
        if state:
            self.media_box.show()
            self.song.set_label(state["title"] or "Unknown title")
            self.artist.set_label(state["artist"] or "")
            self.play_button.set_label("\U000f03e4" if state["status"] == "Playing" else "\U000f040a")
            self.media_tile.value_label.set_label(state["status"])
            self.set_active(self.media_tile, state["status"] == "Playing")
            if state["art"] != self.art_url:
                self.art_url = state["art"]
                threading.Thread(target=self.load_art, args=(state["art"],), daemon=True).start()
        else:
            self.media_box.hide()
            self.media_tile.value_label.set_label("Nothing playing")
            self.set_active(self.media_tile, False)
        if self.refresh_pending:
            self.refresh_pending = False
            self.refresh()
        return False

    def load_art(self, url):
        path = cached_art(url)
        GLib.idle_add(self.show_art, url, path)

    def show_art(self, url, path):
        if url != self.art_url:
            return False
        pixbuf = None
        if path:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), ART_SIZE, ART_SIZE, True)
            except GLib.Error:
                pixbuf = None
        if pixbuf:
            self.art.set_from_pixbuf(pixbuf)
        else:
            self.art.set_from_icon_name("audio-x-generic", Gtk.IconSize.DIALOG)
        return False

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def close(self):
        if self.closing:
            return
        self.closing = True
        if not self.revealer.get_reveal_child():
            Gtk.main_quit()
            return
        self.revealer.set_reveal_child(False)
        GLib.timeout_add(190, lambda: Gtk.main_quit() or False)

    def run(self):
        self.window.show_all()
        self.apply_state(collect_state())
        GLib.idle_add(lambda: self.revealer.set_reveal_child(True) or False)
        GLib.timeout_add(REFRESH_MILLISECONDS, self.refresh)
        unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: self.close() or False)
        Gtk.main()


def close_running_panel():
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid() or not is_control_center(pid):
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


def main():
    if close_running_panel():
        return 0
    PID_FILE.write_text(str(os.getpid()))
    try:
        ControlCenter().run()
    finally:
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
