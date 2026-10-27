"""Real asymmetric pads/slots; derived custom-pad and back-side calibrations."""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_symbol_layout import one, sexpr

from easyeda2kicad_local.footprint import footprint_graphic, parse_pad, render_footprint
from easyeda2kicad_local.geometry import point_pairs
from easyeda2kicad_local.shared import Coordinates

ROOT = Path(__file__).parent
EXAMPLES = json.loads((ROOT / 'fixtures/geometry/real_pad_examples.json').read_bytes())
CASES = [
    (case, raw) for case in EXAMPLES['cases'] for raw in case['records'] if raw.startswith('PAD~')
]
NATIVE_CASES = (
    [(case, raw, 'real') for case, raw in CASES]
    + [(case, raw, 'custom-derived') for case, raw in CASES if raw.startswith('PAD~RECT')]
    + [(case, raw, 'back-derived') for case, raw in CASES if raw.split('~')[6] == '1']
)


def document(case, raw):
    return {
        'head': {
            'docType': '4',
            'x': case['origin'][0],
            'y': case['origin'][1],
            'c_para': {'package': 'orientation'},
        },
        'shape': [raw],
        'layers': [],
    }


def world_vertices(pad):
    a = math.radians(-pad.angle)
    return [
        (pad.x + x * math.cos(a) - y * math.sin(a), pad.y + x * math.sin(a) + y * math.cos(a))
        for x, y in pad.polygon
    ]


@pytest.mark.parametrize('case,raw', CASES, ids=[r.split('~')[12] for c, r in CASES])
def test_real_rectangles_and_slots_match_source_vertices(case, raw):
    coords = Coordinates(document(case, raw))
    pad = parse_pad(raw, coords)
    fields = raw.split('~')
    if fields[1] == 'RECT':
        assert pad.angle == 124
        # Actual source corner coordinates establish the sign; these are not
        # inferred from a round pad or from the converter's own output.
        corners = [
            (-pad.width / 2, -pad.height / 2),
            (pad.width / 2, -pad.height / 2),
            (pad.width / 2, pad.height / 2),
            (-pad.width / 2, pad.height / 2),
        ]
        pad.polygon = corners
        expected = [coords.point(x, y) for x, y in point_pairs(fields[10])]
        actual = world_vertices(pad)
        assert max(min(math.dist(p, q) for q in actual) for p in expected) < 0.0002
    else:
        assert pad.angle == 270 and pad.width < pad.height
        hole_centers = [coords.point(x, y) for x, y in point_pairs(fields[14])]
        assert abs(hole_centers[0][1] - hole_centers[1][1]) < 0.0001  # Horizontal in source.
        assert math.dist(*hole_centers) + pad.drill == pytest.approx(pad.hole_length, abs=0.0001)
        drill = one(sexpr(pad.render()), 'drill')
        assert drill[1] == 'oval'
        assert list(map(float, drill[2:])) == pytest.approx([0.649986, 2.000021], abs=1e-6)


@pytest.mark.parametrize('case,raw', [item for item in CASES if item[1].startswith('PAD~RECT')])
def test_custom_polygon_calibration_preserves_actual_source_corners(case, raw):
    fields = raw.split('~')
    fields[1] = 'POLYGON'  # Explicitly a derived calibration, not a new real component.
    coords = Coordinates(document(case, raw))
    pad = parse_pad('~'.join(fields), coords)
    expected = [coords.point(x, y) for x, y in point_pairs(fields[10])]
    assert all(math.dist(p, q) < 1e-8 for p, q in zip(world_vertices(pad), expected))


def test_real_rotated_text_keeps_source_angle_and_size():
    case = EXAMPLES['cases'][0]
    text = next(raw for raw in case['records'] if raw.startswith('TEXT~'))
    graphic = sexpr(footprint_graphic(text, Coordinates(document(case, text)))[0])
    assert float(one(graphic, 'at')[3]) == 124
    assert list(map(float, one(one(one(graphic, 'effects'), 'font'), 'size')[1:])) == pytest.approx(
        [1.143, 1.143]
    )


@pytest.fixture(scope='module')
def pcbnew_python():
    for executable in dict.fromkeys([sys.executable, '/usr/bin/python3']):
        if Path(executable).exists():
            probe = subprocess.run(
                [executable, '-c', 'import pcbnew'], capture_output=True, timeout=30
            )
            if probe.returncode == 0:
                return executable
    if os.environ.get('EE2KICAD_REQUIRE_PCBNEW'):
        pytest.fail('Native pad integration requires Python pcbnew bindings')
    pytest.skip('Optional native geometry integration requires Python pcbnew bindings')


@pytest.mark.kicad
@pytest.mark.parametrize(
    'case,raw,calibration',
    NATIVE_CASES,
    ids=[f'{kind}-{raw.split("~")[12]}' for case, raw, kind in NATIVE_CASES],
)
def test_native_easyeda_and_kicad_geometry_agree(case, raw, calibration, pcbnew_python, tmp_path):
    fields = raw.split('~')
    if calibration == 'custom-derived':
        fields[1] = 'POLYGON'
    elif calibration == 'back-derived':
        fields[6] = '2'
    raw = '~'.join(fields)
    data = document(case, raw)
    coords = Coordinates(data)
    pad = parse_pad(raw, coords)
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(data), encoding='utf-8')
    pretty = tmp_path / 'orientation.pretty'
    pretty.mkdir()
    (pretty / 'orientation.kicad_mod').write_text(
        render_footprint('orientation', data, coords, [pad], []), encoding='utf-8'
    )
    run = subprocess.run(
        [pcbnew_python, str(ROOT / 'helpers/native_pad_geometry.py'), str(source), str(pretty)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    original, generated = result['source'][0], result['generated'][0]
    assert len(original['outline']) >= 3 and len(generated['outline']) >= 3
    assert generated['number'] == original['number']
    assert generated['layers'] == original['layers']
    for key in ('at', 'drill'):
        assert generated[key] == pytest.approx(original[key], abs=0.0001)
    assert generated['angle'] == pytest.approx(original['angle'], abs=0.0001)
    if calibration != 'custom-derived':
        assert generated['size'] == pytest.approx(original['size'], abs=0.0001)
    if original['hole_bounds']:
        assert generated['hole_bounds'] == pytest.approx(original['hole_bounds'], abs=0.0001)
        assert (
            generated['hole_bounds'][0] > generated['hole_bounds'][1]
        )  # Source slot is horizontal.
    for point in original['outline']:
        assert min(math.dist(point, p) for p in generated['outline']) < 0.0002
