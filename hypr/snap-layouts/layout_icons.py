import os

ICON_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "snap-layouts")
WIDTH, HEIGHT, PAD, GAP = 160, 100, 6, 6


def zone_rect(zone):
    _, x, y, w, h = zone
    inner_w, inner_h = WIDTH - 2 * PAD, HEIGHT - 2 * PAD
    return (
        PAD + x * inner_w + GAP / 2,
        PAD + y * inner_h + GAP / 2,
        w * inner_w - GAP,
        h * inner_h - GAP,
    )


def draw(zones):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">']
    for number, zone in enumerate(zones, start=1):
        x, y, w, h = zone_rect(zone)
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="5" fill="#4a6380"/>')
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 6:.1f}" font-family="Noto Sans" font-size="17" '
            f'font-weight="bold" fill="#ffffff" text-anchor="middle">{number}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def icon_path(layout_index, zones):
    os.makedirs(ICON_DIR, exist_ok=True)
    path = os.path.join(ICON_DIR, f"layout-{layout_index}.svg")
    content = draw(zones)
    if not os.path.exists(path) or open(path).read() != content:
        with open(path, "w") as f:
            f.write(content)
    return path
