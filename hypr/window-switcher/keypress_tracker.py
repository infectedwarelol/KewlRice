import os

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK_FILE = os.path.join(RUNTIME_DIR, "alttab.lock")
PRESSES_FILE = os.path.join(RUNTIME_DIR, "alttab-presses")
ALT_RELEASED_FILE = os.path.join(RUNTIME_DIR, "alttab-released")


def record_press(pressed_at):
    with open(PRESSES_FILE, "a") as presses:
        presses.write(f"{pressed_at}\n")


def clear_presses():
    open(PRESSES_FILE, "w").close()


def presses_since(since):
    try:
        times = [float(t) for t in open(PRESSES_FILE).read().split()]
    except (OSError, ValueError):
        return []
    return [t for t in times if t > since]


def alt_released_after(moment):
    try:
        return os.stat(ALT_RELEASED_FILE).st_mtime > moment
    except FileNotFoundError:
        return False
