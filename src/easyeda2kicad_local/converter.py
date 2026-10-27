"""Tolerant EasyEDA geometry conversion; no upstream implementation copied."""
from collections import Counter
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

from .geometry import numbers, path_segments

log = logging.getLogger(__name__)
UNIT = .254
DRAWING_TEXT_SIZE = 75 * .0254  # 75 mil, in KiCad millimetres
LAYERS = {'1': 'F.Cu', '2': 'B.Cu', '3': 'F.SilkS', '4': 'B.SilkS',
          '5': 'F.Paste', '6': 'B.Paste', '7': 'F.Mask', '8': 'B.Mask',
          '10': 'Edge.Cuts', '12': 'F.Fab', '13': 'F.Fab', '14': 'B.Fab',
          '99': 'F.Fab', '100': 'F.Fab', '101': 'F.Fab'}


def num(value, default=0.):
    if value in (None, '', 'undefined'):
        return default
    value = float(str(value).removesuffix('pt'))
    if not math.isfinite(value):
        raise ValueError('nonfinite coordinate')
    return value


def f(value):
    value = round(value, 6)
    return str(value if value else 0)


def q(text):
    # KiCad strings use escaped double quotes and backslashes.
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"').replace('\r', ' ').replace('\n', '\\n') + '"'


def safe_name(title):
    ascii_title = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode()
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', ascii_title).strip('._-')[:60].rstrip('._-') or 'component'
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
                *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if name.split('.')[0].upper() in reserved:
        name = '_' + name[:59]
    return name


def document(value):
    return json.loads(value) if isinstance(value, str) else value


def prefix(value):
    return re.sub(r'\d+$', '', (value or '').replace('?', '')) or 'U'


def effects(size=1.27, hidden=False):
    return f'(effects (font (size {f(size)} {f(size)})){" hide" if hidden else ""})'


class Coordinates:
    def __init__(self, data, symbol=False):
        self.x = num(data['head'].get('x'))
        self.y = num(data['head'].get('y'))
        self.sign = -1 if symbol else 1

    def point(self, x, y):
        return ((num(x) - self.x) * UNIT, (num(y) - self.y) * UNIT * self.sign)

    def xy(self, x, y):
        return ' '.join(map(f, self.point(x, y)))


@dataclass
class Pin:
    number: str
    name: str
    x: float
    y: float
    angle: int
    length: float
    electrical: str
    style: str = 'line'

    def render(self):
        return (f'(pin {self.electrical} {self.style} (at {f(self.x)} {f(self.y)} {self.angle}) '
                f'(length {f(self.length)}) (name {q(self.name)} {effects()}) '
                f'(number {q(self.number)} {effects()}))')


def parse_pin(raw, coords):
    sections = [s.split('~') for s in raw.split('^^')]
    main = sections[0]
    segments = list(path_segments(sections[2][0]))
    if len(segments) != 1 or segments[0][0] != 'line':
        raise ValueError('pin path must be one straight segment')
    start, end = segments[0][1]
    x, y = coords.point(*start)
    ex, ey = coords.point(*end)
    dx, dy = ex - x, ey - y
    if abs(dx) > 1e-6 and abs(dy) > 1e-6:
        raise ValueError('nonorthogonal pin')
    length = math.hypot(dx, dy)
    if length <= 0:
        raise ValueError('zero-length pin')
    angle = round(math.degrees(math.atan2(dy, dx))) % 360
    name, number = sections[3][4], sections[4][4] or main[3]
    electrical = {'0': 'unspecified', '1': 'input', '2': 'output',
                  '3': 'bidirectional', '4': 'power_in'}.get(main[2], 'unspecified')
    inverted = len(sections) > 5 and sections[5][0] == '1'
    clock = len(sections) > 6 and sections[6][0] == '1'
    style = 'inverted_clock' if inverted and clock else 'inverted' if inverted else 'clock' if clock else 'line'
    return Pin(number, name, x, y, angle, length, electrical, style)


def layer(value):
    if value not in LAYERS:
        raise ValueError(f'unsupported layer {value}')
    return LAYERS[value]


