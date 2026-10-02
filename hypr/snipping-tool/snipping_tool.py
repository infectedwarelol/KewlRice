#!/usr/bin/env python3
import fcntl
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

GLib.set_prgname("snipping-tool")

from screen_capture import capture_monitor, focused_monitor, visible_windows
from snip_editor import SnipEditor
from snip_overlay import SnipOverlay

LOCK_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "snipping-tool-snip.lock")
QUIET_OPEN_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "snipping-tool-quiet-open")


def load_theme():
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-application-prefer-dark-theme", True)
    settings.set_property("gtk-icon-theme-name", "breeze-dark")
    provider = Gtk.CssProvider()
    provider.load_from_path(os.path.join(HERE, "theme.css"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )


def skip_next_open_sound():
    open(QUIET_OPEN_FILE, "w").close()


def take_snip(on_result, delay=0.0):
    def capture():
        monitor = focused_monitor()
        screenshot = capture_monitor(monitor)
        SnipOverlay(screenshot, monitor, visible_windows(monitor), on_result)
        return False

    GLib.timeout_add(int(delay * 1000), capture)


class SnipApp:
    def __init__(self):
        self.editor = None

    def open_editor(self, pixbuf=None):
        if not self.editor:
            self.editor = SnipEditor(on_new=self.new_snip)
            self.editor.connect("destroy", Gtk.main_quit)
        if pixbuf:
            self.editor.load(pixbuf)
        self.editor.present()

    def new_snip(self, delay):
        self.editor.hide()
        take_snip(self.snip_done, delay + 0.3)

    def snip_done(self, pixbuf):
        if pixbuf:
            self.editor.load(pixbuf)
        skip_next_open_sound()
        self.editor.show()
        self.editor.present()


def quick_snip():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    result = {}

    def done(pixbuf):
        result["pixbuf"] = pixbuf
        Gtk.main_quit()

    take_snip(done, 0)
    Gtk.main()
    pixbuf = result.get("pixbuf")
    if not pixbuf:
        return
    lock.close()
    app = SnipApp()
    skip_next_open_sound()
    app.open_editor(pixbuf)
    Gtk.main()


def main():
    load_theme()
    if "snip" in sys.argv[1:]:
        quick_snip()
        return
    app = SnipApp()
    app.open_editor()
    Gtk.main()


if __name__ == "__main__":
    main()
