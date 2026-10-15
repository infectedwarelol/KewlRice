#!/usr/bin/env python3
import calendar
import datetime
import html
import json
import os
import random
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
LOCK_DIR = HOME / ".config" / "hypr" / "lock"
COLORS_FILE = LOCK_DIR / "colors.json"
LOCATION_FILE = LOCK_DIR / "weather-location"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "kewlrice"
WEATHER_CACHE = CACHE_DIR / "weather.json"
WEATHER_MAX_AGE = 1800
FALLBACK_COLORS = {"text": "#2e1a47", "muted": "#6b5a85", "accent": "#9b59ff", "accent_light": "#d090ff"}
WEATHER_ICONS = (
    ({113}, ""),
    ({116}, ""),
    ({119, 122}, ""),
    ({143, 248, 260}, ""),
    ({200, 386, 389, 392, 395}, ""),
    ({179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377}, ""),
)
RAIN_ICON = ""
TIPS = (
    "Tip: Super + Q opens a terminal",
    "Tip: Super + R opens the app launcher",
    "Tip: Super + A toggles the overview",
    "Tip: Alt + Tab spins the planet",
    "Tip: Super + Tab picks a theme",
    "Tip: Super + Esc opens the power menu",
    "Tip: pacman -Qdt lists orphaned packages",
    "Tip: paccache -r keeps only the last 3 versions of each package",
    "Tip: journalctl -b -p err shows this boot's errors",
    "Tip: systemd-analyze blame shows what slows down your boot",
    "Tip: checkupdates shows pending updates without syncing the database",
    "Tip: read the Arch news before big updates",
)


def colors():
    try:
        return {**FALLBACK_COLORS, **json.loads(COLORS_FILE.read_text())}
    except (OSError, ValueError):
        return dict(FALLBACK_COLORS)


def span(text, color, points=None, bold=False, family=None):
    attributes = [f'foreground="{color}"']
    if points:
        attributes.append(f'size="{int(points * 1024)}"')
    if bold:
        attributes.append('weight="bold"')
    if family:
        attributes.append(f'font_family="{family}"')
    return f"<span {' '.join(attributes)}>{html.escape(str(text))}</span>"


def weather_data():
    try:
        if WEATHER_CACHE.is_file() and time.time() - WEATHER_CACHE.stat().st_mtime < WEATHER_MAX_AGE:
            return json.loads(WEATHER_CACHE.read_text())
    except (OSError, ValueError):
        pass
    try:
        location = "".join(LOCATION_FILE.read_text().split())
    except OSError:
        location = ""
    try:
        with urllib.request.urlopen(f"https://wttr.in/{location}?format=j1", timeout=5) as response:
            data = json.loads(response.read())
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        WEATHER_CACHE.write_text(json.dumps(data))
        return data
    except (OSError, ValueError):
        try:
            return json.loads(WEATHER_CACHE.read_text())
        except (OSError, ValueError):
            return None


def weather_icon(code):
    code = int(code or 0)
    for codes, icon in WEATHER_ICONS:
        if code in codes:
            return icon
    return RAIN_ICON


def weather_now(palette):
    data = weather_data()
    if not data:
        return span("Weather unavailable", palette["muted"], 12)
    current = data["current_condition"][0]
    icon = weather_icon(current.get("weatherCode"))
    description = current["weatherDesc"][0]["value"]
    return (
        span(icon, palette["accent"], 42, family="JetBrainsMono Nerd Font") + "    "
        + span(f"{current['temp_C']}°C", palette["text"], 28, bold=True) + "\n"
        + span(description, palette["text"], 14) + "\n"
        + span(f"Feels like {current['FeelsLikeC']}°  ·  Humidity {current['humidity']}%", palette["muted"], 10)
    )


