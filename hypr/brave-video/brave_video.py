#!/usr/bin/env python3
import fcntl
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time

BRAVE_CLASS = "brave-browser"
DISCORD_CLASS = "discord"
VIDEO_SITES = ("YouTube",)
SOLID = "1.0"
SEE_THROUGH = "0.8"
PROPS = ("opacity", "opacity_inactive", "opacity_fullscreen")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK_FILE = os.path.join(RUNTIME, "brave-video.lock")


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def watched_windows():
    try:
        return [c for c in json.loads(hyprctl("clients", "-j")) if c["class"] in (BRAVE_CLASS, DISCORD_CLASS)]
    except (json.JSONDecodeError, KeyError):
        return []


def process_name(pid):
    try:
        with open(f"/proc/{pid}/comm") as comm:
            return comm.read().strip().lower()
    except (OSError, TypeError):
        return ""


def discord_audio_playing():
    try:
        output = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, timeout=5).stdout
        streams = json.loads(output or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    for stream in streams:
        if stream.get("corked", True):
            continue
        props = stream.get("properties") or {}
        binary = (props.get("application.process.binary") or "").lower()
        if "discord" in binary or "discord" in process_name(props.get("application.process.id")):
            return True
    return False


def watch_discord(events, discord_open):
    playing = False
    while True:
        discord_open.wait()
        now = discord_audio_playing()
        if now != playing:
            playing = now
            events.put(("discord", playing))
        try:
            process = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            time.sleep(5)
            continue
        for line in process.stdout:
            if not discord_open.is_set():
                break
            if "sink-input" not in line:
                continue
            now = discord_audio_playing()
            if now != playing:
                playing = now
                events.put(("discord", playing))
        process.terminate()
        process.wait()
        if playing and not discord_open.is_set():
            playing = False
            events.put(("discord", playing))
        time.sleep(1)


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
        time.sleep(2)


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
                name, _, payload = line.partition(b">>")
                if name in (b"openwindow", b"closewindow", b"windowtitlev2"):
                    events.put((name.decode(), payload.decode(errors="replace")))


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)

    events = queue.Queue()
    discord_open = threading.Event()
    threading.Thread(target=watch_player, args=(events,), daemon=True).start()
    threading.Thread(target=watch_hyprland, args=(events,), daemon=True).start()
    threading.Thread(target=watch_discord, args=(events, discord_open), daemon=True).start()

    playing = False
    discord_playing = False
    applied = {}
    events.put(("start", ""))
    while True:
        source, value = events.get()
        if source == "player":
            playing = value == "Playing"
        elif source == "discord":
            discord_playing = value
        elif source == "openwindow":
            if value.split(",", 3)[2:3] not in ([BRAVE_CLASS], [DISCORD_CLASS]):
                continue
        elif source in ("closewindow", "windowtitlev2"):
            if "0x" + value.split(",", 1)[0] not in applied:
                continue
        windows = watched_windows()
        if any(window["class"] == DISCORD_CLASS for window in windows):
            discord_open.set()
        else:
            discord_open.clear()
        for window in windows:
            if window["class"] == DISCORD_CLASS:
                solid = discord_playing
            else:
                solid = playing or any(site in window["title"] for site in VIDEO_SITES)
            wanted = SOLID if solid else SEE_THROUGH
            if applied.get(window["address"]) != wanted:
                set_opacity(window["address"], wanted)
                applied[window["address"]] = wanted
        alive = {w["address"] for w in windows}
        applied = {a: v for a, v in applied.items() if a in alive}


if __name__ == "__main__":
    main()
