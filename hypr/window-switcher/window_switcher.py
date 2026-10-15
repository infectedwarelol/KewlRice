#!/usr/bin/env python3
import fcntl
import sys
import time

from desktop_icons import icon_names_by_window_class
from hyprland_ipc import list_windows, switch_to_window
from keypress_tracker import (
    LOCK_FILE,
    alt_released_after,
    clear_presses,
    presses_since,
    record_press,
)

STALE_PRESS_SECONDS = 2


def print_window_order():
    for window in list_windows():
        print(window["focusHistoryID"], window["class"], "|", window["title"], "|", window["workspace"]["name"])


def run_switcher(since):
    def tabs_pressed():
        return max(1, len(presses_since(since)))

    def alt_released():
        return alt_released_after(max(presses_since(since) or [since]))

    windows = list_windows()
    if len(windows) < 2:
        return

    if alt_released():
        switch_to_window(windows[tabs_pressed() % len(windows)])
        return

    from planet_view import choose_window

    choice = choose_window(windows, icon_names_by_window_class(), tabs_pressed, alt_released)
    if choice is not None:
        switch_to_window(windows[choice])


def main():
    if "--list" in sys.argv:
        print_window_order()
        return

    pressed_at = float(sys.argv[1]) if len(sys.argv) > 1 else time.time()
    record_press(pressed_at)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    try:
        run_switcher(pressed_at - STALE_PRESS_SECONDS)
    finally:
        clear_presses()


if __name__ == "__main__":
    main()
