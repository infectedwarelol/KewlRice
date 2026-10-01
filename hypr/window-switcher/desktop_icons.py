import glob
import os

APPLICATION_DIRS = [
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
]


def icon_names_by_window_class():
    icons = {}
    for directory in APPLICATION_DIRS:
        for path in glob.glob(os.path.join(directory, "*.desktop")):
            try:
                lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
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
