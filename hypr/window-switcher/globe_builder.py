#!/usr/bin/env python3
import ctypes
import fcntl
import hashlib
import json
import math
import mmap
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cairo

BUILD_VERSION = 7
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
GLOBE_DIRECTORY_NAME = re.compile(r"[0-9a-f]{16}")
STALE_STAGING_SECONDS = 3600
LAYER_NAMES = ("color.mip", "surface.mip")
BAKE_SEED = 7
COMPILER_FLAGS = ("-O3", "-march=native", "-ffast-math", "-fPIC", "-shared")
GCC_TUNING = ("--param", "max-completely-peeled-insns=2000", "-mtune-ctrl=use_gather")
PARALLEL_FLAGS = (
    ("-fopenmp", *GCC_TUNING), ("-fopenmp-simd", *GCC_TUNING), ("-fopenmp",), ("-fopenmp-simd",), (),
)
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


class Color(ctypes.c_float * 3):
    pass


class GlobeParams(ctypes.Structure):
    _fields_ = [
        ("light", Color), ("key_color", Color), ("rim_color", Color), ("sky_ambient", Color),
        ("ground_ambient", Color), ("atmosphere_lit", Color), ("atmosphere_dark", Color),
        ("emissive_color", Color), ("cloud_color", Color), ("warm_color", Color),
        ("warm_amount", ctypes.c_float), ("bump", ctypes.c_float), ("pitch_degrees", ctypes.c_float),
        ("shift", ctypes.c_float), ("cloud_shift", ctypes.c_float), ("exposure", ctypes.c_float),
        ("bloom_threshold", ctypes.c_float), ("bloom_strength", ctypes.c_float), ("grain_amount", ctypes.c_float),
        ("halo_extent", ctypes.c_float), ("grain_seed", ctypes.c_uint32),
    ]


class BakeParams(ctypes.Structure):
    _fields_ = [
        ("ocean_deep", Color), ("ocean_shelf", Color), ("land_low", Color), ("land_high", Color),
        ("lights_gain", ctypes.c_float), ("seed", ctypes.c_uint32),
    ]


def mip_bytes(width=RUNTIME_WIDTH, height=RUNTIME_HEIGHT):
    total = 0
    while True:
        total += width * height * 4
        if width <= 1 or height <= 1:
            return total
        width, height = width // 2, height // 2


def layer_paths(directory):
    return [directory / name for name in LAYER_NAMES]


def is_ready(directory):
    try:
        return (directory / "ready").is_file() and all(path.stat().st_size == mip_bytes() for path in layer_paths(directory))
    except OSError:
        return False


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


