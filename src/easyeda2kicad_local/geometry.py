"""Small SVG path reader, including endpoint-to-center elliptical arcs."""
import math
import re

NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"


def numbers(text):
    return [float(n) for n in re.findall(NUMBER, text)]


def arc_points(start, values):
    rx, ry, rotation, large, sweep, x, y = values
    rx, ry = abs(rx), abs(ry)
    end = (x, y)
    if start == end:
        raise ValueError("coincident SVG arc endpoints")
    if not rx or not ry:
        return [start, end]
    phi = math.radians(rotation)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - x) / 2, (start[1] - y) / 2
    xp, yp = c * dx + s * dy, -s * dx + c * dy
    scale = max(1, math.sqrt((xp / rx) ** 2 + (yp / ry) ** 2))
    rx, ry = rx * scale, ry * scale
    numerator = max(0, rx**2 * ry**2 - rx**2 * yp**2 - ry**2 * xp**2)
    denominator = rx**2 * yp**2 + ry**2 * xp**2
    factor = (-1 if bool(large) == bool(sweep) else 1) * math.sqrt(numerator / denominator)
    cxp, cyp = factor * rx * yp / ry, -factor * ry * xp / rx
    cx = c * cxp - s * cyp + (start[0] + x) / 2
    cy = s * cxp + c * cyp + (start[1] + y) / 2
    a = math.atan2((yp - cyp) / ry, (xp - cxp) / rx)
    b = math.atan2((-yp - cyp) / ry, (-xp - cxp) / rx)
    delta = (b - a) % (2 * math.pi)
    if not sweep:
        delta -= 2 * math.pi
    # Circular arcs need exactly a midpoint; ellipses are approximated explicitly.
    count = 2 if math.isclose(rx, ry, rel_tol=1e-6) else max(8, math.ceil(abs(delta) / .1))
    result = []
    for i in range(count + 1):
        theta = a + delta * i / count
        result.append((cx + c * rx * math.cos(theta) - s * ry * math.sin(theta),
                       cy + s * rx * math.cos(theta) + c * ry * math.sin(theta)))
    result[0], result[-1] = start, end
    return result


def path_segments(path):
    """Yield (line|arc|ellipse, points) for M/L/H/V/A/Z. Reject other commands."""
    tokens = re.findall(rf"[a-df-zA-DF-Z]|{NUMBER}", path)
    i, command, point, origin = 0, None, (0., 0.), (0., 0.)
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        if command is None:
            raise ValueError("path has no command")
        upper = command.upper()
        if upper == 'Z':
            if point != origin:
                yield 'line', [point, origin]
            point, command = origin, None
            continue
        count = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'A': 7}.get(upper)
        if count is None:
            raise ValueError(f"unsupported SVG command {command}")
        values = list(map(float, tokens[i:i + count]))
        if len(values) != count:
            raise ValueError("incomplete SVG command")
        i += count
        relative = command.islower()
        if upper in ('M', 'L'):
            end = (values[0] + (point[0] if relative else 0),
                   values[1] + (point[1] if relative else 0))
        elif upper == 'H':
            end = (values[0] + (point[0] if relative else 0), point[1])
        elif upper == 'V':
            end = (point[0], values[0] + (point[1] if relative else 0))
        else:
            if relative:
                values[-2] += point[0]
                values[-1] += point[1]
            pts = arc_points(point, values)
            yield ('arc' if len(pts) == 3 else 'ellipse'), pts
            point = pts[-1]
            continue
        if upper == 'M':
            origin = end
            command = 'l' if relative else 'L'
        else:
            yield 'line', [point, end]
        point = end
