TITLE_HEIGHT = 30
GAP = 28


def item_size(size, row_height):
    width, height = size
    shown_height = min(row_height, height)
    return width * shown_height / height, shown_height


def pack(sizes, row_height, area_width):
    rows, row, row_width = [], [], 0
    for index, size in enumerate(sizes):
        w, _ = item_size(size, row_height)
        needed = w if not row else row_width + GAP + w
        if row and needed > area_width:
            rows.append(row)
            row, row_width = [], 0
            needed = w
        row.append(index)
        row_width = needed
    if row:
        rows.append(row)
    return rows


def fits(sizes, row_height, area_width, area_height):
    rows = pack(sizes, row_height, area_width)
    for row in rows:
        if sum(item_size(sizes[i], row_height)[0] for i in row) + GAP * (len(row) - 1) > area_width:
            return False
    total = sum(max(item_size(sizes[i], row_height)[1] for i in row) + TITLE_HEIGHT for row in rows)
    return total + GAP * (len(rows) - 1) <= area_height


def layout(sizes, area_x, area_y, area_width, area_height):
    low, high = 24.0, area_height * 0.7
    for _ in range(30):
        middle = (low + high) / 2
        if fits(sizes, middle, area_width, area_height):
            low = middle
        else:
            high = middle
    row_height = low
    rows = pack(sizes, row_height, area_width)
    heights = [max(item_size(sizes[i], row_height)[1] for i in row) for row in rows]
    total = sum(h + TITLE_HEIGHT for h in heights) + GAP * (len(rows) - 1)
    y = area_y + (area_height - total) / 2
    placed = [None] * len(sizes)
    for row, height in zip(rows, heights):
        widths = [item_size(sizes[i], row_height)[0] for i in row]
        x = area_x + (area_width - sum(widths) - GAP * (len(row) - 1)) / 2
        for index, width in zip(row, widths):
            _, item_height = item_size(sizes[index], row_height)
            image_y = y + TITLE_HEIGHT + (height - item_height) / 2
            placed[index] = (x, image_y, width, item_height)
            x += width + GAP
        y += height + TITLE_HEIGHT + GAP
    return placed
