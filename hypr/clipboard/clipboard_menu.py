#!/usr/bin/env python3
import fcntl
import json
import os
import re
import subprocess
import sys
import time

THEME = os.path.expanduser("~/.config/rofi/clipboard.rasi")
THUMBNAIL_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "kewl-clipboard")
LOCK_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "kewl-clipboard.lock")
DATABASE_PATH = os.environ.get("KEWL_CLIPBOARD_DB")
MAX_ENTRIES = 50
PREVIEW_LENGTH = 90
THUMBNAIL_SIZE = 256
TERMINAL_CLASSES = {"kitty", "org.kde.konsole", "alacritty", "foot", "com.mitchellh.ghostty", "wezterm"}
IMAGE_PATTERN = re.compile(r"^\[\[ binary data .+? (\w+) (\d+)x(\d+) \]\]$")
EXIT_SELECTED = 0
EXIT_DELETE = 10
EXIT_CLEAR = 11


def cliphist(*arguments, data=None):
    command = ["cliphist"]
    if DATABASE_PATH:
        command += ["-db-path", DATABASE_PATH]
    return subprocess.run(command + list(arguments), input=data, capture_output=True)


def load_entries():
    output = cliphist("list").stdout.decode("utf-8", errors="replace")
    entries = []
    for line in output.splitlines()[:MAX_ENTRIES]:
        entry_id, _, preview = line.partition("\t")
        if entry_id:
            entries.append({"line": line, "id": entry_id, "preview": preview})
    return entries


def scaled_thumbnail(image):
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        loader = GdkPixbuf.PixbufLoader()
        loader.write(image)
        loader.close()
        pixbuf = loader.get_pixbuf()
        width, height = pixbuf.get_width(), pixbuf.get_height()
        scale = min(1.0, THUMBNAIL_SIZE / max(width, height))
        if scale < 1.0:
            pixbuf = pixbuf.scale_simple(max(1, round(width * scale)), max(1, round(height * scale)), GdkPixbuf.InterpType.BILINEAR)
        _, data = pixbuf.save_to_bufferv("png", [], [])
        return data
    except Exception:
        return image


def thumbnail_for(entry):
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    path = os.path.join(THUMBNAIL_DIR, f"{entry['id']}.thumb.png")
    if not os.path.exists(path):
        image = cliphist("decode", data=entry["line"].encode()).stdout
        if not image:
            return None
        temporary = f"{path}.{os.getpid()}"
        with open(temporary, "wb") as thumbnail:
            thumbnail.write(scaled_thumbnail(image))
        os.replace(temporary, path)
    return path


def remove_stale_thumbnails(entries):
    if not os.path.isdir(THUMBNAIL_DIR):
        return
    kept = {f"{entry['id']}.thumb.png" for entry in entries}
    for name in os.listdir(THUMBNAIL_DIR):
        if name not in kept:
            try:
                os.remove(os.path.join(THUMBNAIL_DIR, name))
            except OSError:
                pass


def menu_row(entry):
    image = IMAGE_PATTERN.match(entry["preview"].strip())
    if image:
        _, width, height = image.groups()
        thumbnail = thumbnail_for(entry)
        label = f"Image  {width} x {height}"
        return f"{label}\0icon\x1f{thumbnail}" if thumbnail else label, True
    text = " ".join(entry["preview"].split())
    if len(text) > PREVIEW_LENGTH:
        text = text[:PREVIEW_LENGTH - 1].rstrip() + "…"
    return text or "(blank)", False


def show_menu(entries, selected_row):
    rows, has_images = [], False
    for entry in entries:
        row, is_image = menu_row(entry)
        rows.append(row)
        has_images = has_images or is_image
    if not rows:
        rows.append("Copy something and it shows up here\0nonselectable\x1ftrue")
    command = [
        "rofi", "-dmenu", "-i", "-no-custom",
        "-theme", THEME,
        "-p", "",
        "-format", "i",
        "-selected-row", str(selected_row),
        "-kb-delete-entry", "",
        "-kb-remove-char-forward", "",
        "-kb-custom-1", "Delete",
        "-kb-custom-2", "shift+Delete",
        "-mesg", "Enter to paste    Del to remove    Shift+Del to clear all" if entries else "Nothing copied yet",
    ]
    if has_images:
        command.append("-show-icons")
    result = subprocess.run(command, input="\n".join(rows), capture_output=True, text=True)
    choice = result.stdout.strip()
    return result.returncode, int(choice) if choice.isdigit() else None


def paste_into_focused_window():
    time.sleep(0.15)
    window = json.loads(subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True).stdout or "{}")
    if not window.get("address"):
        return
    if window.get("class", "").lower() in TERMINAL_CLASSES:
        subprocess.run(["wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"])
    else:
        subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"])


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        subprocess.run(["pkill", "-x", "rofi"])
        return

    selected_row = 0
    while True:
        entries = load_entries()
        remove_stale_thumbnails(entries)
        exit_code, index = show_menu(entries, selected_row)
        if index is None or index >= len(entries):
            return
        entry = entries[index]
        if exit_code == EXIT_SELECTED:
            content = cliphist("decode", data=entry["line"].encode()).stdout
            subprocess.run(["wl-copy"], input=content)
            if "--no-paste" not in sys.argv:
                paste_into_focused_window()
            return
        if exit_code == EXIT_DELETE:
            cliphist("delete", data=entry["line"].encode())
            selected_row = max(0, min(index, len(entries) - 2))
            continue
        if exit_code == EXIT_CLEAR:
            cliphist("wipe")
            remove_stale_thumbnails([])
            selected_row = 0
            continue
        return


if __name__ == "__main__":
    main()