def stroke(width):
    return f'(stroke (width {f(max(.01, width))}) (type default))'


def fill(value):
    return '(fill (type none))' if value in ('', 'none', 'undefined') else '(fill (type background))'


def poly(points, width, symbol, layer_name='F.Fab', solid=False):
    pts = ' '.join(f'(xy {f(x)} {f(y)})' for x, y in points)
    if symbol:
        return f'(polyline (pts {pts}) {stroke(width)} (fill (type {"background" if solid else "none"})))'
    return f'(fp_poly (pts {pts}) {stroke(width)} (fill {"solid" if solid else "none"}) (layer {q(layer_name)}))'


def svg_graphics(path, coords, width, symbol, layer_name='F.Fab', solid=False):
    segments = list(path_segments(path))
    if solid:
        if any(kind != 'line' for kind, _ in segments):
            raise ValueError('curved solid region not supported')
        if not segments:
            raise ValueError('empty solid region')
        points = [coords.point(*segments[0][1][0])]
        points.extend(coords.point(*pts[-1]) for _, pts in segments)
        return [poly(points, width, symbol, layer_name, True)]
    result = []
    for kind, pts in segments:
        pts = [coords.point(*p) for p in pts]
        if kind == 'arc':
            start, mid, end = pts
            body = (f'(start {f(start[0])} {f(start[1])}) '
                    f'(mid {f(mid[0])} {f(mid[1])}) (end {f(end[0])} {f(end[1])}) {stroke(width)}')
            result.append(f'(arc {body} (fill (type none)))' if symbol else
                          f'(fp_arc {body} (layer {q(layer_name)}))')
        elif kind == 'line' and not symbol:
            result.append(f'(fp_line (start {f(pts[0][0])} {f(pts[0][1])}) '
                          f'(end {f(pts[1][0])} {f(pts[1][1])}) {stroke(width)} (layer {q(layer_name)}))')
        else:
            if kind == 'ellipse':
                log.warning('Approximating elliptical SVG arc as a polyline: %s', path)
            result.append(poly(pts, width, symbol, layer_name))
    return result


def symbol_text_angle(value):
    # Stock SSM2018 graphic text: 900 = 90 degrees; property angles use 90.
    # Reflect the EasyEDA Y-down orientation into symbol Y-up before scaling.
    return f'{(-num(value) % 360) * 10:g}'


def symbol_graphic(raw, coords):
    t = raw.split('~')
    kind = t[0]
    if kind == 'R':
        x, y = num(t[1]), num(t[2])
        return [f'(rectangle (start {coords.xy(x, y)}) (end {coords.xy(x + num(t[5]), y + num(t[6]))}) '
                f'{stroke(num(t[8], 1) * UNIT)} {fill(t[10])})']
    if kind in ('E', 'C'):
        x, y, rx = num(t[1]), num(t[2]), num(t[3])
        ry = num(t[4], rx) if kind == 'E' else rx
        if rx != ry:
            pts = [coords.point(x + rx * math.cos(i * math.pi / 32), y + ry * math.sin(i * math.pi / 32)) for i in range(65)]
            return [poly(pts, .254, True)]
        wi, fi = (6, 8) if kind == 'E' else (5, 7)
        return [f'(circle (center {coords.xy(x, y)}) (radius {f(rx * UNIT)}) {stroke(num(t[wi], 1) * UNIT)} {fill(t[fi])})']
    if kind == 'T':
        return [f'(text {q(t[12])} (at {coords.xy(t[2], t[3])} {symbol_text_angle(t[4])}) '
                f'{effects(DRAWING_TEXT_SIZE)})']
    if kind in ('PL', 'PG'):
        ns = numbers(t[1])
        points = [coords.point(x, y) for x, y in zip(ns[::2], ns[1::2])]
        if kind == 'PG' and points:
            points.append(points[0])
        return [poly(points, num(t[3], 1) * UNIT, True, solid=kind == 'PG')]
    if kind in ('PT', 'A'):
        return svg_graphics(t[1], coords, num(t[3], 1) * UNIT, True)
    raise ValueError(f'unsupported symbol element {kind}')


