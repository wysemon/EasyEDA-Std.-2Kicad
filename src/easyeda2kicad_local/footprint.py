"""EasyEDA pad/footprint parsing and KiCad footprint serialization."""
from dataclasses import dataclass
import math

from .geometry import numbers
from .shared import UNIT, effects, f, num, q, stroke, svg_graphics

LAYERS = {'1': 'F.Cu', '2': 'B.Cu', '3': 'F.SilkS', '4': 'B.SilkS',
          '5': 'F.Paste', '6': 'B.Paste', '7': 'F.Mask', '8': 'B.Mask',
          '10': 'Edge.Cuts', '12': 'F.Fab', '13': 'F.Fab', '14': 'B.Fab',
          '99': 'F.Fab', '100': 'F.Fab', '101': 'F.Fab'}


def layer(value):
    if value not in LAYERS:
        raise ValueError(f'unsupported layer {value}')
    return LAYERS[value]



@dataclass
class Pad:
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
    polygon: list

    def render(self):
        drill = ''
        if self.drill:
            # Ignore the one-thousandth drawing-unit rounding noise in the fixture.
            if self.hole_length > self.drill + .01:
                drill = f'(drill oval {f(self.hole_length)} {f(self.drill)})'
            else:
                drill = f'(drill {f(self.drill)})'
        shape = 'custom' if self.polygon else self.shape
        size = (min(self.width, self.height) / 4,) * 2 if self.polygon else (self.width, self.height)
        extra = ''
        if self.polygon:
            pts = ' '.join(f'(xy {f(x)} {f(y)})' for x, y in self.polygon)
            extra = f'(options (clearance outline) (anchor circle)) (primitives (gr_poly (pts {pts}) (width 0) (fill yes)))'
        return (f'(pad {q(self.number)} {self.kind} {shape} (at {f(self.x)} {f(self.y)} {f(self.angle)}) '
                f'(size {f(size[0])} {f(size[1])}) {drill} (layers {self.layers}) {extra})')



def parse_pad(raw, coords):
    t = raw.split('~')
    x, y = coords.point(t[2], t[3])
    w, h, radius = num(t[4]) * UNIT, num(t[5]) * UNIT, num(t[9]) * UNIT
    angle = num(t[11])
    shape = {'RECT': 'rect', 'ELLIPSE': 'circle' if abs(w - h) < 1e-6 else 'oval',
             'OVAL': 'oval', 'POLYGON': 'custom'}.get(t[1])
    if shape is None or min(w, h) <= 0:
        raise ValueError('unsupported/invalid pad shape or size')
    through = t[6] == '11'
    kind = ('thru_hole' if t[15] == 'Y' else 'np_thru_hole') if through else 'smd'
    if through and radius <= 0:
        raise ValueError('through-hole pad without drill')
    if through:
        layers = '"*.Cu" "*.Mask"'
    elif t[6] in ('1', '2'):
        side = 'F' if t[6] == '1' else 'B'
        layers = ' '.join(q(f'{side}.{s}') for s in ('Cu', 'Paste', 'Mask'))
    else:
        raise ValueError(f'unsupported pad layer {t[6]}')
    polygon = []
    if shape == 'custom':
        ns = numbers(t[10])
        if len(ns) < 6 or len(ns) % 2:
            raise ValueError('invalid polygon pad')
        for px, py in zip(ns[::2], ns[1::2]):
            px, py = coords.point(px, py)
            a = math.radians(-angle)
            polygon.append(((px - x) * math.cos(a) - (py - y) * math.sin(a),
                            (px - x) * math.sin(a) + (py - y) * math.cos(a)))
    return Pad(t[8], x, y, w, h, 2 * radius if through else 0,
               num(t[13]) * UNIT, angle, shape, kind, layers, polygon)



