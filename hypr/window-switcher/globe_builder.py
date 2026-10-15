#!/usr/bin/env python3
import ctypes
import fcntl
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import cairo

BUILD_VERSION = 6
TEXTURE_WIDTH = 4096
TEXTURE_HEIGHT = 2048
RUNTIME_WIDTH = 2048
RUNTIME_HEIGHT = 1024
MASK_WIDTH = 1024
MASK_HEIGHT = 512
NETWORK_POINTS = 2200
NEIGHBOURS = 3
LINK_DEGREES = 6.5
COLOR_KEYS = ("background", "foreground", "primary", "accent")
CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kewlrice"
GEODATA_DIR = CACHE_ROOT / "geodata"
GLOBE_ROOT = CACHE_ROOT / "globe"
LAND_FILE = GEODATA_DIR / "ne_50m_land.geojson"
PLACES_FILE = GEODATA_DIR / "ne_50m_populated_places_simple.geojson"
THEME_SWITCH_DIR = Path(__file__).resolve().parent.parent / "theme-switch"
RENDERER_SOURCE = Path(__file__).resolve().parent / "globe_render.c"
WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[index:index + 2], 16) / 255 for index in (0, 2, 4))


def mix(first, second, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, second))


def cache_dir(colors):
    payload = json.dumps([BUILD_VERSION, RUNTIME_WIDTH, RUNTIME_HEIGHT, [colors[key].lower() for key in COLOR_KEYS]])
    return GLOBE_ROOT / hashlib.sha1(payload.encode()).hexdigest()[:16]


def texture_path(directory):
    return directory / "texture.argb"


def is_ready(directory):
    return (directory / "ready").is_file()


def geodata_available():
    return LAND_FILE.is_file() and PLACES_FILE.is_file()


def to_texture(lon, lat, width=TEXTURE_WIDTH, height=TEXTURE_HEIGHT):
    return (lon + 180) / 360 * width, (90 - lat) / 180 * height


def land_rings():
    rings = []
    for feature in json.loads(LAND_FILE.read_text())["features"]:
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            rings.extend(polygon)
    return rings


def cities():
    result = []
    for feature in json.loads(PLACES_FILE.read_text())["features"]:
        properties = feature["properties"]
        population = properties.get("pop_max") or 0
        result.append((properties["longitude"], properties["latitude"], population))
    return result


def trace(cr, ring, width, height):
    previous_x = None
    for lon, lat in ring:
        x, y = to_texture(lon, lat, width, height)
        if previous_x is None or abs(x - previous_x) > width / 2:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
        previous_x = x


def fill_rings(cr, rings, width, height):
    for shift in (-width, 0, width):
        for ring in rings:
            previous = None
            for lon, lat in ring:
                if previous is not None:
                    lon += round((previous - lon) / 360) * 360
                x, y = to_texture(lon, lat, width, height)
                if previous is None:
                    cr.move_to(x + shift, y)
                else:
                    cr.line_to(x + shift, y)
                previous = lon
            cr.close_path()
    cr.fill()


def land_mask(rings):
    surface = cairo.ImageSurface(cairo.FORMAT_A8, MASK_WIDTH, MASK_HEIGHT)
    cr = cairo.Context(surface)
    cr.set_fill_rule(cairo.FILL_RULE_WINDING)
    fill_rings(cr, rings, MASK_WIDTH, MASK_HEIGHT)
    surface.flush()
    return surface.get_data(), surface.get_stride()


def network_points(rings, places, rng):
    data, stride = land_mask(rings)
    points = [(lon, lat, population) for lon, lat, population in places]
    attempts = 0
    while len(points) < NETWORK_POINTS + len(places) and attempts < NETWORK_POINTS * 40:
        attempts += 1
        lat = math.degrees(math.asin(rng.uniform(-0.96, 0.98)))
        lon = rng.uniform(-180, 180)
        x, y = to_texture(lon, lat, MASK_WIDTH, MASK_HEIGHT)
        if data[min(MASK_HEIGHT - 1, int(y)) * stride + min(MASK_WIDTH - 1, int(x))] > 127:
            points.append((lon, lat, 0))
    return points


def angular_distance(first, second):
    dlon = (first[0] - second[0] + 540) % 360 - 180
    dlat = first[1] - second[1]
    return math.hypot(dlon * math.cos(math.radians((first[1] + second[1]) / 2)), dlat)


