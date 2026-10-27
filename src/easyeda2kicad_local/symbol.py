"""EasyEDA symbol pins, geometry, layout and KiCad library serialization."""

import json
import logging
import math
import re
from dataclasses import dataclass

from .credits import owner
from .geometry import numbers, path_segments
from .shared import (
    MAX_SHAPES,
    UNIT,
    document,
    effects,
    f,
    fill,
    num,
    poly,
    prefix,
    q,
    short_description,
    stroke,
    svg_graphics,
)

log = logging.getLogger(__name__)
SYMBOL_TEXT_SIZE_CAP = 75 * 0.0254


@dataclass
class Pin:
    """A connected pin in local mm, with a Y-up direction in degrees.

    Keep the original name even when rendering it hidden, for stored metadata.
    Pin numbers always remain visible, independently of unreliable source flags.
    """

    number: str
    name: str
    x: float
    y: float
    angle: int
    length: float
    electrical: str
    style: str = 'line'
    name_visible: bool = True

    def render(self):
        # KiCad ignores hide inside pin-name effects; '~' is its blank-name marker.
        name = self.name if self.name_visible else '~'
        return (
            f'(pin {self.electrical} {self.style} (at {f(self.x)} {f(self.y)} {self.angle}) '
            f'(length {f(self.length)}) (name {q(name)} {effects()}) '
            f'(number {q(self.number)} {effects()}))'
        )


def parse_pin(raw, coords):
    """Read a P record's subsections and derive direction from its straight path."""
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
    if not number:
        raise ValueError('pin number is empty')
    electrical_types = {
        '0': 'unspecified',
        '1': 'input',
        '2': 'output',
        '3': 'bidirectional',
        '4': 'passive',
    }
    electrical = electrical_types.get(main[2], 'unspecified')
    if main[2] not in (*electrical_types, '', 'undefined'):
        log.warning('Unknown electrical type %r for pin %s; using unspecified.', main[2], number)
    inverted = len(sections) > 5 and sections[5][0] == '1'
    clock = len(sections) > 6 and sections[6][0] == '1'
    style = (
        'inverted_clock'
        if inverted and clock
        else 'inverted'
        if inverted
        else 'clock'
        if clock
        else 'line'
    )
    return Pin(number, name, x, y, angle, length, electrical, style, sections[3][0] != '0')


def symbol_text_angle(value):
    """Reflect source degrees into KiCad graphic-text tenths of a degree."""
    # Stock SSM2018 graphic text: 900 = 90 degrees; property angles use 90.
    # Reflect the EasyEDA Y-down orientation into symbol Y-up before scaling.
    return f'{(-num(value) % 360) * 10:g}'


def symbol_graphic(raw, coords):
    t = raw.split('~')
    kind = t[0]
    if kind == 'R':
        x, y = num(t[1]), num(t[2])
        return [
            f'(rectangle (start {coords.xy(x, y)}) (end {coords.xy(x + num(t[5]), y + num(t[6]))}) '
            f'{stroke(num(t[8], 1) * UNIT)} {fill(t[10])})'
        ]
    if kind in ('E', 'C'):
        x, y, rx = num(t[1]), num(t[2]), num(t[3])
        ry = num(t[4], rx) if kind == 'E' else rx
        if rx != ry:
            pts = [
                coords.point(
                    x + rx * math.cos(i * math.pi / 32), y + ry * math.sin(i * math.pi / 32)
                )
                for i in range(65)
            ]
            return [poly(pts, 0.254, True)]
        wi, fi = (6, 8) if kind == 'E' else (5, 7)
        return [
            f'(circle (center {coords.xy(x, y)}) (radius {f(rx * UNIT)}) {stroke(num(t[wi], 1) * UNIT)} {fill(t[fi])})'
        ]
    if kind == 'T':
        # Symbol fonts use points. This cap intentionally excludes footprint
        # text, pin labels and properties, which have different size policies.
        size = min(num(t[7], 9) * 25.4 / 72, SYMBOL_TEXT_SIZE_CAP)
        return [
            f'(text {q(t[12])} (at {coords.xy(t[2], t[3])} {symbol_text_angle(t[4])}) '
            f'{effects(size)})'
        ]
    if kind in ('PL', 'PG'):
        ns = numbers(t[1])
        points = [coords.point(x, y) for x, y in zip(ns[::2], ns[1::2])]
        if kind == 'PG' and points:
            points.append(points[0])
        return [poly(points, num(t[3], 1) * UNIT, True, solid=kind == 'PG')]
    if kind in ('PT', 'A'):
        return svg_graphics(t[1], coords, num(t[3], 1) * UNIT, True)
    raise ValueError(f'unsupported symbol element {kind}')