def footprint_graphic(raw, coords):
    t = raw.split('~')
    kind = t[0]
    if kind in ('TRACK', 'ARC'):
        ln, width = layer(t[2]), num(t[1], 1) * UNIT
        if kind == 'ARC':
            return svg_graphics(t[4], coords, width, False, ln)
        ns = numbers(t[4])
        pts = list(zip(ns[::2], ns[1::2]))
        return [f'(fp_line (start {coords.xy(*a)}) (end {coords.xy(*b)}) {stroke(width)} (layer {q(ln)}))'
                for a, b in zip(pts, pts[1:])]
    if kind == 'SOLIDREGION':
        if t[4] not in ('solid', ''):
            raise ValueError(f'unsupported region type {t[4]}')
        return svg_graphics(t[3], coords, .01, False, layer(t[1]), solid=True)
    if kind == 'TEXT':
        mirror = ' (justify mirror)' if t[6] == '1' else ''
        size = num(t[9], 5) * UNIT
        return [f'(fp_text user {q(t[10])} (at {coords.xy(t[2], t[3])} {f(num(t[5]))}) '
                f'(layer {q(layer(t[7]))}) (effects (font (size {f(size)} {f(size)}) '
                f'(thickness {f(max(.01, num(t[4], .6) * UNIT))})){mirror}))']
    if kind == 'CIRCLE':
        x, y, radius = num(t[1]), num(t[2]), num(t[3])
        return [f'(fp_circle (center {coords.xy(x, y)}) (end {coords.xy(x + radius, y)}) '
                f'{stroke(num(t[4], 1) * UNIT)} (fill none) (layer {q(layer(t[5]))}))']
    if kind == 'RECT':
        x, y = num(t[1]), num(t[2])
        return [f'(fp_rect (start {coords.xy(x, y)}) (end {coords.xy(x + num(t[3]), y + num(t[4]))}) '
                f'{stroke(.254)} (fill none) (layer {q(layer(t[5]))}))']
    if kind == 'HOLE':
        diameter = 2 * num(t[3]) * UNIT
        return [f'(pad "" np_thru_hole circle (at {coords.xy(t[1], t[2])}) '
                f'(size {f(diameter)} {f(diameter)}) (drill {f(diameter)}) (layers "*.Cu" "*.Mask"))']
    if kind == 'VIA':
        diameter, drill = num(t[3]) * UNIT, 2 * num(t[5]) * UNIT
        return [f'(pad "" thru_hole circle (at {coords.xy(t[1], t[2])}) (size {f(diameter)} {f(diameter)}) '
                f'(drill {f(drill)}) (layers "*.Cu" "*.Mask"))']
    if kind == 'SVGNODE':
        return []  # Explicit optional handling after credits generation.
    raise ValueError(f'unsupported footprint element {kind}')



def render_footprint(name, fp, fc, pads, fg):
    box = fp.get('BBox') or {}
    extents = []
    if box:
        extents.extend([fc.point(box['x'], box['y']),
                        fc.point(num(box['x']) + num(box['width']), num(box['y']) + num(box['height']))])
    for pad in pads:
        a = math.radians(pad.angle)
        wx = (abs(pad.width * math.cos(a)) + abs(pad.height * math.sin(a))) / 2
        hy = (abs(pad.width * math.sin(a)) + abs(pad.height * math.cos(a))) / 2
        extents.extend([(pad.x - wx, pad.y - hy), (pad.x + wx, pad.y + hy)])
    minx, maxx = min(x for x, _ in extents) - .25, max(x for x, _ in extents) + .25
    miny, maxy = min(y for _, y in extents) - .25, max(y for _, y in extents) + .25
    fg.append(f'(fp_rect (start {f(minx)} {f(miny)}) (end {f(maxx)} {f(maxy)}) {stroke(.05)} (fill none) (layer "F.CrtYd"))')
    attrs = 'through_hole' if any(p.kind != 'smd' for p in pads) else 'smd'
    footprint = (f'(footprint {q(name)} (version 20240108) (generator "easyeda2kicad-local") '
                 f'(layer "F.Cu") (attr {attrs})\n'
                 f'(property "Reference" "REF**" (at 0 {f(miny - 1)} 0) (layer "F.SilkS") {effects()})\n'
                 f'(property "Value" {q(name)} (at 0 {f(maxy + 1)} 0) (layer "F.Fab") {effects(hidden=True)})\n'
                 + '\n'.join(p.render() for p in pads) + '\n' + '\n'.join(fg) + '\n)\n')
    return footprint
