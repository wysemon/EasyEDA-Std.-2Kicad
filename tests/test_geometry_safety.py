"""Regression checks for filled contours, plating and essential copper records."""

import json

import pytest
from test_workflow import install_cache, snapshot

from euc2k.converter import convert_response, write_conversion
from euc2k.footprint import parse_pad
from euc2k.publication import libraries_complete
from euc2k.sexpr import children, loads
from euc2k.shared import Coordinates, svg_graphics
from euc2k.workflow import run_items


@pytest.fixture
def coords():
    return Coordinates({'head': {'x': 0, 'y': 0}})


@pytest.mark.parametrize(
    'path',
    [
        'M0 0h10v10h-10z M20 0h10v10h-10z',  # Separate islands.
        'M0 0h10v10h-10z M2 2v6h6v-6z',  # A hole needs winding semantics.
        'M0 0L10 0L10 10 M10 10L0 10Z',  # Coincident moves are still contours.
        'M0 0h10v10z L20 20',  # Drawing after close starts a new contour.
    ],
)
def test_compound_fills_never_become_one_polygon(coords, path):
    with pytest.raises(ValueError, match='compound filled SVG'):
        svg_graphics(path, coords, 0.1, False, 'F.Cu', solid=True)


def test_single_fill_and_separate_strokes_preserve_geometry(coords):
    fill = svg_graphics('M0 0h10v10h-10z', coords, 0.1, False, 'F.Cu', solid=True)
    assert len(fill) == 1
    points = children(children(loads(fill[0]), 'pts')[0], 'xy')
    assert [list(map(float, p[1:])) for p in points] == [
        [0, 0],
        [2.54, 0],
        [2.54, 2.54],
        [0, 2.54],
        [0, 0],
    ]
    strokes = svg_graphics('M0 0h10 M20 0h10', coords, 0.1, False, 'F.Cu')
    assert len(strokes) == 2
    assert [list(map(float, children(loads(s), 'start')[0][1:])) for s in strokes] == [
        [0, 0],
        [5.08, 0],
    ]


@pytest.mark.parametrize('layer', ['1', '2', '21'])
def test_compound_copper_is_essential(response, layer):
    response['result']['packageDetail']['dataStr']['shape'].append(
        f'SOLIDREGION~{layer}~~M0 0h10v10z M20 0h10v10z~solid'
    )
    with pytest.raises(ValueError, match='invalid essential footprint SOLIDREGION'):
        convert_response(response)


def test_unsupported_decorative_fill_warns_without_bridging(response, caplog):
    expected = convert_response(response)
    response['result']['packageDetail']['dataStr']['shape'].append(
        'SOLIDREGION~3~~M0 0h10v10z M20 0h10v10z~solid'
    )
    assert convert_response(response) == expected
    assert 'compound filled SVG' in caplog.text


@pytest.mark.parametrize(
    'flag,kind',
    [(v, 'thru_hole') for v in ('Y', 'y', 'yes', 'YES', 'True', 'true', '1')]
    + [(v, 'np_thru_hole') for v in ('N', 'n', 'no', 'NO', 'False', 'false', '0')],
)
def test_explicit_plating_flags(response, flag, kind):
    doc = response['result']['packageDetail']['dataStr']
    fields = next(r for r in doc['shape'] if r.startswith('PAD~')).split('~')
    fields[15] = flag
    pad = parse_pad('~'.join(fields), Coordinates(doc))
    assert pad.kind == kind and pad.drill > 0


@pytest.mark.parametrize('flag', ['', 'undefined', 'NPTH', 'malformed'])
def test_unknown_plating_defaults_to_plated_with_warning(response, flag, caplog):
    doc = response['result']['packageDetail']['dataStr']
    fields = next(r for r in doc['shape'] if r.startswith('PAD~')).split('~')
    fields[15] = flag
    pad = parse_pad('~'.join(fields), Coordinates(doc))
    assert pad.kind == 'thru_hole'
    assert 'defaulting to plated' in caplog.text


def test_missing_plating_defaults_to_plated(response, caplog):
    doc = response['result']['packageDetail']['dataStr']
    raw = next(r for r in doc['shape'] if r.startswith('PAD~'))
    assert parse_pad('~'.join(raw.split('~')[:15]), Coordinates(doc)).kind == 'thru_hole'
    assert 'defaulting to plated' in caplog.text


