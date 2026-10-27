"""EasyEDA pad/footprint parsing and KiCad footprint serialization."""

import math
from dataclasses import dataclass

from .bounds import courtyard
from .geometry import point_pairs
from .shared import UNIT, effects, f, num, q, stroke, svg_graphics

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
    w, h, radius = num(t[4]) * UNIT, num(t[5]) * UNIT, num(t[9]) * UNIT
    angle = num(t[11])
    shape = {
        'RECT': 'rect',
        'ELLIPSE': 'circle' if abs(w - h) < 1e-6 else 'oval',
        'OVAL': 'oval',
        'POLYGON': 'custom',
    }.get(t[1])
    if shape is None or min(w, h) <= 0:
        raise ValueError('unsupported/invalid pad shape or size')
    through = t[6] == '11'
    kind = ('thru_hole' if t[15] == 'Y' else 'np_thru_hole') if through else 'smd'
    if through and radius <= 0:
        raise ValueError('through-hole pad without drill')
    if through and num(t[13]) < 0:
        raise ValueError('negative drill-slot length')
    if through:
        layers = '"*.Cu" "*.Mask"'
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
    return Pad(
        t[8],
        x,
        y,
        w,
        h,
        2 * radius if through else 0,
        num(t[13]) * UNIT,
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
        pts = point_pairs(t[4])
        return [
            f'(fp_line (start {coords.xy(*a)}) (end {coords.xy(*b)}) {stroke(width)} (layer {q(ln)}))'
            for a, b in zip(pts, pts[1:])
        ]
    if kind == 'SOLIDREGION':
        if t[4] not in ('solid', ''):
            raise ValueError(f'unsupported region type {t[4]}')
        return svg_graphics(t[3], coords, 0.01, False, layer(t[1]), solid=True)
    if kind == 'TEXT':
        mirror = ' (justify mirror)' if t[6] == '1' else ''
        size = num(t[9], 5) * UNIT
        return [
            f'(fp_text user {q(t[10])} (at {coords.xy(t[2], t[3])} {f(num(t[5]))}) '
            f'(layer {q(layer(t[7]))}) (effects (font (size {f(size)} {f(size)}) '
            f'(thickness {f(max(0.01, num(t[4], 0.6) * UNIT))})){mirror}))'
        ]
    if kind == 'CIRCLE':
        x, y, radius = num(t[1]), num(t[2]), num(t[3])
        return [
            f'(fp_circle (center {coords.xy(x, y)}) (end {coords.xy(x + radius, y)}) '
            f'{stroke(num(t[4], 1) * UNIT)} (fill none) (layer {q(layer(t[5]))}))'
        ]
    if kind == 'RECT':
        x, y = num(t[1]), num(t[2])
        return [
            f'(fp_rect (start {coords.xy(x, y)}) (end {coords.xy(x + num(t[3]), y + num(t[4]))}) '
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
        f'(footprint {q(name)} (version 20240108) (generator "easyeda2kicad-local") '
        f'(layer "F.Cu") (attr {attrs})\n'
        f'(property "Reference" "REF**" (at 0 {f(miny - 1)} 0) (layer "F.SilkS") {effects()})\n'
        f'(property "Value" {q(name)} (at 0 {f(maxy + 1)} 0) (layer "F.Fab") {effects(hidden=True)})\n'
        + '\n'.join(p.render() for p in pads)
        + '\n'
        + '\n'.join([*fg, courtyard_graphic])
        + '\n)\n'
    )
    return footprint
