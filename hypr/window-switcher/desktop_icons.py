import glob
import json
import os

APPLICATION_DIRS = [
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
]
CACHE_FILE = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "kewlrice", "desktop-icons.json"
)


def directories_signature():
    signature = []
    for directory in APPLICATION_DIRS:
        try:
            signature.append([directory, os.stat(directory).st_mtime_ns])
        except OSError:
            signature.append([directory, None])
    return signature


def scan_desktop_files():
    icons = {}
    for directory in APPLICATION_DIRS:
        for path in glob.glob(os.path.join(directory, "*.desktop")):
            try:
                with open(path, encoding="utf-8", errors="ignore") as desktop_file:
                    lines = desktop_file.read().splitlines()
            except OSError:
                continue
            icon = next((line[5:].strip() for line in lines if line.startswith("Icon=")), None)
            if not icon:
                continue
            icons.setdefault(os.path.basename(path)[: -len(".desktop")].lower(), icon)
            for line in lines:
                if line.startswith("StartupWMClass="):
                    icons.setdefault(line[15:].strip().lower(), icon)
    return icons


def icon_names_by_window_class():
    signature = directories_signature()
    try:
        with open(CACHE_FILE, encoding="utf-8") as cache_file:
            cached = json.load(cache_file)
        if cached.get("signature") == signature and isinstance(cached.get("icons"), dict):
            return cached["icons"]
    except (OSError, ValueError, AttributeError):
        pass
    icons = scan_desktop_files()
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        temporary = f"{CACHE_FILE}.{os.getpid()}"
        with open(temporary, "w", encoding="utf-8") as cache_file:
            json.dump({"signature": signature, "icons": icons}, cache_file)
        os.replace(temporary, CACHE_FILE)
    except OSError:
        pass
    return icons