def symbol_label_position(data, coords, graphics, pins, below=False):
    """Center over body geometry; clear the entire converted drawing and pins.

    Generated primitives are already in KiCad mm. The source BBox is included
    as an extra guard, but geometry still works when BBox is missing or stale.
    Text uses a conservative one-em-per-character envelope, not just its anchor.
    """
    body, outer = [], []
    for graphic in graphics:
        points = (
            []
            if graphic.startswith('(text ')
            else [
                tuple(numbers(point))
                for point in re.findall(r'\((?:start|end|mid|xy|center) ([^)]*)\)', graphic)
            ]
        )
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
            match = re.search(
                r'^\(text ("(?:\\.|[^"\\])*") \(at ([^)]*)\).*?\(size ([^)]*)\)', graphic
            )
            text = json.loads(match[1], strict=False)
            x, y, angle = numbers(match[2])
            width, height = numbers(match[3])
            lines = text.splitlines() or ['']
            half_width = max(map(len, lines)) * width / 2
            half_height = len(lines) * height * 0.75
            a = math.radians(angle / 10)
            dx = abs(half_width * math.cos(a)) + abs(half_height * math.sin(a))
            dy = abs(half_width * math.sin(a)) + abs(half_height * math.cos(a))
            outer.extend([(x - dx, y - dy), (x + dx, y + dy)])
    for pin in pins:
        a = math.radians(pin.angle)
        outer.extend(
            [(pin.x, pin.y), (pin.x + pin.length * math.cos(a), pin.y + pin.length * math.sin(a))]
        )
    box = data.get('BBox') or {}
    if box:
        outer.extend(
            [
                coords.point(box['x'], box['y']),
                coords.point(num(box['x']) + num(box['width']), num(box['y']) + num(box['height'])),
            ]
        )
    centered = body or outer
    center = (min(x for x, _ in centered) + max(x for x, _ in centered)) / 2
    if below:
        return min(x for x, _ in centered), min(y for _, y in outer) - 2.54
    top = max(y for _, y in outer)
    return center, top + 2.54


def unit_one(data):
    """Require a single unit; retain this historical helper name for callers."""
    if not data.get('subparts'):
        return data
    raise ValueError(
        'Multi-unit symbols (nonempty subparts) are not supported; refusing a partial unit-1 library. Use a verified single-unit source.'
    )


def symbol_units(result):
    """Read verified result.subparts; its first document replaces the parent copy.

    The STM32 fixture repeats unit 1 in result.dataStr. Unit numbers follow list
    order, not c_para.subpart_no (both of its units incorrectly say '1').
    Reject incomplete/unknown layouts instead of silently keeping a parent unit.
    """
    parent = unit_one(document(result['dataStr']))
    parts = result.get('subparts')
    if not parts:
        return [parent]
    try:
        if not isinstance(parts, list) or len(parts) > 100:
            raise ValueError('expected a list of at most 100 complete unit documents')
        units = []
        for index, part in enumerate(parts, 1):
            if not isinstance(part, dict) or not part.get('dataStr'):
                raise ValueError(f'unit {index} is missing dataStr')
            unit = unit_one(document(part['dataStr']))
            if not isinstance(unit.get('head'), dict) or not isinstance(unit.get('shape'), list):
                raise ValueError(f'unit {index} is missing head/shape')
            if unit.get('subparts') or part.get('subparts'):
                raise ValueError(f'unit {index} has unsupported nested subparts')
            if not any(raw.startswith('P~') for raw in unit['shape']):
                raise ValueError(f'unit {index} has no pins')
            units.append(unit)
        if parent.get('shape') and parent['shape'] != units[0]['shape']:
            raise ValueError('parent geometry differs from unit 1')
        if sum(len(unit['shape']) for unit in units) > MAX_SHAPES:
            raise ValueError('combined units exceed supported shape count')
        return units
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f'Multi-unit symbol: {e}; refusing a partial library') from e


def render_symbol(result, data, name, sc, sg, pins, *, has_footprint=True, units=None):
    """Render body, pins and source metadata with a matching footprint reference."""
    para = data['head'].get('c_para') or {}
    source = f'https://easyeda.com/component/{result["uuid"]}'
    properties = {
        'Reference': prefix(para.get('pre')),
        'Value': result.get('title', name),
        'Footprint': f'{name}:{name}' if has_footprint else '',
        'Datasheet': para.get('link') or '',
        'Description': short_description(result.get('description') or ''),
        'Author': owner(result),
        'Source': source,
        'EasyEDA UUID': result['uuid'],
    }
    hidden_names = [
        {'number': pin.number, 'name': pin.name} for pin in pins if not pin.name_visible
    ]
    if hidden_names:
        properties['EasyEDA Hidden Pin Names'] = json.dumps(hidden_names, ensure_ascii=False)
    first_data, first_coords, first_graphics, first_pins = (
        units[0] if units else (data, sc, sg, pins)
    )
    center, value_y = symbol_label_position(first_data, first_coords, first_graphics, first_pins)
    # Property angles are degrees; graphic text above uses deci-degrees.
    positions = {'Reference': (center, value_y + 2.54), 'Value': (center, value_y)}
    hidden_x, hidden_y = symbol_label_position(data, sc, sg, pins, below=True)
    rows = []
    for key, value in properties.items():
        hidden = key not in positions
        x, y = (hidden_x, hidden_y) if hidden else positions[key]
        rows.append(
            f'(property {q(key)} {q(value)} (at {f(x)} {f(y)} 0) '
            f'{effects(hidden=hidden, justify="left" if hidden else None)})'
        )
        if hidden:
            hidden_y -= 1.27
    props = '\n'.join(rows)
    if units:
        body = (
            '\n'.join(
                f'(symbol {q(name + f"_{index}_1")}\n'
                + '\n'.join([*graphics, *(p.render() for p in unit_pins)])
                + ')'
                for index, (_, _, graphics, unit_pins) in enumerate(units, 1)
            )
            + '\n'
        )
    else:
        body = (
            f'(symbol {q(name + "_0_1")}\n' + '\n'.join(sg) + ')\n'
            f'(symbol {q(name + "_1_1")}\n' + '\n'.join(p.render() for p in pins) + ')\n'
        )
    symbol = (
        f'(kicad_symbol_lib (version 20231120) (generator "easyeda2kicad-local")\n'
        f'(symbol {q(name)} (pin_names (offset 0.508)) (in_bom yes) (on_board yes)\n{props}\n'
        + body
        + '))\n'
    )
    return symbol
