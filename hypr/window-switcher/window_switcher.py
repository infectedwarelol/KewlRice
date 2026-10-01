#!/usr/bin/env python3
import fcntl
import subprocess
import sys
import time

from desktop_icons import icon_names_by_window_class
from hyprland_ipc import list_windows, switch_to_window, switcher_menu_is_open
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
    last_row = len(windows) - 1

    if alt_released():
        switch_to_window(windows[min(tabs_pressed(), last_row)])
        return

    icons = icon_names_by_window_class()
    rows = "".join(
        f"{w['class']}   {w['title']}\0icon\x1f{icons.get(w['class'].lower(), w['class'].lower())}\n"
        for w in windows
    )
    start_row = min(tabs_pressed(), last_row)
    menu = subprocess.Popen(
        ["rofi", "-dmenu", "-i", "-p", "", "-format", "i", "-selected-row", str(start_row)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    menu.stdin.write(rows)
    menu.stdin.close()

    menu_ready = False
    enter_sent = False
    while menu.poll() is None:
        if not menu_ready and switcher_menu_is_open():
            menu_ready = True
            time.sleep(0.05)
            missed_tabs = min(tabs_pressed(), last_row) - start_row
            if missed_tabs > 0:
                subprocess.run(["wtype", *(["-k", "Down"] * missed_tabs)])
        if menu_ready and not enter_sent and alt_released():
            enter_sent = True
            if menu.poll() is None:
                subprocess.run(["wtype", "-k", "Return"])
        time.sleep(0.02)

    choice = menu.stdout.read().strip()
    if menu.returncode == 0 and choice.isdigit():
        switch_to_window(windows[int(choice)])


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