@pytest.mark.parametrize(
    'raw',
    [
        'ARC~1~1~~~',
        'ARC~1~2~~M0 0',
        'ARC~1~1~~M0 0Z',
        'ARC~1~1~~M0 0L0 0',
        'ARC~1~1~~M0 0L0.000000001 0',
        'TRACK~1~1~~0 0 0 0',
        'TRACK~1~1~~0 0 0.000000001 0',
        'SOLIDREGION~1~~~solid',
        'SOLIDREGION~1~~M0 0L10 0L20 0Z~solid',
        'SOLIDREGION~1~~M0 0h0.000000001v10z~solid',
        'RECT~0~0~0~10~1',
        'RECT~0~0~0.000000001~10~1',
        'CIRCLE~0~0~0~1~2',
        'CIRCLE~0~0~0.000000001~1~2',
        'TEXT~L~0~0~0.6~0~0~1~~5',
        'TEXT~L~0~0~0.6~0~0~1~~5~   ',
        'TEXT~L~0~0~0.6~0~0~1~~0~label',
        'TEXT~L~0~0~0.6~0~0~1~~0.000000001~label',
        'TEXT~L~0~0~0.6~0~0~1~~bad~label',
        'TEXT~L~0~0~0.6~0~0~1~~~label',
        'TEXT~L~0~0~0.6~0~0~1~~undefined~label',
        'TEXT~L~0~0~0~0~0~1~~5~label',
        'TEXT~L~0~0~bad~0~0~1~~5~label',
        'TEXT~L~0~0~0.6~0~yes~1~~5~label',
        'TEXT~L~0~0~0.6~0~0~21~~5~label',
        'TEXT~L~nan~0~0.6~0~0~2~~5~label',
    ],
)
def test_empty_or_unsupported_copper_fails_whole_component(response, raw):
    response['result']['packageDetail']['dataStr']['shape'].append(raw)
    with pytest.raises(ValueError, match='invalid essential footprint'):
        convert_response(response)


@pytest.mark.parametrize('layer', ['1', '2'])
def test_supported_copper_text_is_retained(response, layer):
    response['result']['packageDetail']['dataStr']['shape'].append(
        f'TEXT~L~0~0~0.6~0~0~{layer}~~5~copper label'
    )
    footprint = loads(convert_response(response).footprint)
    label = next(t for t in children(footprint, 'fp_text') if t[2] == 'copper label')
    assert children(label, 'layer') == [['layer', 'F.Cu' if layer == '1' else 'B.Cu']]


def test_coordinate_overflow_cannot_publish_nonfinite_copper(response):
    doc = response['result']['packageDetail']['dataStr']
    doc['head']['x'] = -1e308
    doc['shape'].insert(0, 'SOLIDREGION~1~~M1e308 0L1e308 1L1e307 1Z~solid')
    with pytest.raises(ValueError, match='invalid essential footprint SOLIDREGION.*nonfinite'):
        convert_response(response)


def test_rejected_copper_keeps_previous_libraries_and_exact_cache(response, tmp_path):
    folder, original = install_cache(tmp_path, response)
    write_conversion(response, folder, sources={'raw.json': original})
    response['result']['packageDetail']['dataStr']['shape'].append(
        'SOLIDREGION~1~~M0 0h10v10z M20 0h10v10z~solid'
    )
    raw = json.dumps(response, indent=2).encode() + b'\n'
    (folder / 'raw.json').write_bytes(raw)
    before = snapshot(folder)
    assert run_items([response['result']['uuid']], tmp_path, cached_only=True) == 1
    assert snapshot(folder) == before
    assert not libraries_complete(folder)  # Cached bytes no longer match the committed hash.


@pytest.mark.kicad
def test_native_kicad_accepts_supported_fill_text_and_both_plating_flags(response, tmp_path):
    doc = response['result']['packageDetail']['dataStr']
    fields = next(r for r in doc['shape'] if r.startswith('PAD~')).split('~')
    fields[8], fields[15] = 'NPTH', 'N'
    doc['shape'].extend(
        [
            '~'.join(fields),
            'SOLIDREGION~1~~M0 0h10v10h-10z~solid',
            'TEXT~L~20~20~0.6~0~0~2~~5~copper label',
        ]
    )
    write_conversion(response, tmp_path / 'native', validate=True)
    assert libraries_complete(tmp_path / 'native')
