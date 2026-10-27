"""Courtyards enclose physical geometry, independently of BBox and text."""
import math

import pytest
from test_pad_orientation import CASES, document, world_vertices
from test_symbol_layout import children, one, sexpr

from easyeda2kicad_local.bounds import arc_extrema, courtyard
from easyeda2kicad_local.converter import convert_response
from easyeda2kicad_local.footprint import Pad, parse_pad
from easyeda2kicad_local.shared import Coordinates


def pad(**kwargs):
    fields = dict(number='1', x=0, y=0, width=2, height=4, drill=0, hole_length=0,
                  angle=0, shape='rect', kind='smd', layers='"F.Cu"', polygon=[])
    return Pad(**(fields | kwargs))


def test_extending_body_lines_holes_circles_and_arcs_are_included():
    graphics = ['(fp_line (start -10 -5) (end 10 -5) (stroke (width 0.2)) (layer "F.SilkS"))',
                '(fp_circle (center 0 8) (end 2 8) (stroke (width 0.2)) (layer "F.Fab"))',
                '(fp_arc (start -3 0) (mid 0 -3) (end 3 0) (stroke (width 0.2)) (layer "Edge.Cuts"))',
                '(pad "" np_thru_hole circle (at 12 0) (size 2 2) (drill 2))']
    assert courtyard([pad()], graphics) == pytest.approx((-10.35, -5.35, 13.25, 10.35))


def test_far_text_documentation_and_marking_do_not_enlarge_courtyard():
    irrelevant = ['(fp_text user "far label" (at 999 999) (layer "F.SilkS"))',
                  '(fp_rect (start -999 -999) (end 999 999) (layer "Dwgs.User"))',
                  '(fp_rect (start -999 -999) (end 999 999) (layer "User.5"))']
    assert courtyard([pad()], irrelevant) == pytest.approx((-1.25, -2.25, 1.25, 2.25))


@pytest.mark.parametrize('bbox', [None, {}, {'x': -999999, 'y': -999999, 'width': 9999999, 'height': 9999999}])
def test_stale_or_missing_source_bbox_cannot_distort_courtyard(response, bbox):
    expected = convert_response(response).footprint
    response['result']['packageDetail']['dataStr']['BBox'] = bbox
    assert convert_response(response).footprint == expected


@pytest.mark.parametrize('case,raw', CASES)
def test_real_rotated_rectangles_and_slots_fit_courtyard(case, raw):
    coords = Coordinates(document(case, raw))
    p = parse_pad(raw, coords)
    box = courtyard([p], [])
    angle = math.radians(-p.angle)
    for x, y in [(-p.width / 2, -p.height / 2), (p.width / 2, p.height / 2),
                 (-p.width / 2, p.height / 2), (p.width / 2, -p.height / 2)]:
        x, y = p.x + x * math.cos(angle) - y * math.sin(angle), p.y + x * math.sin(angle) + y * math.cos(angle)
        assert box[0] <= x - .25 <= x + .25 <= box[2]
        assert box[1] <= y - .25 <= y + .25 <= box[3]


def test_custom_polygon_uses_real_vertices_not_nominal_size():
    p = pad(width=1, height=1, angle=37, polygon=[(-8, -2), (6, -2), (3, 5)])
    minx, miny, maxx, maxy = courtyard([p], [])
    for x, y in world_vertices(p):
        assert minx <= x - .25 <= x + .25 <= maxx
        assert miny <= y - .25 <= y + .25 <= maxy
    assert maxx - minx > 10


def test_arc_bounds_include_quadrants_without_including_unused_circle():
    points = arc_extrema((1, 0), (math.sqrt(.5), math.sqrt(.5)), (0, 1))
    assert min(x for x, y in points) >= -1e-10
    assert min(y for x, y in points) >= -1e-10
    assert max(x for x, y in points) == pytest.approx(1)
    assert max(y for x, y in points) == pytest.approx(1)
    major = arc_extrema((1, 0), (-1, 0), (0, 1))
    assert min(x for x, y in major) == pytest.approx(-1)
    assert min(y for x, y in major) == pytest.approx(-1)


def test_generated_courtyard_is_one_closed_native_rectangle(response):
    fp = sexpr(convert_response(response).footprint)
    rects = [r for r in children(fp, 'fp_rect') if one(r, 'layer')[1] == 'F.CrtYd']
    assert len(rects) == 1
    for value in one(rects[0], 'start')[1:] + one(rects[0], 'end')[1:]:
        assert float(value) / .05 == pytest.approx(round(float(value) / .05))
    assert float(one(one(rects[0], 'stroke'), 'width')[1]) == .05
