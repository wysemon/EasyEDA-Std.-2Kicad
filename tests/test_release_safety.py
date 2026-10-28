"""Reproduced final-audit failures and native compatibility regressions."""

import json

import pytest
from conftest import FIXTURES
from test_workflow import install_cache, snapshot

from euc2k import geometry
from euc2k.converter import convert_response, write_conversion
from euc2k.footprint import parse_pad
from euc2k.geometry import check_polygon
from euc2k.sexpr import children, loads
from euc2k.shared import Coordinates
from euc2k.workflow import run_items

RECORDS = [
    ('TRACK~{width}~1~~0 0 10 0', 'fp_line'),
    ('ARC~{width}~2~~M10 0A10 10 0 0 1 0 10', 'fp_arc'),
    ('CIRCLE~0~0~10~{width}~1', 'fp_circle'),
    ('TEXT~L~0~0~{width}~0~0~2~~5~label', 'fp_text'),
]


@pytest.mark.parametrize('raw,kind', RECORDS)
@pytest.mark.parametrize(
    'width', ['', 'undefined', '0', '-1', 'nan', 'inf', '1e999', 'bad', '1pt', '1e-10']
)
def test_copper_width_cannot_default_or_be_invented(response, raw, kind, width):
    response['result']['packageDetail']['dataStr']['shape'].append(raw.format(width=width))
    with pytest.raises(ValueError, match='invalid essential footprint'):
        convert_response(response)


@pytest.mark.parametrize('raw,kind', RECORDS)
def test_valid_narrow_copper_width_survives_without_clamping(response, raw, kind):
    response['result']['packageDetail']['dataStr']['shape'].append(raw.format(width='0.01'))
    nodes = children(loads(convert_response(response).footprint), kind)
    node = next(n for n in nodes if children(n, 'layer')[0][1] in ('F.Cu', 'B.Cu'))
    if kind == 'fp_text':
        font = children(children(node, 'effects')[0], 'font')[0]
        value = children(font, 'thickness')[0][1]
    else:
        value = children(children(node, 'stroke')[0], 'width')[0][1]
    assert float(value) == 0.00254


def test_optional_missing_width_keeps_its_decoration_default(response):
    response['result']['packageDetail']['dataStr']['shape'].append('TRACK~~3~~0 0 10 0')
    assert '(stroke (width 0.254)' in convert_response(response).footprint


@pytest.mark.parametrize(
    'points',
    [
        [(0, 0), (4, 4), (0, 4), (4, 0), (5, -1)],  # Crossing with nonzero signed area.
        [(0, 0), (4, 0), (2, 0), (2, 4), (0, 4)],  # Adjacent backtracking.
        [(0, 0), (4, 0), (4, 4), (2, 0), (0, 4)],  # Touching nonadjacent edges.
        [(0, 0), (4, 0), (4, 4), (0, 4), (4, 0)],  # Repeated nonadjacent vertex.
    ],
)
def test_ambiguous_copper_polygons_fail(points):
    with pytest.raises(ValueError, match='copper polygon'):
        check_polygon(points)


@pytest.mark.parametrize('reverse', [False, True])
def test_concave_simple_polygons_and_redundant_points_are_supported(reverse):
    points = [(0, 0), (2, 0), (4, 0), (4, 4), (2, 2), (0, 4), (0, 4), (0, 0)]
    check_polygon(points[::-1] if reverse else points)


def test_polygon_intersection_work_is_bounded(monkeypatch):
    monkeypatch.setattr(geometry, 'MAX_POLYGON_VERTICES', 3)
    check_polygon([(0, 0), (1, 0), (0, 1)])
    with pytest.raises(ValueError, match='intersection-check limit'):
        check_polygon([(0, 0), (1, 0), (1, 1), (0, 1)])


@pytest.mark.parametrize(
    'record',
    [
        'TRACK~0~1~~0 0 10 0',
        'SOLIDREGION~1~~M0 0L4 4L0 4L4 0L5 -1Z~solid',
    ],
)
def test_copper_failure_preserves_libraries_cache_and_user_files(response, tmp_path, record):
    folder, raw = install_cache(tmp_path, response)
    write_conversion(response, folder, sources={'raw.json': raw})
    response['result']['packageDetail']['dataStr']['shape'].append(record)
    (folder / 'raw.json').write_bytes(json.dumps(response).encode() + b'\r\n')
    (folder / 'user.txt').write_text('keep verbatim')
    before = snapshot(folder)
    assert run_items([response['result']['uuid']], tmp_path, cached_only=True) == 1
    assert snapshot(folder) == before


@pytest.mark.parametrize(
    'points',
    [
        '0 0 4 4 0 4 4 0 5 -1',  # Self-intersection.
        '10 10 20 10 15 20',  # Anchor outside an otherwise simple polygon.
        '-0.01 -5 5 -5 5 5 -0.01 5',  # Anchor crosses a source edge.
        '0 0 1 0 2 0',  # No copper area.
    ],
)
def test_custom_pad_cannot_add_anchor_copper_or_use_an_ambiguous_polygon(points):
    raw = f'PAD~POLYGON~0~0~4~4~1~~1~0~{points}~0~test~0~~Y'
    with pytest.raises(ValueError, match='polygon|anchor'):
        parse_pad(raw, Coordinates({'head': {'x': 0, 'y': 0}}))


@pytest.mark.parametrize(
    'raw',
    [
        'PAD~RECT~~0~4~4~1~~1~0~~0~test~0~~Y',
        'VIA~undefined~0~4~~1',
        'HOLE~0~~1',
    ],
)
def test_missing_electrical_positions_cannot_default_to_zero(response, raw):
    response['result']['packageDetail']['dataStr']['shape'].append(raw)
    with pytest.raises(ValueError, match='invalid essential footprint'):
        convert_response(response)


@pytest.mark.parametrize('points', ['-1 1 1 1', '0 -1 0 1', '-0.5 0 0.5 0'])
def test_slot_points_cannot_be_silently_recentered_reoriented_or_resized(points):
    raw = f'PAD~OVAL~0~0~6~4~11~~1~1~~0~test~4~{points}~Y'
    with pytest.raises(ValueError, match='unsupported.*slot'):
        parse_pad(raw, Coordinates({'head': {'x': 0, 'y': 0}}))


@pytest.mark.kicad
@pytest.mark.parametrize('path', sorted(FIXTURES.glob('*.json')), ids=lambda p: p.stem)
def test_all_real_fixtures_validate_without_modifying_generated_files(path, tmp_path):
    raw = path.read_bytes()
    response = json.loads(raw)
    folder = tmp_path / 'libraries'
    converted = write_conversion(response, folder, validate=True, sources={'raw.json': raw})
    assert (folder / f'{converted.name}.kicad_sym').read_text(encoding='utf-8') == converted.symbol
    if converted.footprint:
        assert (folder / f'{converted.name}.pretty' / f'{converted.name}.kicad_mod').read_text(
            encoding='utf-8'
        ) == converted.footprint
    else:
        assert not list(folder.glob('*.pretty'))
    assert (folder / 'raw.json').read_bytes() == raw
