"""EasyEDA pad/footprint parsing and KiCad footprint serialization."""

import logging
import math
from dataclasses import dataclass

from .bounds import courtyard
from .geometry import check_polygon, point_pairs
from .shared import UNIT, effects, f, num, q, stroke, svg_graphics

log = logging.getLogger(__name__)

# Layer 11 is handled by pad parsing as all copper/mask layers. Unsupported
# drawing IDs deliberately have no fallback; see the verified table in API_NOTES.
LAYERS = {
    '1': 'F.Cu',
    '2': 'B.Cu',
    '3': 'F.SilkS',
    '4': 'B.SilkS',
    '5': 'F.Paste',
    '6': 'B.Paste',
    '7': 'F.Mask',
    '8': 'B.Mask',
    '10': 'Edge.Cuts',
    '12': 'Dwgs.User',
    '13': 'F.Fab',
    '14': 'B.Fab',
    '99': 'User.3',
    '100': 'User.4',
    '101': 'User.5',
}


def layer(value):
    if value not in LAYERS:
        raise ValueError(f'unsupported layer {value}')
    return LAYERS[value]


@dataclass
class Pad:
    """A physical pad in local mm with a KiCad degree rotation and local polygon.

    Positions keep the footprint's Y-down axis. Hole length is the full oblong
    drill length, not the distance between its circular end centers.
    """

    number: str
    x: float
    y: float
    width: float
    height: float
    drill: float
    hole_length: float
    angle: float
    shape: str
    kind: str
    layers: str
    polygon: list[tuple[float, float]]

    def render(self):
        drill = ''
        if self.drill:
            # Ignore the one-thousandth drawing-unit rounding noise in the fixture.
            if self.hole_length > self.drill + 0.01:
                dx, dy = (
                    (self.drill, self.hole_length)
                    if self.width < self.height
                    else (self.hole_length, self.drill)
                )
                drill = f'(drill oval {f(dx)} {f(dy)})'
            else:
                drill = f'(drill {f(self.drill)})'
        shape = 'custom' if self.polygon else self.shape
        # KiCad custom pads need an anchor as well as polygon primitives.
        size = (
            (min(self.width, self.height) / 4,) * 2 if self.polygon else (self.width, self.height)
        )
        extra = ''
        if self.polygon:
            pts = ' '.join(f'(xy {f(x)} {f(y)})' for x, y in self.polygon)
            extra = f'(options (clearance outline) (anchor circle)) (primitives (gr_poly (pts {pts}) (width 0) (fill yes)))'
        return (
            f'(pad {q(self.number)} {self.kind} {shape} (at {f(self.x)} {f(self.y)} {f(self.angle)}) '
            f'(size {f(size[0])} {f(size[1])}) {drill} (layers {self.layers}) {extra})'
        )


