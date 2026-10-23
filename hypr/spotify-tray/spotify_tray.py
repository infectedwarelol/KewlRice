#!/usr/bin/env python3
import fcntl
import json
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, GLib, Gtk

try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
    unix_signal_add = GLibUnix.signal_add
except (ValueError, ImportError):
    unix_signal_add = GLib.unix_signal_add

HIDDEN_WORKSPACE = "special:hidden"
SPOTIFY_CLASSES = {"spotify"}
ICON_NAME = "spotify-launcher"
POLL_INTERVAL_SECONDS = 2
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
ORIGIN_FILE = os.path.join(RUNTIME_DIR, "kewl-spotify-workspace")
LOCK_FILE = os.path.join(RUNTIME_DIR, "kewl-spotify-tray.lock")


def run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def hyprctl_json(*args):
    try:
        return json.loads(run("hyprctl", *args, "-j") or "null")
    except ValueError:
        return None


def dispatch(expression):
    run("hyprctl", "dispatch", expression)


def spotify_windows():
    clients = hyprctl_json("clients") or []
    return [client for client in clients if (client.get("class") or "").lower() in SPOTIFY_CLASSES]


def is_hidden(window):
    return window.get("workspace", {}).get("name") == HIDDEN_WORKSPACE


def origin_workspace():
    try:
        with open(ORIGIN_FILE, encoding="utf-8") as origin:
            name = origin.read().strip()
    except OSError:
        name = ""
    if name and not name.startswith("special:"):
        return name
    active = hyprctl_json("activeworkspace") or {}
    return active.get("name") or "1"


def hide_spotify():
    windows = [window for window in spotify_windows() if not is_hidden(window)]
    if not windows:
        return
    try:
        with open(ORIGIN_FILE, "w", encoding="utf-8") as origin:
            origin.write(windows[0]["workspace"]["name"])
    except (OSError, KeyError):
        pass
    for window in windows:
        dispatch(f'hl.dsp.window.move({{ workspace = "{HIDDEN_WORKSPACE}", window = "address:{window["address"]}", follow = false }})')


def unhide_spotify():
    windows = [window for window in spotify_windows() if is_hidden(window)]
    if not windows:
        return
    target = origin_workspace()
    for window in windows:
        dispatch(f'hl.dsp.window.move({{ workspace = "{target}", window = "address:{window["address"]}", follow = false }})')
    dispatch(f'hl.dsp.focus({{ window = "address:{windows[0]["address"]}" }})')
    try:
        os.remove(ORIGIN_FILE)
    except OSError:
        pass


def show_spotify():
    windows = spotify_windows()
    if not windows:
        return
    if any(is_hidden(window) for window in windows):
        unhide_spotify()
        return
    dispatch(f'hl.dsp.focus({{ window = "address:{windows[0]["address"]}" }})')


def close_spotify():
    for window in spotify_windows():
        dispatch(f'hl.dsp.window.close({{ window = "address:{window["address"]}" }})')


class SpotifyTray:
    def __init__(self):
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "kewl-spotify", ICON_NAME, AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_title("Spotify")
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.PASSIVE)

        menu = Gtk.Menu()
        self.show_item = self.add_item(menu, "Show Spotify", show_spotify)
        self.hide_item = self.add_item(menu, "Hide fully", hide_spotify)
        self.unhide_item = self.add_item(menu, "Unhide", unhide_spotify)
        menu.append(Gtk.SeparatorMenuItem())
        self.add_item(menu, "Close", close_spotify)
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_secondary_activate_target(self.show_item)

        self.refresh()
        GLib.timeout_add_seconds(POLL_INTERVAL_SECONDS, self.refresh)

    def add_item(self, menu, label, action):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _item: self.run_action(action))
        menu.append(item)
        return item

    def run_action(self, action):
        action()
        self.refresh()

    def refresh(self):
        windows = spotify_windows()
        hidden = bool(windows) and any(is_hidden(window) for window in windows)
        playing = bool(windows) and run("playerctl", "-p", "spotify", "status") == "Playing"

        self.hide_item.set_visible(bool(windows) and not hidden)
        self.unhide_item.set_visible(hidden)

        status = AyatanaAppIndicator3.IndicatorStatus
        self.indicator.set_status(status.ACTIVE if hidden or playing else status.PASSIVE)
        return True


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)

    SpotifyTray()
    unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
