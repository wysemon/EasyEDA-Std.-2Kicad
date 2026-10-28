"""Small SVG path reader, including endpoint-to-center elliptical arcs."""

import math
import re

NUMBER = r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?'
MAX_GEOMETRY_CHARS = 1_000_000
MAX_GEOMETRY_POINTS = 100_000
MAX_POLYGON_VERTICES = 1_000


def check_polygon(points):
    """Reject ambiguous copper fills at the serialized one-nanometre precision.

    Exact integer cross products avoid floating tolerances at edge contacts.
    Bound the pairwise check rather than add a sweep-line geometry framework.
    """
    vertices = []
    for x, y in points:
        point = (round(x * 1_000_000), round(y * 1_000_000))
        if not vertices or point != vertices[-1]:
            vertices.append(point)
    if len(vertices) > 1 and vertices[-1] == vertices[0]:
        vertices.pop()
    if len(vertices) > MAX_POLYGON_VERTICES:
        raise ValueError('copper polygon exceeds supported intersection-check limit')
    if len(vertices) < 3:
        raise ValueError('degenerate copper polygon')

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(vertices, vertices[1:] + vertices[:1])) == 0:
        raise ValueError('degenerate copper polygon')
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    for i, (a, b) in enumerate(edges):
        c = vertices[(i + 2) % len(vertices)]
        if cross(a, b, c) == 0 and sum((x - y) * (z - y) for x, y, z in zip(a, b, c)) > 0:
            raise ValueError('overlapping copper polygon edges')
        for j in range(i + 2, len(edges)):
            if i == 0 and j == len(edges) - 1:
                continue  # Adjacent edges may share their one common endpoint.
            c, d = edges[j]
            if any(
                max(a[k], b[k]) < min(c[k], d[k]) or max(c[k], d[k]) < min(a[k], b[k])
                for k in (0, 1)
            ):
                continue
            ab = (cross(a, b, c), cross(a, b, d))
            cd = (cross(c, d, a), cross(c, d, b))
            if min(ab) <= 0 <= max(ab) and min(cd) <= 0 <= max(cd):
                raise ValueError('self-intersecting or touching copper polygon')


def numbers(text):
    if len(text) > MAX_GEOMETRY_CHARS:
        raise ValueError('geometry text exceeds supported size')
    values = []
    for match in re.finditer(NUMBER, text):
        if len(values) >= 2 * MAX_GEOMETRY_POINTS:
            raise ValueError('geometry exceeds supported point count')
        values.append(float(match[0]))
    return values


def point_pairs(text, minimum=2):
    """Require complete finite XY pairs; do not silently drop bad coordinates."""
    values = numbers(text)
    if (
        re.sub(NUMBER, '', text).strip(' \t\r\n,')
        or len(values) < 2 * minimum
        or len(values) % 2
        or not all(math.isfinite(v) for v in values)
    ):
        raise ValueError('invalid point-pair geometry')
    return list(zip(values[::2], values[1::2]))


def arc_points(start, values):
    """Convert SVG endpoint arc parameters to circular or sampled ellipse points.

    Follow the SVG endpoint-to-center construction, including radius correction:
    https://www.w3.org/TR/SVG/implnote.html#ArcImplementationNotes
    """
    rx, ry, rotation, large, sweep, x, y = values
    rx, ry = abs(rx), abs(ry)
    end = (x, y)
    if start == end:
        raise ValueError('coincident SVG arc endpoints')
    if not rx or not ry:
        return [start, end]
    phi = math.radians(rotation)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (start[0] - x) / 2, (start[1] - y) / 2
    xp, yp = c * dx + s * dy, -s * dx + c * dy
    # SVG enlarges undersized radii so the ellipse can reach both endpoints.
    scale = max(1, math.sqrt((xp / rx) ** 2 + (yp / ry) ** 2))
    rx, ry = rx * scale, ry * scale
    numerator = max(0, rx**2 * ry**2 - rx**2 * yp**2 - ry**2 * xp**2)
    denominator = rx**2 * yp**2 + ry**2 * xp**2
    # The two centers are disambiguated by the large-arc and sweep flags.
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
    count = 2 if math.isclose(rx, ry, rel_tol=1e-6) else max(8, math.ceil(abs(delta) / 0.1))
    result = []
    for i in range(count + 1):
        theta = a + delta * i / count
        result.append(
            (
                cx + c * rx * math.cos(theta) - s * ry * math.sin(theta),
                cy + s * rx * math.cos(theta) + c * ry * math.sin(theta),
            )
        )
    result[0], result[-1] = start, end
    return result


def path_segments(path, *, single_contour=False):
    """Yield (line|arc|ellipse, points) for M/L/H/V/A/Z. Reject other commands."""
    if len(path) > MAX_GEOMETRY_CHARS:
        raise ValueError('SVG path exceeds supported size')
    i, command, point, origin = 0, None, (0.0, 0.0), (0.0, 0.0)
    moves = point_count = 0
    closed = False

    def checked(kind, pts):
        nonlocal point_count
        point_count += len(pts)
        if point_count > MAX_GEOMETRY_POINTS:
            raise ValueError('SVG path exceeds supported point count')
        return kind, pts

    def skip_separators():
        nonlocal i
        while i < len(path) and (path[i].isspace() or path[i] == ','):
            i += 1

    def read_value(flag=False):
        nonlocal i
        skip_separators()
        # SVG flags are individual characters, even in "01" or "0110".
        if flag:
            if i >= len(path) or path[i] not in '01':
                raise ValueError('SVG arc flag must be 0 or 1')
            value = float(path[i])
            i += 1
            return value
        match = re.compile(NUMBER).match(path, i)
        if not match:
            raise ValueError('incomplete or invalid SVG coordinate')
        i = match.end()
        value = float(match[0])
        if not math.isfinite(value):
            raise ValueError('nonfinite SVG coordinate')
        return value

    while True:
        skip_separators()
        if i == len(path):
            break
        if path[i].isalpha():
            command = path[i]
            i += 1
        if command is None:
            raise ValueError('path has no command')
        upper = command.upper()
        if single_contour and closed:
            raise ValueError('compound filled SVG regions are unsupported')
        if upper == 'Z':
            if point != origin:
                yield checked('line', [point, origin])
            point, command = origin, None
            closed = True
            continue
        count = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'A': 7}.get(upper)
        if count is None:
            raise ValueError(f'unsupported SVG command {command}')
        values = [read_value(flag=upper == 'A' and index in (3, 4)) for index in range(count)]
        relative = command.islower()
        if upper in ('M', 'L'):
            end = (
                values[0] + (point[0] if relative else 0),
                values[1] + (point[1] if relative else 0),
            )
        elif upper == 'H':
            end = (values[0] + (point[0] if relative else 0), point[1])
        elif upper == 'V':
            end = (point[0], values[0] + (point[1] if relative else 0))
        else:
            if relative:
                values[-2] += point[0]
                values[-1] += point[1]
            pts = arc_points(point, values)
            yield checked('arc' if len(pts) == 3 else 'ellipse', pts)
            point = pts[-1]
            continue
        if upper == 'M':
            moves += 1
            if single_contour and moves > 1:
                raise ValueError('compound filled SVG regions are unsupported')
            origin = end
            command = 'l' if relative else 'L'
        else:
            yield checked('line', [point, end])
        point = end