def network_links(points):
    cell = LINK_DEGREES
    buckets = {}
    for index, (lon, lat, _) in enumerate(points):
        buckets.setdefault((int((lon + 180) // cell), int((lat + 90) // cell)), []).append(index)
    columns = int(360 // cell) + 1
    links = set()
    for index, point in enumerate(points):
        bx, by = int((point[0] + 180) // cell), int((point[1] + 90) // cell)
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get(((bx + dx) % columns, by + dy), ()):
                    if other != index:
                        distance = angular_distance(point, points[other])
                        if distance <= LINK_DEGREES:
                            candidates.append((distance, other))
        for _, other in sorted(candidates)[:NEIGHBOURS]:
            links.add((min(index, other), max(index, other)))
    return links


def stroke_wrapped(cr, start, end):
    x1, y1 = to_texture(start[0], start[1])
    x2, y2 = to_texture(end[0], end[1])
    if abs(x2 - x1) > TEXTURE_WIDTH / 2:
        return
    cr.move_to(x1, y1)
    cr.line_to(x2, y2)


def build_texture(colors, path):
    background = hex_to_rgb(colors["background"])
    accent = hex_to_rgb(colors["accent"])
    foreground = hex_to_rgb(colors["foreground"])
    primary = hex_to_rgb(colors["primary"])
    line = mix(foreground, accent, 0.3)
    bright = mix(foreground, WHITE, 0.6)
    rng = random.Random(7)
    rings = land_rings()
    places = cities()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*mix(background, BLACK, 0.65))
    cr.paint()
    cr.set_fill_rule(cairo.FILL_RULE_WINDING)
    cr.set_source_rgba(*mix(primary, BLACK, 0.35), 0.55)
    fill_rings(cr, rings, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    points = network_points(rings, places, rng)
    cr.set_line_width(1.3)
    cr.set_source_rgba(*line, 0.34)
    for first, second in network_links(points):
        stroke_wrapped(cr, points[first], points[second])
    cr.stroke()
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    for width, color, alpha in ((14, accent, 0.06), (8, accent, 0.12), (4, line, 0.35), (2.2, bright, 0.9)):
        cr.set_line_width(width)
        cr.set_source_rgba(*color, alpha)
        for ring in rings:
            trace(cr, ring, TEXTURE_WIDTH, TEXTURE_HEIGHT)
        cr.stroke()
    for lon, lat, population in points:
        x, y = to_texture(lon, lat)
        if population <= 0:
            cr.arc(x, y, 1.6, 0, 2 * math.pi)
            cr.set_source_rgba(*line, 0.55)
            cr.fill()
            continue
        size = 2.5 + 7 * min(1.0, math.log10(max(population, 10)) / 7.5) ** 3
        glow = cairo.RadialGradient(x, y, 0, x, y, size * 2.2)
        glow.add_color_stop_rgba(0, *bright, 0.9)
        glow.add_color_stop_rgba(0.25, *accent, 0.45)
        glow.add_color_stop_rgba(1, *accent, 0)
        cr.arc(x, y, size * 2.2, 0, 2 * math.pi)
        cr.set_source(glow)
        cr.fill()
        cr.arc(x, y, size * 0.45, 0, 2 * math.pi)
        cr.set_source_rgb(*bright)
        cr.fill()
    surface.flush()
    small = cairo.ImageSurface(cairo.FORMAT_ARGB32, RUNTIME_WIDTH, RUNTIME_HEIGHT)
    context = cairo.Context(small)
    context.scale(RUNTIME_WIDTH / TEXTURE_WIDTH, RUNTIME_HEIGHT / TEXTURE_HEIGHT)
    context.set_source_surface(surface, 0, 0)
    context.get_source().set_filter(cairo.FILTER_GOOD)
    context.paint()
    small.flush()
    stride = small.get_stride()
    rows = bytes(small.get_data())
    with open(path, "wb") as output:
        for row in range(RUNTIME_HEIGHT):
            output.write(rows[row * stride:row * stride + RUNTIME_WIDTH * 4])


def load_texture(directory):
    data = bytearray(texture_path(directory).read_bytes())
    if len(data) != RUNTIME_WIDTH * RUNTIME_HEIGHT * 4:
        raise ValueError("globe texture has the wrong size")
    return data


def renderer_library_path():
    digest = hashlib.sha1(RENDERER_SOURCE.read_bytes()).hexdigest()[:12]
    return GLOBE_ROOT / f"libglobe-{digest}.so"


def compile_renderer():
    library = renderer_library_path()
    if library.is_file():
        return library
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not compiler:
        raise RuntimeError("no C compiler found, install base-devel")
    GLOBE_ROOT.mkdir(parents=True, exist_ok=True)
    staging = library.with_name(f".{library.name}.{os.getpid()}")
    result = subprocess.run(
        [compiler, "-O3", "-march=native", "-ffast-math", "-fopenmp", "-fPIC", "-shared", "-o", str(staging), str(RENDERER_SOURCE), "-lm"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        staging.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "compiling the globe renderer failed")
    staging.rename(library)
    return library


def load_renderer():
    os.environ.setdefault("OMP_NUM_THREADS", str(len(os.sched_getaffinity(0))))
    library = ctypes.CDLL(str(compile_renderer()))
    float_pointer = ctypes.POINTER(ctypes.c_float)
    library.globe_prepare.argtypes = [
        ctypes.c_int, ctypes.c_double, ctypes.c_int, ctypes.c_int, float_pointer, float_pointer, float_pointer,
    ]
    library.globe_prepare.restype = None
    library.globe_render.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, float_pointer, float_pointer, float_pointer,
        ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_double,
    ]
    library.globe_render.restype = None
    return library


def build(colors):
    directory = cache_dir(colors)
    if is_ready(directory):
        return directory
    if not geodata_available():
        raise RuntimeError(f"map data missing in {GEODATA_DIR}")
    compile_renderer()
    GLOBE_ROOT.mkdir(parents=True, exist_ok=True)
    with open(GLOBE_ROOT / ".build.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if is_ready(directory):
            return directory
        staging = GLOBE_ROOT / f".{directory.name}.{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        try:
            build_texture(colors, texture_path(staging))
            (staging / "ready").write_text("ok\n")
            shutil.rmtree(directory, ignore_errors=True)
            staging.rename(directory)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return directory


def theme_colors(name=None):
    sys.path.insert(0, str(THEME_SWITCH_DIR))
    import theme_switch
    name = name or theme_switch.current_theme() or theme_switch.DEFAULT_THEME
    _, palette = theme_switch.load_palette(name)
    return {key: palette[key] for key in COLOR_KEYS}


def main(arguments):
    try:
        directory = build(theme_colors(arguments[0] if arguments else None))
    except Exception as error:
        print(f"globe-builder: {error}", file=sys.stderr)
        return 1
    print(directory)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
