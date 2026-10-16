#!/usr/bin/env python3
import fcntl
import filecmp
import functools
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
KEWLRICE_DIR = Path(os.environ.get("KEWLRICE_DIR") or CONFIG_DIR / "kewlrice")
THEMES_DIR = KEWLRICE_DIR / "themes"
TEMPLATES_DIR = KEWLRICE_DIR / "templates"
DEFAULT_SOUNDS_DIR = KEWLRICE_DIR / "sounds"
SOUNDS_DIR = CONFIG_DIR / "hypr" / "sounds"
LOGIN_SCREEN_DIR = Path("/var/lib/kewlrice-sddm")
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state") / "kewlrice"
STATE_FILE = STATE_DIR / "current-theme"
BACKUP_ROOT = CONFIG_DIR / "kewlrice-backup"
LOCK_FILE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "kewl-theme-switch.lock"
GTK_CSS_FILES = (CONFIG_DIR / "gtk-3.0" / "gtk.css", CONFIG_DIR / "gtk-4.0" / "gtk.css")
GTK_IMPORT = "@import 'kewlrice.css';"
DEFAULT_THEME = "default"
WALLPAPER_NAMES = ("wallpaper.png", "wallpaper.jpg", "wallpaper.jpeg", "wallpaper.webp")
WALLPAPER_SWAP_DELAY = 0.4
REQUIRED_KEYS = (
    "background", "foreground", "surface", "primary", "secondary", "accent", "urgent",
    "border_active", "border_inactive",
) + tuple(f"color{index}" for index in range(16))
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
STYLE_KEYS = {"style": re.compile(r"plain|ornate|neon|gothic|frost|hud|vine|constellation|celtic|flame|deco|synth|retro|ribbon"), "terminal_padding": re.compile(r"[0-9]{1,2}")}
STYLE_DEFAULTS = {"style": "plain", "terminal_padding": "0"}
WINDOW_FRAME = CONFIG_DIR / "hypr" / "window-frame" / "window_frame.py"
THEME_TRANSITION = CONFIG_DIR / "hypr" / "theme-switch" / "theme_transition.py"
TRANSITION_READY_SECONDS = 0.8
THEME_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+(?:\|[a-z0-9_]+)*)(?:\.(hex|rgb|ansi))?\s*\}\}")
USAGE = "usage: theme_switch.py <theme-name> | --menu | --restore | --list | --current"


class ThemeError(Exception):
    pass


def warn(message):
    print(f"theme-switch: {message}", file=sys.stderr)


def available_themes():
    if not THEMES_DIR.is_dir():
        return []
    return sorted(
        entry.name for entry in THEMES_DIR.iterdir()
        if entry.is_dir() and (entry / "palette").is_file() and THEME_NAME.fullmatch(entry.name)
    )


def current_theme():
    try:
        name = STATE_FILE.read_text().strip()
    except OSError:
        return None
    return name if THEME_NAME.fullmatch(name) else None


