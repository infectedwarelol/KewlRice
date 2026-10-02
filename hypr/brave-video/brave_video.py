#!/usr/bin/env python3
import fcntl
import json
import os
import queue
import socket
import subprocess
import sys
import threading

BRAVE_CLASS = "brave-browser"
VIDEO_SITES = ("YouTube",)
SOLID = "1.0"
SEE_THROUGH = "0.8"
PROPS = ("opacity", "opacity_inactive", "opacity_fullscreen")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK_FILE = os.path.join(RUNTIME, "brave-video.lock")


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def brave_windows():
    try:
        return [c for c in json.loads(hyprctl("clients", "-j")) if c["class"] == BRAVE_CLASS]
    except (json.JSONDecodeError, KeyError):
        return []


def set_opacity(address, value):
    for prop in PROPS:
        hyprctl(
            "dispatch",
            f'hl.dsp.window.set_prop({{ window = "address:{address}", prop = "{prop}", value = "{value}" }})',
        )


def watch_player(events):
    command = ["playerctl", "--player=brave", "--follow", "status"]
    while True:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in process.stdout:
            events.put(("player", line.strip()))
        process.wait()
        events.put(("player", "Stopped"))
        threading.Event().wait(2)


def watch_hyprland(events):
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    path = os.path.join(RUNTIME, "hypr", signature, ".socket2.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(path)
        buffer = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                os._exit(0)
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                name = line.split(b">>", 1)[0]
                if name in (b"openwindow", b"windowtitlev2", b"windowtitle"):
                    events.put(("hyprland", name.decode()))


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)

    events = queue.Queue()
    threading.Thread(target=watch_player, args=(events,), daemon=True).start()
    threading.Thread(target=watch_hyprland, args=(events,), daemon=True).start()

    playing = False
    applied = {}
    events.put(("start", ""))
    while True:
        source, value = events.get()
        if source == "player":
            playing = value == "Playing"
        windows = brave_windows()
        for window in windows:
            solid = playing or any(site in window["title"] for site in VIDEO_SITES)
            wanted = SOLID if solid else SEE_THROUGH
            if applied.get(window["address"]) != wanted:
                set_opacity(window["address"], wanted)
                applied[window["address"]] = wanted
        alive = {w["address"] for w in windows}
        applied = {a: v for a, v in applied.items() if a in alive}


if __name__ == "__main__":
    main()