def symbol_label_position(data, coords, graphics, pins):
    """Center over body geometry; clear the entire converted drawing and pins.

    Generated primitives are already in KiCad mm. The source BBox is included
    as an extra guard, but geometry still works when BBox is missing or stale.
    Text uses a conservative one-em-per-character envelope, not just its anchor.
    """
    body, outer = [], []
    for graphic in graphics:
        points = [] if graphic.startswith('(text ') else [
            tuple(numbers(point)) for point in
            re.findall(r'\((?:start|end|mid|xy|center) ([^)]*)\)', graphic)]
        if graphic.startswith('(circle '):
            x, y = points[0]
            radius = num(re.search(r'\(radius ([^)]*)\)', graphic)[1])
            points = [(x - radius, y - radius), (x + radius, y + radius)]
        elif graphic.startswith('(arc '):
            # Use its full circumcircle as a conservative envelope.
            (ax, ay), (bx, by), (cx, cy) = points
            d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
            if abs(d) > 1e-12:
                aa, bb, cc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
                x = (aa * (by - cy) + bb * (cy - ay) + cc * (ay - by)) / d
                y = (aa * (cx - bx) + bb * (ax - cx) + cc * (bx - ax)) / d
                radius = math.hypot(ax - x, ay - y)
                points = [(x - radius, y - radius), (x + radius, y + radius)]
        body.extend(points)
        outer.extend(points)
        if graphic.startswith('(text '):
            match = re.search(r'^\(text ("(?:\\.|[^"\\])*") \(at ([^)]*)\).*?\(size ([^)]*)\)', graphic)
            text = json.loads(match[1], strict=False)
            x, y, angle = numbers(match[2])
            width, height = numbers(match[3])
            lines = text.splitlines() or ['']
            half_width = max(map(len, lines)) * width / 2
            half_height = len(lines) * height * .75
            a = math.radians(angle / 10)
            dx = abs(half_width * math.cos(a)) + abs(half_height * math.sin(a))
            dy = abs(half_width * math.sin(a)) + abs(half_height * math.cos(a))
            outer.extend([(x - dx, y - dy), (x + dx, y + dy)])
    for pin in pins:
        a = math.radians(pin.angle)
        outer.extend([(pin.x, pin.y),
                      (pin.x + pin.length * math.cos(a), pin.y + pin.length * math.sin(a))])
    box = data.get('BBox') or {}
    if box:
        outer.extend([coords.point(box['x'], box['y']),
                      coords.point(num(box['x']) + num(box['width']), num(box['y']) + num(box['height']))])
    centered = body or outer
    center = (min(x for x, _ in centered) + max(x for x, _ in centered)) / 2
    top = max(y for _, y in outer)
    return center, top + 2.54


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
        size = DRAWING_TEXT_SIZE
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
                f'{stroke(.254)} (fill none) (layer {q(layer(t[6]))}))']
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


def owner(component):
    o = component.get('owner') or {}
    return o.get('nickname') or o.get('username') or 'unknown'


def unit_one(data):
    if 'subparts' not in data:
        return data
    log.warning('Multi-unit symbol: converting unit 1 only; subparts format is unverified')
    parts = data['subparts']
    if data.get('shape'):
        return data
    if isinstance(parts, list) and parts and isinstance(parts[0], dict) and 'shape' in parts[0]:
        return {**data, 'shape': parts[0]['shape']}
    raise ValueError('unrecognized subparts layout; cannot locate unit 1')


@dataclass
class Conversion:
    name: str
    pins: list
    pads: list
    symbol: str
    footprint: str
    credits: str