def parse_pad(raw, coords):
    """Read the verified PAD field layout and keep all physical units in mm."""
    t = raw.split('~')
    x, y = coords.point(t[2], t[3])
    dimensions = []
    for field, label in ((4, 'width'), (5, 'height')):
        try:
            dimensions.append(num(t[field]) * UNIT)
        except (ValueError, TypeError) as e:
            raise ValueError(f'invalid pad {label} {t[field]!r}: {e}') from e
    w, h = dimensions
    radius = num(t[9]) * UNIT
    angle = num(t[11])
    shape = {
        'RECT': 'rect',
        'ELLIPSE': 'circle' if abs(w - h) < 1e-6 else 'oval',
        'OVAL': 'oval',
        'POLYGON': 'custom',
    }.get(t[1])
    if shape is None:
        raise ValueError(f'unsupported pad shape {t[1]!r}')
    if min(w, h) < 0 or (shape != 'custom' and min(w, h) == 0):
        raise ValueError(f'invalid pad width {t[4]!r} or height {t[5]!r} for {t[1]}')
    through = t[6] == '11'
    flag = t[15] if len(t) > 15 else ''
    plating = flag.strip().lower()
    if through and plating not in ('y', 'yes', 'true', '1', 'n', 'no', 'false', '0'):
        log.warning('Pad %s: unknown plating value %r; defaulting to plated.', t[8], flag)
    plated = plating not in ('n', 'no', 'false', '0')
    kind = ('thru_hole' if plated else 'np_thru_hole') if through else 'smd'
    if through and radius <= 0:
        raise ValueError('through-hole pad without drill')
    if through and num(t[13]) < 0:
        raise ValueError('negative drill-slot length')
    hole_length = num(t[13]) * UNIT
    if through and hole_length > 2 * radius + 0.01 and t[14] not in ('', 'undefined'):
        centers = [coords.point(*p) for p in point_pairs(t[14])]
        if len(centers) != 2:
            raise ValueError('slot must have exactly two hole-center points')
        cx, cy = ((a + b) / 2 for a, b in zip(*centers))
        dx, dy = (b - a for a, b in zip(*centers))
        axis = math.radians(-angle + (90 if w < h else 0))
        # Source points are rounded; accept the verified sub-micrometre noise,
        # but never silently center or reorient an offset/independent drill.
        if (
            math.hypot(cx - x, cy - y) > 0.001
            or abs(math.hypot(dx, dy) + 2 * radius - hole_length) > 0.001
            or abs(dx * math.sin(axis) - dy * math.cos(axis)) > 0.001
        ):
            raise ValueError('unsupported offset, independently angled or inconsistent slot')
    if through:
        # KiCad's native EasyEDA importer uses outer copper/mask only for NPTH.
        layers = '"*.Cu" "*.Mask"' if kind == 'thru_hole' else '"F.Cu" "B.Cu" "*.Mask"'
    elif t[6] in ('1', '2'):
        side = 'F' if t[6] == '1' else 'B'
        layers = ' '.join(q(f'{side}.{s}') for s in ('Cu', 'Paste', 'Mask'))
    else:
        raise ValueError(f'unsupported pad layer {t[6]}')
    polygon = []
    if shape == 'custom':
        for px, py in point_pairs(t[10], minimum=3):
            px, py = coords.point(px, py)
            # KiCad applies a positive pad angle counterclockwise in Y-down
            # coordinates. Undo that world transform to obtain local vertices.
            a = math.radians(angle)
            polygon.append(
                (
                    (px - x) * math.cos(a) - (py - y) * math.sin(a),
                    (px - x) * math.sin(a) + (py - y) * math.cos(a),
                )
            )
        check_polygon(polygon)
        # Eagle/Altium imports legitimately omit a polygon pad's dimensions.
        # Its absolute vertices are authoritative; derive missing dimensions
        # in the unrotated local frame, without moving or resizing the polygon.
        if w == 0:
            w = max(px for px, _ in polygon) - min(px for px, _ in polygon)
        if h == 0:
            h = max(py for _, py in polygon) - min(py for _, py in polygon)
        # KiCad adds a circular anchor at the pad origin. It must fit wholly
        # inside the source polygon; otherwise the anchor invents extra copper.
        vertices = [tuple(round(v, 6) for v in p) for p in polygon]
        anchor_radius = float(f(min(w, h) / 4)) / 2
        inside = False
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            if (a[1] > 0) != (b[1] > 0) and a[0] - a[1] * (b[0] - a[0]) / (b[1] - a[1]) > 0:
                inside = not inside
            dx, dy = b[0] - a[0], b[1] - a[1]
            if dx or dy:
                fraction = max(0, min(1, -(a[0] * dx + a[1] * dy) / (dx * dx + dy * dy)))
                if math.hypot(a[0] + fraction * dx, a[1] + fraction * dy) < anchor_radius:
                    raise ValueError('custom pad anchor extends outside source polygon')
        if not inside:
            raise ValueError('custom pad origin is outside source polygon')
    return Pad(
        t[8],
        x,
        y,
        w,
        h,
        2 * radius if through else 0,
        hole_length,
        angle,
        shape,
        kind,
        layers,
        polygon,
    )


