"""Shared units, strings, coordinates and drawing serialization helpers."""
import json
import logging
import math
import re
import unicodedata

from .geometry import path_segments

log = logging.getLogger(__name__)
UNIT = .254


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



def effects(size=1.27, hidden=False, justify=None):
    alignment = f' (justify {justify})' if justify else ''
    return f'(effects (font (size {f(size)} {f(size)})){alignment}{" hide" if hidden else ""})'



class Coordinates:
    def __init__(self, data, symbol=False):
        self.x = num(data['head'].get('x'))
        self.y = num(data['head'].get('y'))
        self.sign = -1 if symbol else 1

    def point(self, x, y):
        return ((num(x) - self.x) * UNIT, (num(y) - self.y) * UNIT * self.sign)

    def xy(self, x, y):
        return ' '.join(map(f, self.point(x, y)))



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



def short_description(text):
    text = ' '.join(text.split())
    return text if len(text) <= 80 else text[:77] + '...'
