"""Shared units, strings, coordinates and drawing serialization helpers."""

import json
import logging
import math
import re
import unicodedata

from .files import MAX_INPUT_BYTES
from .geometry import path_segments

log = logging.getLogger(__name__)
# EasyEDA's drawing unit is 10 mil, irrespective of the editor's displayed grid.
UNIT = 0.254
MAX_SHAPES = 10_000


def num(value, default=0.0):
    """Apply source sentinels as defaults, but reject malformed/nonfinite values."""
    if value in (None, '', 'undefined'):
        return default
    value = float(str(value).removesuffix('pt'))
    if not math.isfinite(value):
        raise ValueError('nonfinite coordinate')
    return value


def f(value):
    """Keep serialization stable to six decimals, including a canonical zero."""
    value = round(value, 6)
    return str(value if value else 0)


def q(text):
    # KiCad strings use escaped double quotes and backslashes.
    return (
        '"'
        + str(text)
        .replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('\r', ' ')
        .replace('\n', '\\n')
        + '"'
    )


def safe_name(title):
    """Build a portable ASCII title; the caller appends the component identity."""
    ascii_title = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode()
    name = (
        re.sub(r'[^A-Za-z0-9_.-]+', '_', ascii_title).strip('._-')[:60].rstrip('._-') or 'component'
    )
    reserved = {
        'CON',
        'PRN',
        'AUX',
        'NUL',
        'CONIN$',
        'CONOUT$',
        *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10)),
    }
    if name.split('.')[0].upper() in reserved:
        name = '_' + name[:59]
    return name


def document(value):
    """Accept dataStr as either an API object or its JSON-encoded string form."""
    if isinstance(value, str) and len(value) > MAX_INPUT_BYTES:
        raise ValueError('source document exceeds supported size')
    data = json.loads(value) if isinstance(value, str) else value
    shapes = data.get('shape', [])
    if len(shapes) > MAX_SHAPES or sum(len(s) for s in shapes) > MAX_INPUT_BYTES:
        raise ValueError('component geometry exceeds supported size')
    return data


def prefix(value):
    return re.sub(r'\d+$', '', (value or '').replace('?', '')) or 'U'


def effects(size=1.27, hidden=False, justify=None):
    alignment = f' (justify {justify})' if justify else ''
    return f'(effects (font (size {f(size)} {f(size)})){alignment}{" hide" if hidden else ""})'


class Coordinates:
    """Translate source points to local KiCad mm using a verified document origin.

    Symbol coordinates reflect Y into KiCad's upward axis. Footprints keep the
    source Y-down axis. Resolve each missing head coordinate independently from
    the canvas; a valid explicit zero is never treated as a missing origin.
    """

    def __init__(self, data, symbol=False):
        head = data['head']
        canvas = data.get('canvas')
        fields = canvas.split('~') if isinstance(canvas, str) else []
        # CA layouts differ between symbol and footprint documents. These
        # zero-based origin fields are verified against all six real fixtures.
        indices = (13, 14) if symbol else (16, 17)
        resolved = []
        fallbacks = []
        for key, index in zip(('x', 'y'), indices):
            candidates = [(head.get(key), 'head')]
            if fields and fields[0] == 'CA' and len(fields) > index:
                candidates.append((fields[index], 'canvas'))
            for value, source in candidates:
                if value in (None, '', 'undefined'):
                    continue
                try:
                    coordinate = num(value)
                except (TypeError, ValueError):
                    continue
                resolved.append(coordinate)
                if source != 'head':
                    fallbacks.append(f'{key} from {source}')
                break
            else:
                raise ValueError(f'Cannot determine {key} origin from head or canvas')
        self.x, self.y = resolved
        self.sign = -1 if symbol else 1
        if fallbacks:
            log.warning(
                'Missing or invalid head origin; using %s (origin %s, %s).',
                ', '.join(fallbacks),
                f(self.x),
                f(self.y),
            )

    def point(self, x, y):
        point = ((num(x) - self.x) * UNIT, (num(y) - self.y) * UNIT * self.sign)
        if not all(math.isfinite(v) for v in point):
            raise ValueError('nonfinite converted coordinate')
        return point

    def xy(self, x, y):
        return ' '.join(map(f, self.point(x, y)))


def stroke(width):
    return f'(stroke (width {f(max(0.01, width))}) (type default))'


def fill(value):
    return (
        '(fill (type none))' if value in ('', 'none', 'undefined') else '(fill (type background))'
    )


def poly(points, width, symbol, layer_name='F.Fab', solid=False):
    pts = ' '.join(f'(xy {f(x)} {f(y)})' for x, y in points)
    if symbol:
        return f'(polyline (pts {pts}) {stroke(width)} (fill (type {"background" if solid else "none"})))'
    return f'(fp_poly (pts {pts}) {stroke(width)} (fill {"solid" if solid else "none"}) (layer {q(layer_name)}))'


def svg_graphics(path, coords, width, symbol, layer_name='F.Fab', solid=False):
    segments = list(path_segments(path, single_contour=solid))
    if solid:
        if any(kind != 'line' for kind, _ in segments):
            raise ValueError('curved solid region not supported')
        if not segments:
            raise ValueError('empty solid region')
        points = [tuple(round(v, 6) for v in coords.point(*segments[0][1][0]))]
        points.extend(tuple(round(v, 6) for v in coords.point(*pts[-1])) for _, pts in segments)
        # Shift before computing area to avoid cancellation at large origins.
        x0, y0 = points[0]
        local = [(x - x0, y - y0) for x, y in points]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(local, local[1:] + local[:1]))
        if len(set(points)) < 3 or not math.isfinite(area) or area == 0:
            raise ValueError('empty or degenerate solid region')
        return [poly(points, width, symbol, layer_name, True)]
    result = []
    for kind, pts in segments:
        # Check the actual serialized precision, not sub-micrometre differences
        # that would become coincident copper vertices in the output.
        pts = [tuple(round(v, 6) for v in coords.point(*p)) for p in pts]
        if not any(p != pts[0] for p in pts[1:]):
            continue
        if kind == 'arc':
            start, mid, end = pts
            body = (
                f'(start {f(start[0])} {f(start[1])}) '
                f'(mid {f(mid[0])} {f(mid[1])}) (end {f(end[0])} {f(end[1])}) {stroke(width)}'
            )
            result.append(
                f'(arc {body} (fill (type none)))'
                if symbol
                else f'(fp_arc {body} (layer {q(layer_name)}))'
            )
        elif kind == 'line' and not symbol:
            result.append(
                f'(fp_line (start {f(pts[0][0])} {f(pts[0][1])}) '
                f'(end {f(pts[1][0])} {f(pts[1][1])}) {stroke(width)} (layer {q(layer_name)}))'
            )
        else:
            if kind == 'ellipse':
                log.warning('Approximating elliptical SVG arc as a polyline: %s', path)
            result.append(poly(pts, width, symbol, layer_name))
    return result


def short_description(text):
    text = ' '.join(text.split())
    return text if len(text) <= 80 else text[:77] + '...'