def footprint_graphic(raw, coords):
    """Render supported 2D records; model metadata emits no geometry."""
    t = raw.split('~')
    kind = t[0]
    if kind in ('TRACK', 'ARC'):
        ln, width = layer(t[2]), num(t[1], 1) * UNIT
        if kind == 'ARC':
            return svg_graphics(t[4], coords, width, False, ln)
        pts = [coords.xy(*p) for p in point_pairs(t[4])]
        if not any(a != b for a, b in zip(pts, pts[1:])):
            raise ValueError('empty track geometry')
        return [
            f'(fp_line (start {a}) (end {b}) {stroke(width, minimum=0 if ln.endswith(".Cu") else 0.01)} (layer {q(ln)}))'
            for a, b in zip(pts, pts[1:])
        ]
    if kind == 'SOLIDREGION':
        if t[4] not in ('solid', ''):
            raise ValueError(f'unsupported region type {t[4]}')
        path = t[3].strip()
        if path and path[0] not in 'Mm':
            points = point_pairs(path, minimum=3)
            path = 'M ' + ' L '.join(f'{x} {y}' for x, y in points) + ' Z'
        return svg_graphics(path, coords, 0.01, False, layer(t[1]), solid=True)
    if kind == 'TEXT':
        mirror = ' (justify mirror)' if t[6] == '1' else ''
        size = num(t[9], 5) * UNIT
        if round(size, 6) <= 0 or not t[10].strip() or num(t[4], 0.6) <= 0:
            raise ValueError('empty or invalid footprint text')
        return [
            f'(fp_text user {q(t[10])} (at {coords.xy(t[2], t[3])} {f(num(t[5]))}) '
            f'(layer {q(layer(t[7]))}) (effects (font (size {f(size)} {f(size)}) '
            f'(thickness {f(max(0 if layer(t[7]).endswith(".Cu") else 0.01, num(t[4], 0.6) * UNIT))})){mirror}))'
        ]
    if kind == 'CIRCLE':
        x, y, radius = num(t[1]), num(t[2]), num(t[3])
        center, end = coords.xy(x, y), coords.xy(x + radius, y)
        if radius <= 0 or center == end:
            raise ValueError('empty circle geometry')
        return [
            f'(fp_circle (center {center}) (end {end}) '
            f'{stroke(num(t[4], 1) * UNIT, minimum=0 if layer(t[5]).endswith(".Cu") else 0.01)} (fill none) (layer {q(layer(t[5]))}))'
        ]
    if kind == 'RECT':
        x, y = num(t[1]), num(t[2])
        start, end = coords.xy(x, y), coords.xy(x + num(t[3]), y + num(t[4]))
        if min(num(t[3]), num(t[4])) <= 0 or any(
            a == b for a, b in zip(start.split(), end.split())
        ):
            raise ValueError('empty rectangle geometry')
        return [
            f'(fp_rect (start {start}) (end {end}) '
            f'{stroke(0.254)} (fill none) (layer {q(layer(t[5]))}))'
        ]
    if kind == 'HOLE':
        diameter = 2 * num(t[3]) * UNIT
        if diameter <= 0:
            raise ValueError('hole diameter must be positive')
        return [
            f'(pad "" np_thru_hole circle (at {coords.xy(t[1], t[2])}) '
            f'(size {f(diameter)} {f(diameter)}) (drill {f(diameter)}) (layers "*.Cu" "*.Mask"))'
        ]
    if kind == 'VIA':
        diameter, drill = num(t[3]) * UNIT, 2 * num(t[5]) * UNIT
        if min(diameter, drill) <= 0:
            raise ValueError('via size and drill must be positive')
        return [
            f'(pad "" thru_hole circle (at {coords.xy(t[1], t[2])}) (size {f(diameter)} {f(diameter)}) '
            f'(drill {f(drill)}) (layers "*.Cu" "*.Mask"))'
        ]
    if kind == 'SVGNODE':
        return []  # Ignore non-2D metadata in untouched EasyEDA source responses.
    raise ValueError(f'unsupported footprint element {kind}')


def render_footprint(name, fp, fc, pads, fg):
    """Render a library entry with physical bounds and a generated courtyard.

    ``fp`` and ``fc`` remain for compatibility with the original call signature.
    Bounds come from exported geometry rather than the source's stale BBox.
    """
    minx, miny, maxx, maxy = courtyard(pads, fg)
    courtyard_graphic = f'(fp_rect (start {f(minx)} {f(miny)}) (end {f(maxx)} {f(maxy)}) {stroke(0.05)} (fill none) (layer "F.CrtYd"))'
    attrs = 'through_hole' if any(p.kind != 'smd' for p in pads) else 'smd'
    footprint = (
        f'(footprint {q(name)} (version 20240108) (generator "euc2k") '
        f'(layer "F.Cu") (attr {attrs})\n'
        f'(property "Reference" "REF**" (at 0 {f(miny - 1)} 0) (layer "F.SilkS") {effects()})\n'
        f'(property "Value" {q(name)} (at 0 {f(maxy + 1)} 0) (layer "F.Fab") {effects(hidden=True)})\n'
        + '\n'.join(p.render() for p in pads)
        + '\n'
        + '\n'.join([*fg, courtyard_graphic])
        + '\n)\n'
    )
    return footprint
