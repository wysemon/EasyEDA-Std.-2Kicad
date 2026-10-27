"""Conservative physical footprint bounds, excluding text and documentation."""

import math

from .sexpr import children, loads

BODY_LAYERS = {
    'F.Cu',
    'B.Cu',
    'F.Paste',
    'B.Paste',
    'F.Mask',
    'B.Mask',
    'F.SilkS',
    'B.SilkS',
    'F.Fab',
    'B.Fab',
    'Edge.Cuts',
    'User.3',
}


def values(node, kind):
    return list(map(float, children(node, kind)[0][1:]))


def rotated_box(x, y, width, height, angle):
    a = math.radians(angle)
    dx = (abs(width * math.cos(a)) + abs(height * math.sin(a))) / 2
    dy = (abs(width * math.sin(a)) + abs(height * math.cos(a))) / 2
    return [(x - dx, y - dy), (x + dx, y + dy)]


def pad_points(node):
    at = values(node, 'at')
    x, y = at[:2]
    angle = at[2] if len(at) > 2 else 0
    width, height = values(node, 'size')
    if node[3] == 'circle' or node[3] == 'custom':
        points = [(x - width / 2, y - height / 2), (x + width / 2, y + height / 2)]
    else:
        points = rotated_box(x, y, width, height, angle)
    if node[3] == 'custom':
        a = math.radians(-angle)  # KiCad pad-local -> footprint Y-down.
        for primitive in children(children(node, 'primitives')[0], 'gr_poly'):
            for xy in children(children(primitive, 'pts')[0], 'xy'):
                px, py = map(float, xy[1:])
                points.append(
                    (
                        x + px * math.cos(a) - py * math.sin(a),
                        y + px * math.sin(a) + py * math.cos(a),
                    )
                )
    for drill in children(node, 'drill'):
        dims = list(map(float, drill[2:] if drill[1] == 'oval' else drill[1:]))
        points.extend(rotated_box(x, y, dims[0], dims[-1], angle))
    return points


def arc_extrema(start, mid, end):
    ax, ay = start
    bx, by = mid
    cx, cy = end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [start, mid, end]
    aa, bb, cc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    x = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
    y = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
    radius = math.hypot(ax - x, ay - y)
    first, middle, last = (math.atan2(py - y, px - x) for px, py in (start, mid, end))
    tau = 2 * math.pi
    ccw = (middle - first) % tau <= (last - first) % tau
    result = [start, end, mid]
    for angle in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
        inside = (
            (angle - first) % tau <= (last - first) % tau + 1e-9
            if ccw
            else (first - angle) % tau <= (first - last) % tau + 1e-9
        )
        if inside:
            result.append((x + radius * math.cos(angle), y + radius * math.sin(angle)))
    return result


def graphic_points(node):
    if node[0] == 'pad':  # Standalone mechanical holes / vias.
        return pad_points(node)
    layers = children(node, 'layer')
    if not layers or layers[0][1] not in BODY_LAYERS or node[0] == 'fp_text':
        return []
    kind = node[0]
    if kind == 'fp_circle':
        x, y = values(node, 'center')
        ex, ey = values(node, 'end')
        radius = math.hypot(ex - x, ey - y)
        points = [(x - radius, y - radius), (x + radius, y + radius)]
    elif kind == 'fp_arc':
        points = arc_extrema(*(values(node, k) for k in ('start', 'mid', 'end')))
    elif kind == 'fp_poly':
        points = [list(map(float, p[1:])) for p in children(children(node, 'pts')[0], 'xy')]
    elif kind in ('fp_rect', 'fp_line'):
        points = [values(node, 'start'), values(node, 'end')]
    else:
        return []
    width = values(children(node, 'stroke')[0], 'width')[0] / 2
    return [(x + dx, y + dy) for x, y in points for dx, dy in ((-width, -width), (width, width))]


def courtyard(pads, graphics):
    points = [point for pad in pads for point in pad_points(loads(pad.render()))]
    points.extend(point for graphic in graphics for point in graphic_points(loads(graphic)))
    # 0.25 mm clearance, rounded outwards to KiCad's usual 0.05 mm grid.
    return (
        math.floor((min(x for x, _ in points) - 0.25) / 0.05 + 1e-9) * 0.05,
        math.floor((min(y for _, y in points) - 0.25) / 0.05 + 1e-9) * 0.05,
        math.ceil((max(x for x, _ in points) + 0.25) / 0.05 - 1e-9) * 0.05,
        math.ceil((max(y for _, y in points) + 0.25) / 0.05 - 1e-9) * 0.05,
    )