def convert_response(response, package=None):
    if response.get('success') is not True:
        raise ValueError('API response did not succeed')
    result = response['result']
    data = unit_one(document(result['dataStr']))
    package = package or result.get('packageDetail')
    if not package:
        raise ValueError('missing footprint; fetch packageDetail or cache package_raw.json')
    fp = document(package['dataStr'])
    name = safe_name(result.get('title') or result['uuid'])
    sc, fc = Coordinates(data, True), Coordinates(fp)
    pins, pads, sg, fg = [], [], [], []
    for raw in fp.get('shape', []):
        try:
            if raw.startswith('PAD~'):
                pads.append(parse_pad(raw, fc))
            else:
                fg.extend(footprint_graphic(raw, fc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            log.warning('Skipping footprint element (%s): %s', e, raw)
    for raw in data.get('shape', []):
        try:
            if raw.startswith('P~'):
                pins.append(parse_pin(raw, sc))
            else:
                sg.extend(symbol_graphic(raw, sc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            log.warning('Skipping symbol element (%s): %s', e, raw)
    for number, count in Counter(p.number for p in pins).items():
        if count > 1:
            log.warning('Duplicate symbol pin number %s (%s records retained)', number, count)
    missing = {p.number for p in pins} - {p.number for p in pads}
    if missing:
        log.warning('Symbol pin numbers missing from footprint: %s', ', '.join(sorted(missing)))
    if not pins or not pads:
        raise ValueError('no usable pins or pads; refusing empty library')
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
    para = data['head'].get('c_para') or {}
    source = f'https://easyeda.com/component/{result["uuid"]}'
    properties = {'Reference': prefix(para.get('pre')), 'Value': result.get('title', name),
                  'Footprint': f'{name}:{name}', 'Datasheet': para.get('link') or '',
                  'Description': result.get('description') or '', 'Author': owner(result),
                  'Source': source, 'EasyEDA UUID': result['uuid']}
    center, value_y = symbol_label_position(data, sc, sg, pins)
    # Property angles are degrees; graphic text above uses deci-degrees.
    positions = {'Reference': (center, value_y + 2.54), 'Value': (center, value_y)}
    props = '\n'.join(
        f'(property {q(k)} {q(v)} (at {f(positions.get(k, (center, 0))[0])} '
        f'{f(positions.get(k, (center, 0))[1])} 0) {effects(hidden=k not in positions)})'
        for k, v in properties.items())
    symbol = (f'(kicad_symbol_lib (version 20231120) (generator "easyeda2kicad-local")\n'
              f'(symbol {q(name)} (pin_names (offset 0.508)) (in_bom yes) (on_board yes)\n{props}\n'
              f'(symbol {q(name + "_0_1")}\n' + '\n'.join(sg) + ')\n'
              f'(symbol {q(name + "_1_1")}\n' + '\n'.join(p.render() for p in pins) + ')\n))\n')
    heads = [data['head'], fp['head']]
    official = any((h.get('c_para') or {}).get('Contributor') == 'LCSC' or
                   any('official' in str(v).lower() for k, v in h.items() if 'license' in k.lower()) for h in heads)
    note = ('JLCEDA/EasyEDA Official Library - https://lceda.cn/ - https://easyeda.com' if official else
            f'Contributed by {owner(result)}, {owner(package)}; rights belong to the author(s); check before redistributing')
    credits = (f'Source: {source}\nTitle: {result.get("title", name)}\nSymbol author: {owner(result)}\n'
               f'Footprint author: {owner(package)}\nupdateTime: {result.get("updateTime", "unknown")}\n'
               f'Footprint updateTime: {package.get("updateTime", "unknown")}\nLicense note: {note}\n')
    return Conversion(name, pins, pads, symbol, footprint, credits)


def write_conversion(response, folder: Path, package=None):
    converted = convert_response(response, package)
    folder.mkdir(parents=True, exist_ok=True)
    pretty = folder / f'{converted.name}.pretty'
    pretty.mkdir(exist_ok=True)
    (pretty / f'{converted.name}.kicad_mod').write_text(converted.footprint, encoding='utf-8')
    (folder / f'{converted.name}.kicad_sym').write_text(converted.symbol, encoding='utf-8')
    (folder / 'CREDITS.txt').write_text(converted.credits, encoding='utf-8')
    return converted