def forecast(palette, index):
    data = weather_data()
    if not data or index >= len(data.get("weather", [])):
        return ""
    day = data["weather"][index]
    name = datetime.date.fromisoformat(day["date"]).strftime("%a")
    code = day["hourly"][len(day["hourly"]) // 2]["weatherCode"] if day.get("hourly") else 113
    return (
        span(name, palette["muted"], 10) + "\n"
        + span(weather_icon(code), palette["accent"], 26, family="JetBrainsMono Nerd Font") + "\n"
        + span(f"{day['maxtempC']}° / {day['mintempC']}°", palette["text"], 11, bold=True)
    )


def run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def uptime_text():
    seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    hours, minutes = seconds // 3600, seconds % 3600 // 60
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def system_info(palette):
    os_name = "Linux"
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    packages = len(run(["pacman", "-Qq"]).splitlines())
    rows = (
        ("OS", os_name), ("Kernel", os.uname().release), ("Uptime", uptime_text()),
        ("Packages", str(packages)), ("Shell", Path(os.environ.get("SHELL", "bash")).name), ("WM", "Hyprland"),
    )
    return "\n".join(span(f"{key}: ", palette["accent"], 11, bold=True) + span(value, palette["text"], 11) for key, value in rows)


def month_calendar(palette):
    today = datetime.date.today()
    lines = [span(today.strftime("%B %Y"), palette["text"], 11, bold=True)]
    lines.append(" ".join(span(day, palette["accent"], 10, bold=True) for day in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")))
    for week in calendar.Calendar().monthdayscalendar(today.year, today.month):
        cells = []
        for day in week:
            if day == 0:
                cells.append("  ")
            elif day == today.day:
                cells.append(f'<span background="{palette["accent"]}" foreground="#ffffff" weight="bold" size="{10 * 1024}">{day:>2}</span>')
            else:
                cells.append(span(f"{day:>2}", palette["text"], 10))
        lines.append(" ".join(cells))
    return "\n".join(lines)


def cpu_usage():
    def sample():
        values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return values[3] + values[4], sum(values)
    idle_before, total_before = sample()
    time.sleep(0.25)
    idle_after, total_after = sample()
    total = total_after - total_before
    return 0 if total <= 0 else round(100 * (1 - (idle_after - idle_before) / total))


def cpu_temperature():
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (hwmon / "name").read_text().strip() in ("coretemp", "k10temp", "zenpower"):
                return round(int((hwmon / "temp1_input").read_text()) / 1000)
        except (OSError, ValueError):
            continue
    return None


def memory_usage():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0])
    return round(100 * (1 - info["MemAvailable"] / info["MemTotal"]))


def stat(palette, name):
    if name == "cpu":
        icon, value, label = "\U000f0ee0", f"{cpu_usage()}%", "CPU"
    elif name == "temp":
        temperature = cpu_temperature()
        icon, value, label = "\U000f050f", "—" if temperature is None else f"{temperature}°C", "Temperature"
    elif name == "memory":
        icon, value, label = "\U000f035b", f"{memory_usage()}%", "Memory"
    else:
        icon, value, label = "\U000f0954", uptime_text(), "Uptime"
    return (
        span(icon, palette["accent"], 30, family="JetBrainsMono Nerd Font") + "\n"
        + span(value, palette["text"], 22, bold=True) + "\n"
        + span(label, palette["muted"], 10)
    )


def greeting(palette):
    hour = datetime.datetime.now().hour
    text = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
    name = os.environ.get("USER", "").capitalize()
    return span(f"{text}, {name}" if name else text, palette["text"], 18)


def media(palette):
    status = run(["playerctl", "status"])
    if status not in ("Playing", "Paused"):
        return ""
    title = run(["playerctl", "metadata", "title"])
    artist = run(["playerctl", "metadata", "artist"])
    if not title:
        return ""
    icon = "\U000f075a" if status == "Playing" else "\U000f03e4"
    text = f"{title}  ·  {artist}" if artist else title
    return span(icon, palette["accent"], 12, family="JetBrainsMono Nerd Font") + "  " + span(text, palette["text"], 12)


def tip(palette):
    return f'<i>{span(random.Random(datetime.date.today().toordinal()).choice(TIPS), palette["text"], 12)}</i>'


def main(arguments):
    palette = colors()
    command = arguments[0] if arguments else ""
    if command == "weather":
        output = weather_now(palette)
    elif command == "forecast":
        output = forecast(palette, int(arguments[1]) if len(arguments) > 1 else 0)
    elif command == "system":
        output = system_info(palette)
    elif command == "calendar":
        output = month_calendar(palette)
    elif command == "stat":
        output = stat(palette, arguments[1] if len(arguments) > 1 else "cpu")
    elif command == "greeting":
        output = greeting(palette)
    elif command == "media":
        output = media(palette)
    elif command == "tip":
        output = tip(palette)
    else:
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