def load_palette(name):
    if not THEME_NAME.fullmatch(name):
        raise ThemeError(f"invalid theme name {name!r}")
    theme_dir = THEMES_DIR / name
    palette_file = theme_dir / "palette"
    if not palette_file.is_file():
        themes = ", ".join(available_themes()) or "none"
        raise ThemeError(f"theme {name!r} not found in {THEMES_DIR} (available: {themes})")
    palette = {}
    for line_number, line in enumerate(palette_file.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key:
            raise ThemeError(f"{palette_file}:{line_number}: expected key=value")
        if key in STYLE_KEYS:
            if not STYLE_KEYS[key].fullmatch(value):
                raise ThemeError(f"{palette_file}:{line_number}: {key} has an invalid value {value!r}")
        elif key != "wallpaper" and not HEX_COLOR.fullmatch(value):
            raise ThemeError(f"{palette_file}:{line_number}: {key} must be #rrggbb, got {value!r}")
        palette[key] = value if key == "wallpaper" else value.lower()
    for key, value in STYLE_DEFAULTS.items():
        palette.setdefault(key, value)
    missing = [key for key in REQUIRED_KEYS if key not in palette]
    if missing:
        raise ThemeError(f"{palette_file}: missing keys: {', '.join(missing)}")
    return theme_dir, palette


def find_wallpaper(theme_dir, palette):
    candidates = []
    if palette.get("wallpaper"):
        configured = Path(os.path.expandvars(os.path.expanduser(palette["wallpaper"])))
        candidates.append(configured if configured.is_absolute() else theme_dir / configured)
    candidates.extend(theme_dir / name for name in WALLPAPER_NAMES)
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def rgb(color):
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def format_color(color, style):
    if style == "hex":
        return color[1:]
    if style == "rgb":
        return ", ".join(str(channel) for channel in rgb(color))
    if style == "ansi":
        return ";".join(str(channel) for channel in rgb(color))
    return color


def render(text, palette, source, wallpaper=""):
    def substitute(match):
        for key in match.group(1).split("|"):
            if key == "wallpaper":
                return wallpaper
            if key in palette:
                return format_color(palette[key], match.group(2))
        raise ThemeError(f"{source}: no palette value for {match.group(0)}")
    return PLACEHOLDER.sub(substitute, text)


def render_templates(palette, wallpaper=""):
    if not TEMPLATES_DIR.is_dir():
        raise ThemeError(f"templates folder {TEMPLATES_DIR} is missing, run the install steps again")
    outputs = {}
    for template in sorted(path for path in TEMPLATES_DIR.rglob("*") if path.is_file()):
        outputs[CONFIG_DIR / template.relative_to(TEMPLATES_DIR)] = render(template.read_text(), palette, template, wallpaper)
    if not outputs:
        raise ThemeError(f"no templates found in {TEMPLATES_DIR}")
    return outputs


def relative_luminance(color):
    def linear(channel):
        channel /= 255
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
    red, green, blue = (linear(channel) for channel in rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def check_contrast(palette):
    for key, minimum in (("foreground", 4.5), ("accent", 3.0)):
        ratio = contrast_ratio(palette[key], palette["background"])
        if ratio < minimum:
            warn(f"low contrast: {key} on background is {ratio:.1f}:1, aim for {minimum}:1")


def backup_once(paths):
    if STATE_FILE.exists():
        return
    existing = [path for path in paths if path.is_file()]
    if not existing:
        return
    backup_dir = BACKUP_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in existing:
        relative = path.relative_to(HOME) if path.is_relative_to(HOME) else path.relative_to(path.anchor)
        destination = backup_dir / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    print(f"theme-switch: backed up {len(existing)} files to {backup_dir}")


def write_if_changed(path, content):
    try:
        if path.read_text() == content:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.kewlrice-tmp")
    temporary.write_text(content)
    os.replace(temporary, path)
    return True


def gtk_css_with_import(path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        text = ""
    if GTK_IMPORT in text.splitlines():
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + GTK_IMPORT + "\n"


def write_theme(name, palette, wallpaper=None):
    outputs = render_templates({**palette, **login_colors(palette, wallpaper)}, str(wallpaper) if wallpaper else "")
    for css_file in GTK_CSS_FILES:
        if css_file.parent.is_dir():
            outputs.setdefault(css_file, gtk_css_with_import(css_file))
    backup_once(list(outputs))
    changed = [path for path, content in outputs.items() if write_if_changed(path, content)]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_if_changed(STATE_FILE, name + "\n")
    return changed


def mix_hex(first, second, amount):
    return "#" + "".join(f"{round(a + (b - a) * amount):02x}" for a, b in zip(rgb(first), rgb(second)))


def with_alpha(color, alpha):
    return color + f"{round(alpha * 255):02x}"


@functools.lru_cache(maxsize=4)
def wallpaper_is_dark(wallpaper, background):
    try:
        import cairo
        surface = cairo.ImageSurface.create_from_png(str(wallpaper))
        width, height, stride = surface.get_width(), surface.get_height(), surface.get_stride()
        data = surface.get_data()
        total = count = 0
        for row in range(0, height, max(1, height // 36)):
            for column in range(0, width, max(1, width // 64)):
                offset = row * stride + column * 4
                blue, green, red = data[offset], data[offset + 1], data[offset + 2]
                total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
                count += 1
        return total / count / 255 < 0.42
    except Exception:
        return relative_luminance(background) < 0.2


def login_colors(palette, wallpaper):
    if wallpaper and wallpaper_is_dark(wallpaper, palette["background"]):
        text = mix_hex(palette["foreground"], "#ffffff", 0.2)
        base = mix_hex(palette["background"], "#000000", 0.25)
        return {
            "login_text": text,
            "login_muted": mix_hex(text, palette["background"], 0.35),
            "login_card": with_alpha(base, 0.68),
            "login_frame": with_alpha(base, 0.3),
            "login_frame_border": with_alpha("#ffffff", 0.18),
            "login_card_border": with_alpha("#ffffff", 0.14),
            "login_glass": with_alpha(mix_hex(base, palette["foreground"], 0.12), 0.7),
            "login_field": with_alpha(base, 0.75),
        }
    text = mix_hex(palette["background"], "#000000", 0.45)
    return {
        "login_text": text,
        "login_muted": mix_hex(text, palette["foreground"], 0.3),
        "login_card": with_alpha(mix_hex(palette["foreground"], "#ffffff", 0.6), 0.62),
        "login_frame": with_alpha("#ffffff", 0.16),
        "login_frame_border": with_alpha("#ffffff", 0.4),
        "login_card_border": with_alpha("#ffffff", 0.45),
        "login_glass": with_alpha("#ffffff", 0.45),
        "login_field": with_alpha("#ffffff", 0.6),
    }


def qml_color(color):
    color = color.lstrip("#")
    return "#" + (color[6:8] + color[:6] if len(color) == 8 else color)


def sync_login_screen(palette, wallpaper):
    if not LOGIN_SCREEN_DIR.is_dir() or not os.access(LOGIN_SCREEN_DIR, os.W_OK):
        return []
    login = login_colors(palette, wallpaper)
    text = login["login_text"]
    theme = {
        "text": text,
        "muted": login["login_muted"],
        "accent": palette["primary"],
        "accentLight": palette["accent"],
        "error": palette["urgent"],
        "card": qml_color(login["login_card"]),
        "cardBorder": qml_color(login["login_card_border"]),
        "frame": qml_color(login["login_frame"]),
        "frameBorder": qml_color(login["login_frame_border"]),
        "glass": qml_color(login["login_glass"]),
        "field": qml_color(login["login_field"]),
        "swatches": [
            palette["background"], mix_hex(palette["background"], palette["primary"], 0.5), palette["primary"],
            palette["secondary"], mix_hex(palette["primary"], palette["accent"], 0.5), palette["accent"],
            mix_hex(palette["accent"], "#ffffff", 0.5), palette["foreground"],
        ],
        "blobs": [palette["primary"], palette["accent"], palette["secondary"]],
        "background": "",
    }
    try:
        if wallpaper:
            target = LOGIN_SCREEN_DIR / ("background" + wallpaper.suffix.lower())
            if not target.is_file() or not filecmp.cmp(wallpaper, target, shallow=False):
                temporary = target.with_name(f".{target.name}.kewlrice-tmp")
                shutil.copyfile(wallpaper, temporary)
                os.replace(temporary, target)
            theme["background"] = str(target)
        write_if_changed(LOGIN_SCREEN_DIR / "theme.json", json.dumps(theme, indent=2) + "\n")
    except OSError as error:
        return [f"login screen: {error}"]
    return []


def sync_sounds(theme_dir):
    theme_sounds = theme_dir / "sounds"
    try:
        if not DEFAULT_SOUNDS_DIR.is_dir():
            if not theme_sounds.is_dir() or not SOUNDS_DIR.is_dir():
                return []
            shutil.copytree(SOUNDS_DIR, DEFAULT_SOUNDS_DIR)
        sources = {path.relative_to(DEFAULT_SOUNDS_DIR): path for path in DEFAULT_SOUNDS_DIR.rglob("*") if path.is_file()}
        if theme_sounds.is_dir():
            sources.update({path.relative_to(theme_sounds): path for path in theme_sounds.rglob("*") if path.is_file()})
        for relative, source in sorted(sources.items()):
            target = SOUNDS_DIR / relative
            if target.is_file() and filecmp.cmp(source, target, shallow=False):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.kewlrice-tmp")
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
    except OSError as error:
        return [f"sounds: {error}"]
    return []


def is_running(process_name):
    return subprocess.run(["pgrep", "-x", process_name], stdout=subprocess.DEVNULL).returncode == 0


def run_quietly(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    if result.returncode != 0:
        return (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
    return None


def reload_apps(palette):
    failures = []
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        error = run_quietly(["hyprctl", "reload"])
        if error:
            failures.append(f"hyprctl reload: {error}")
        else:
            config_errors = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True).stdout.strip()
            if config_errors and config_errors.lower() != "no errors":
                failures.append(f"hyprland config errors: {config_errors}")
    for process_name, signal_name in (("waybar", "USR2"), ("kitty", "USR1")):
        if is_running(process_name):
            error = run_quietly(["pkill", f"-{signal_name}", "-x", process_name])
            if error:
                failures.append(f"{process_name} reload: {error}")
    if is_running("mako") and shutil.which("makoctl"):
        error = run_quietly(["makoctl", "reload"])
        if error:
            failures.append(f"makoctl reload: {error}")
    if shutil.which("gsettings"):
        scheme = "prefer-dark" if relative_luminance(palette["background"]) < 0.18 else "prefer-light"
        current = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], capture_output=True, text=True
        ).stdout.strip().strip("'")
        if current and current != scheme:
            error = run_quietly(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", scheme])
            if error:
                failures.append(f"gsettings: {error}")
    return failures


def swaybg_processes():
    processes = {}
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            arguments = (proc_dir / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if arguments and os.path.basename(arguments[0]) == b"swaybg":
            processes[int(proc_dir.name)] = [argument.decode(errors="replace") for argument in arguments if argument]
    return processes


def start_theme_transition(palette):
    if not THEME_TRANSITION.is_file() or not os.environ.get("WAYLAND_DISPLAY"):
        return None
    try:
        transition = subprocess.Popen(
            [sys.executable, str(THEME_TRANSITION), palette["accent"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        return None
    ready, _, _ = select.select([transition.stdout], [], [], TRANSITION_READY_SECONDS)
    if ready:
        transition.stdout.readline()
    transition.stdout.close()
    return transition


def finish_theme_transition(transition):
    if transition is None:
        return
    try:
        transition.stdin.write(b"go\n")
        transition.stdin.close()
    except (BrokenPipeError, OSError):
        pass


def set_wallpaper(wallpaper, palette):
    if not os.environ.get("WAYLAND_DISPLAY"):
        return []
    if not shutil.which("swaybg"):
        return ["swaybg is not installed, wallpaper not changed"]
    command = ["swaybg", "-m", "fill", "-i", str(wallpaper)] if wallpaper else ["swaybg", "-c", palette["background"]]
    running = swaybg_processes()
    if any(arguments[1:] == command[1:] for arguments in running.values()) and len(running) == 1:
        return []
    try:
        new_process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        return [f"swaybg: {error}"]
    time.sleep(WALLPAPER_SWAP_DELAY)
    if new_process.poll() is not None:
        return [f"swaybg exited with code {new_process.returncode} for {' '.join(command[1:])}"]
    for pid in running:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return []


def window_frame_processes():
    running = []
    marker = str(WINDOW_FRAME).encode()
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            arguments = (proc_dir / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if len(arguments) > 1 and os.path.basename(arguments[0]).startswith(b"python") and arguments[1] == marker:
            running.append(int(proc_dir.name))
    return running


def sync_window_frame(palette):
    running = window_frame_processes()
    if palette["style"] == "plain":
        for pid in running:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return []
    if running or not os.environ.get("WAYLAND_DISPLAY") or not WINDOW_FRAME.is_file():
        return []
    try:
        subprocess.Popen(
            [sys.executable, str(WINDOW_FRAME)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as error:
        return [f"window frame: {error}"]
    return []


def start_globe_build(name):
    builder = CONFIG_DIR / "hypr" / "window-switcher" / "globe_builder.py"
    if not builder.is_file():
        return
    try:
        subprocess.Popen(
            ["sh", "-c", 'sleep 1.5; exec "$0" "$1" "$2"', sys.executable, str(builder), name],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        pass


def apply_theme(name):
    theme_dir, palette = load_palette(name)
    wallpaper = find_wallpaper(theme_dir, palette)
    transition = start_theme_transition(palette)
    changed = write_theme(name, palette, wallpaper)
    check_contrast(palette)
    if wallpaper is None:
        warn(f"theme {name!r} has no wallpaper file, using a plain {palette['background']} background")
    failures = reload_apps(palette) if changed else []
    failures += sync_sounds(theme_dir)
    failures += sync_login_screen(palette, wallpaper)
    failures += set_wallpaper(wallpaper, palette)
    failures += sync_window_frame(palette)
    finish_theme_transition(transition)
    start_globe_build(name)
    return failures


def restore_theme():
    name = current_theme() or DEFAULT_THEME
    try:
        theme_dir, palette = load_palette(name)
    except ThemeError as error:
        if name == DEFAULT_THEME:
            raise
        warn(f"{error}, falling back to {DEFAULT_THEME!r}")
        name = DEFAULT_THEME
        theme_dir, palette = load_palette(name)
    wallpaper = find_wallpaper(theme_dir, palette)
    write_theme(name, palette, wallpaper)
    return (
        sync_sounds(theme_dir) + sync_login_screen(palette, wallpaper) + set_wallpaper(wallpaper, palette)
        + sync_window_frame(palette)
    )


def notify(message):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Theme switch", "Theme switch failed", message], check=False)


def send_to_ui_daemon(message):
    import socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.3)
            connection.connect(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "kewl-ui.sock"))
            connection.sendall(message.encode())
        return True
    except OSError:
        return False


def pick_theme():
    from theme_picker import pick_theme as show_picker

    entries = []
    for name in available_themes():
        try:
            theme_dir, palette = load_palette(name)
        except ThemeError as error:
            warn(str(error))
            continue
        entries.append({"name": name, "palette": palette, "wallpaper": find_wallpaper(theme_dir, palette)})
    if not entries:
        raise ThemeError(f"no themes found in {THEMES_DIR}")
    return show_picker(entries, current_theme())


def main(arguments):
    if len(arguments) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    option = arguments[0]
    if option == "--list":
        print("\n".join(available_themes()))
        return 0
    if option == "--current":
        print(current_theme() or "")
        return 0
    if option == "--menu" and send_to_ui_daemon("menu"):
        return 0
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        if option == "--menu":
            try:
                name = pick_theme()
            except ThemeError as error:
                warn(str(error))
                notify(str(error))
                return 1
            if name is None:
                return 0
        else:
            name = None
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if option == "--restore":
                failures = restore_theme()
            elif name is not None:
                failures = apply_theme(name)
            elif option.startswith("-"):
                print(USAGE, file=sys.stderr)
                return 2
            else:
                failures = apply_theme(option)
                name = option
        except (ThemeError, OSError) as error:
            warn(str(error))
            if option == "--menu":
                notify(str(error))
            return 1
    for failure in failures:
        warn(failure)
    if failures:
        if option == "--menu":
            notify("\n".join(failures))
        return 1
    if name is not None:
        print(f"theme-switch: applied {name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