def draw_lights(rings, places, rng):
    surface = cairo.ImageSurface(cairo.FORMAT_A8, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    cr = cairo.Context(surface)
    points = network_points(rings, places, rng)
    cr.set_line_width(1.3)
    cr.set_source_rgba(0, 0, 0, 0.3)
    for first, second in network_links(points):
        stroke_wrapped(cr, points[first], points[second])
    cr.stroke()
    for lon, lat, population in points:
        x, y = to_texture(lon, lat)
        if population <= 0:
            cr.arc(x, y, 1.2, 0, 2 * math.pi)
            cr.set_source_rgba(0, 0, 0, 0.45)
            cr.fill()
            continue
        size = 2.5 + 7 * min(1.0, math.log10(max(population, 10)) / 7.5) ** 3
        glow = cairo.RadialGradient(x, y, 0, x, y, size * 1.5)
        glow.add_color_stop_rgba(0, 0, 0, 0, 1.0)
        glow.add_color_stop_rgba(0.2, 0, 0, 0, 0.6)
        glow.add_color_stop_rgba(1, 0, 0, 0, 0)
        cr.arc(x, y, size * 1.5, 0, 2 * math.pi)
        cr.set_source(glow)
        cr.fill()
    surface.flush()
    return surface


def draw_land(rings):
    surface = cairo.ImageSurface(cairo.FORMAT_A8, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    cr = cairo.Context(surface)
    cr.set_fill_rule(cairo.FILL_RULE_WINDING)
    fill_rings(cr, rings, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    surface.flush()
    return surface


def draw_coast(rings, colors):
    accent = hex_to_rgb(colors["accent"])
    foreground = hex_to_rgb(colors["foreground"])
    line = mix(foreground, accent, 0.3)
    bright = mix(foreground, WHITE, 0.6)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    cr = cairo.Context(surface)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    for width, color, alpha in ((14, accent, 0.05), (8, accent, 0.1), (4, line, 0.28), (2.2, bright, 0.75)):
        cr.set_line_width(width)
        cr.set_source_rgba(*color, alpha)
        for ring in rings:
            trace(cr, ring, TEXTURE_WIDTH, TEXTURE_HEIGHT)
        cr.stroke()
    surface.flush()
    return surface


def bake_params(colors):
    background = hex_to_rgb(colors["background"])
    foreground = hex_to_rgb(colors["foreground"])
    primary = hex_to_rgb(colors["primary"])
    accent = hex_to_rgb(colors["accent"])
    return BakeParams(
        Color(*mix(background, BLACK, 0.74)), Color(*mix(mix(background, accent, 0.3), BLACK, 0.5)),
        Color(*mix(primary, BLACK, 0.45)), Color(*mix(mix(primary, foreground, 0.3), BLACK, 0.25)),
        1.0, BAKE_SEED,
    )


def surface_pointer(surface):
    data = surface.get_data()
    return data, ctypes.addressof((ctypes.c_char * len(data)).from_buffer(data))


def build_layers(colors, directory, library):
    rng = random.Random(BAKE_SEED)
    rings = land_rings()
    land_surface = draw_land(rings)
    coast_surface = draw_coast(rings, colors)
    lights_surface = draw_lights(rings, cities(), rng)
    layers = [bytearray(mip_bytes()) for _ in LAYER_NAMES]
    pointers = [ctypes.addressof((ctypes.c_char * len(layer)).from_buffer(layer)) for layer in layers]
    land_data, land_pointer = surface_pointer(land_surface)
    coast_data, coast_pointer = surface_pointer(coast_surface)
    lights_data, lights_pointer = surface_pointer(lights_surface)
    result = library.globe_bake(
        land_pointer, land_surface.get_stride(), coast_pointer, coast_surface.get_stride(), lights_pointer,
        lights_surface.get_stride(), TEXTURE_WIDTH, TEXTURE_HEIGHT, ctypes.byref(bake_params(colors)),
        pointers[0], pointers[1], RUNTIME_WIDTH, RUNTIME_HEIGHT,
    )
    del land_data, coast_data, lights_data
    if result != 0:
        raise RuntimeError(f"baking the globe layers failed ({result})")
    for layer, pointer, path in zip(layers, pointers, layer_paths(directory)):
        library.globe_build_mips(pointer, RUNTIME_WIDTH, RUNTIME_HEIGHT)
        path.write_bytes(layer)


def map_layers(directory):
    maps = []
    try:
        for path in layer_paths(directory):
            with open(path, "rb") as layer:
                mapped = mmap.mmap(layer.fileno(), 0, access=mmap.ACCESS_COPY)
            maps.append(mapped)
            if len(mapped) != mip_bytes():
                raise ValueError(f"{path.name} has the wrong size")
    except (OSError, ValueError):
        for mapped in maps:
            mapped.close()
        raise
    return maps


def renderer_library_path():
    digest = hashlib.sha1(RENDERER_SOURCE.read_bytes() + repr((COMPILER_FLAGS, PARALLEL_FLAGS)).encode()).hexdigest()[:12]
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
    for parallel in PARALLEL_FLAGS:
        result = subprocess.run(
            [compiler, *COMPILER_FLAGS, *parallel, "-o", str(staging), str(RENDERER_SOURCE), "-lm"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            break
    if result.returncode != 0:
        staging.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "compiling the globe renderer failed")
    staging.rename(library)
    return library


def load_renderer():
    os.environ.setdefault("OMP_NUM_THREADS", str(len(os.sched_getaffinity(0))))
    os.environ.setdefault("OMP_DYNAMIC", "true")
    library = ctypes.CDLL(str(compile_renderer()))
    float_pointer = ctypes.POINTER(ctypes.c_float)
    signatures = {
        "globe_mip_levels": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "globe_build_mips": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_int], None),
        "globe_bind": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int], None),
        "globe_grade": ([float_pointer, float_pointer], None),
        "globe_prepare": (
            [ctypes.c_int, ctypes.c_float, ctypes.c_double, ctypes.c_int, ctypes.c_int, float_pointer, float_pointer, float_pointer],
            None,
        ),
        "globe_render": (
            [ctypes.POINTER(GlobeParams), float_pointer, float_pointer, float_pointer, ctypes.c_int, ctypes.c_float,
             ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, float_pointer, float_pointer, float_pointer],
            None,
        ),
        "globe_bake": (
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
             ctypes.c_int, ctypes.POINTER(BakeParams), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int],
            ctypes.c_int,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    return library


def build(colors):
    directory = cache_dir(colors)
    library_missing = not renderer_library_path().is_file()
    if is_ready(directory) and not library_missing:
        return directory
    if not is_ready(directory) and not geodata_available():
        raise RuntimeError(f"map data missing in {GEODATA_DIR}")
    library = load_renderer()
    GLOBE_ROOT.mkdir(parents=True, exist_ok=True)
    with open(GLOBE_ROOT / ".build.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not is_ready(directory):
            staging = GLOBE_ROOT / f".{directory.name}.{os.getpid()}"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            try:
                build_layers(colors, staging, library)
                (staging / "ready").write_text("ok\n")
                shutil.rmtree(directory, ignore_errors=True)
                staging.rename(directory)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        prune_cache(directory)
    return directory


def wanted_directories():
    sys.path.insert(0, str(THEME_SWITCH_DIR))
    import theme_switch
    wanted = set()
    for name in theme_switch.available_themes():
        try:
            _, palette = theme_switch.load_palette(name)
        except theme_switch.ThemeError:
            continue
        wanted.add(cache_dir({key: palette[key] for key in COLOR_KEYS}).name)
    return wanted


def prune_cache(current):
    try:
        wanted = wanted_directories()
    except Exception:
        return
    if not wanted:
        return
    wanted.add(current.name)
    library = renderer_library_path().name
    now = time.time()
    for entry in GLOBE_ROOT.iterdir():
        name = entry.name
        try:
            if entry.is_dir() and GLOBE_DIRECTORY_NAME.fullmatch(name) and name not in wanted:
                shutil.rmtree(entry, ignore_errors=True)
            elif entry.is_dir() and name.startswith(".") and now - entry.stat().st_mtime > STALE_STAGING_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
            elif entry.is_file() and name.startswith("libglobe-") and name.endswith(".so") and name != library:
                entry.unlink(missing_ok=True)
            elif entry.is_file() and name.startswith(".libglobe-") and now - entry.stat().st_mtime > STALE_STAGING_SECONDS:
                entry.unlink(missing_ok=True)
        except OSError:
            continue


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
    size = sum(path.stat().st_size for path in layer_paths(directory))
    print(f"{directory} {size / 1_000_000:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
