#!/usr/bin/env python3
import ctypes
import fcntl
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
THEME_SWITCH_DIR = HERE.parent / "theme-switch"
POPUPS_DIR = HERE.parent / "popups"
sys.path.insert(0, str(POPUPS_DIR))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(THEME_SWITCH_DIR))

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

import planet_view
import popups
import theme_picker
import theme_switch
from keypress_tracker import LOCK_FILE, clear_presses
from window_switcher import STALE_PRESS_SECONDS, run_switcher

SOURCE_FILES = [path for directory in (HERE, THEME_SWITCH_DIR, POPUPS_DIR) for path in directory.glob("*.py")]
TRIM_DELAY_MS = 500
SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "kewl-ui.sock")
DAEMON_LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "kewl-ui.lock")


def release_memory():
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
    return False


def source_signature():
    signature = []
    for path in SOURCE_FILES:
        try:
            signature.append(path.stat().st_mtime_ns)
        except OSError:
            signature.append(None)
    return signature


class UiDaemon:
    def __init__(self):
        self.busy = None
        self.popups = popups.PopupHost()
        self.signature = source_signature()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o600)
        self.server.listen(8)
        GLib.io_add_watch(self.server.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self.on_request)

    def on_request(self, _fd, _condition):
        connection, _ = self.server.accept()
        with connection:
            connection.settimeout(0.5)
            try:
                message = connection.recv(256).decode(errors="replace").split()
            except OSError:
                return True
        if not message:
            return True
        if not self.busy and source_signature() != self.signature:
            self.server.close()
            os.unlink(SOCKET_PATH)
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *message])
        if message[0] == "alttab" and len(message) == 2:
            GLib.idle_add(self.alttab, message[1])
        elif message[0] == "menu":
            GLib.idle_add(self.menu)
        elif message[0] == "popup" and len(message) == 2:
            GLib.idle_add(self.popups.toggle, message[1])
        return True

    def alttab(self, pressed_at):
        if self.busy:
            return False
        try:
            since = float(pressed_at) - STALE_PRESS_SECONDS
        except ValueError:
            return False
        with open(LOCK_FILE, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            self.busy = "alttab"
            try:
                run_switcher(since)
            finally:
                clear_presses()
                self.busy = None
        GLib.timeout_add(TRIM_DELAY_MS, release_memory)
        return False

    def menu(self):
        if self.busy == "menu":
            os.kill(os.getpid(), signal.SIGTERM)
            return False
        if self.busy:
            return False
        self.busy = "menu"
        try:
            name = theme_switch.pick_theme()
        except theme_switch.ThemeError as error:
            theme_switch.notify(str(error))
            name = None
        finally:
            self.busy = None
        GLib.timeout_add(TRIM_DELAY_MS, release_memory)
        if name:
            process = subprocess.Popen(
                [sys.executable, str(THEME_SWITCH_DIR / "theme_switch.py"), name], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            GLib.child_watch_add(GLib.PRIORITY_DEFAULT, process.pid, lambda *_: None)
        return False


def main():
    lock = open(DAEMON_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    daemon = UiDaemon()
    replay = sys.argv[1:]
    if replay and replay[0] == "alttab" and len(replay) == 2:
        GLib.idle_add(daemon.alttab, replay[1])
    elif replay and replay[0] == "menu":
        GLib.idle_add(daemon.menu)
    elif replay and replay[0] == "popup" and len(replay) == 2:
        GLib.idle_add(daemon.popups.toggle, replay[1])
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
