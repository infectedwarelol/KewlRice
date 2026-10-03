#!/usr/bin/env python3
import math
import os
import re
import shutil
import subprocess
import sys
import time

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MIRROR = str.maketrans({"/": "\\", "\\": "/", "(": ")", ")": "(", "<": ">", ">": "<", "[": "]", "]": "["})
FRONT = "\x1b[1;36m"
SIDE = "\x1b[0;36m"
RESET = "\x1b[0m"
GAP = 4
TURNS = 2
DURATION = 2.5
MIN_INFO_WIDTH = 20
FPS = 40
SPIN_SOUND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spin.wav")


def fastfetch(*args):
    return subprocess.run(["fastfetch", "--pipe", "false", *args], capture_output=True, text=True).stdout


def visible_width(text):
    return len(ANSI.sub("", text))


def truncate(text, limit):
    out, visible, index = [], [], 0
    while index < len(text):
        match = ANSI.match(text, index)
        if match:
            out.append(match.group())
            index = match.end()
            continue
        if len(visible) == limit:
            if visible:
                out[visible[-1]] = "\u2026"
            break
        visible.append(len(out))
        out.append(text[index])
        index += 1
    return "".join(out)


def spun_line(line, width, cos_angle):
    center = (width - 1) / 2
    cells = [" "] * width
    for x, char in enumerate(line):
        if char == " ":
            continue
        position = round(center + (x - center) * cos_angle)
        if 0 <= position < width:
            cells[position] = char.translate(MIRROR) if cos_angle < 0 else char
    return "".join(cells)


def frame(logo, width, info, rows, cos_angle):
    color = FRONT if cos_angle > 0.35 else SIDE
    out = []
    for row in range(rows):
        left = spun_line(logo[row], width, cos_angle) if row < len(logo) else " " * width
        right = info[row] if row < len(info) else ""
        out.append(f"{color}{left}{RESET}{' ' * GAP}{right}{RESET}\x1b[K")
    return "\n".join(out)


def load_logo(*args):
    logo = [ANSI.sub("", line).rstrip() for line in fastfetch(*args, "--structure", " ").splitlines()]
    logo = [line for line in logo if line.strip()] or [""]
    width = max(len(line) for line in logo)
    return [line.ljust(width) for line in logo], width


def terminal_size():
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
        return size.columns, size.lines
    except OSError:
        return shutil.get_terminal_size()


def ease_out(t):
    return 1 - (1 - t) ** 3


def main():
    if not sys.stdout.isatty():
        os.execvp("fastfetch", ["fastfetch"])
    info = (sys.argv[1] if len(sys.argv) > 1 else fastfetch("--logo", "none")).splitlines()
    columns, lines = terminal_size()
    logo, width = load_logo()
    if columns < width or lines < len(logo) + 2:
        os.execvp("fastfetch", ["fastfetch"])
    rows = len(logo)

    sys.stdout.write("\x1b[?25l")
    first = True
    sound = None
    if os.path.exists(SPIN_SOUND):
        sound = subprocess.Popen(["pw-play", SPIN_SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        start = time.monotonic()
        while True:
            t = min(1.0, (time.monotonic() - start) / DURATION)
            angle = ease_out(t) * TURNS * 2 * math.pi
            if not first:
                sys.stdout.write(f"\x1b[{rows - 1}A\r")
            sys.stdout.write(frame(logo, width, [], rows, math.cos(angle)))
            sys.stdout.flush()
            first = False
            if t >= 1.0:
                break
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        pass
    finally:
        if sound and sound.poll() is None:
            sound.terminate()
        columns, _ = terminal_size()
        room = columns - width - GAP - 1
        beside = room >= MIN_INFO_WIDTH
        final_info = [truncate(line, room) for line in info] if beside else []
        if not first:
            sys.stdout.write(f"\x1b[{rows - 1}A\r")
        sys.stdout.write(frame(logo, width, final_info, max(rows, len(final_info)), 1.0))
        sys.stdout.write("\n\x1b[?25h")
        if not beside:
            sys.stdout.write("\n" + "\n".join(info) + RESET + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
