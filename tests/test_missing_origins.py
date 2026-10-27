"""Real regressions: origin-less ESP32 symbols must not be a metre from (0, 0)."""

import copy
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_symbol_layout import children, one, sexpr

from easyeda2kicad_local.converter import convert_response, write_conversion
from easyeda2kicad_local.shared import Coordinates

FIXTURES = Path(__file__).parent / 'fixtures'
ESP32_IDS = ['2e51d5a642224cf198048941f0630f26', 'dd15f28aa16b42c0803759cacb9683e8']


def load(uuid):
    return json.loads((FIXTURES / f'{uuid}.json').read_bytes())


def test_mechanical_layer_has_one_summary_without_changing_output(caplog):
    data = load(ESP32_IDS[1])
    before = copy.deepcopy(data)
    converted = convert_response(data)
    messages = [r.getMessage() for r in caplog.records if 'layer 15' in r.getMessage()]
    assert messages == [f'{ESP32_IDS[1]}: 13 elements on layer 15 skipped']
    assert data == before
    shapes = data['result']['packageDetail']['dataStr']['shape']
    mechanical = [
        raw
        for raw in shapes
        if (raw.startswith('TRACK~') and raw.split('~')[2] == '15')
        or (raw.startswith('TEXT~') and raw.split('~')[7] == '15')
    ]
    assert len(mechanical) == 13
    shapes[:] = [raw for raw in shapes if raw not in mechanical]
    assert convert_response(data) == converted


def test_mechanical_layer_does_not_hide_invalid_pads(response):
    shapes = response['result']['packageDetail']['dataStr']['shape']
    fields = next(raw for raw in shapes if raw.startswith('PAD~')).split('~')
    fields[6] = '15'
    shapes.append('~'.join(fields))
    with pytest.raises(
        ValueError, match='invalid essential footprint PAD.*unsupported pad layer 15'
    ):
        convert_response(response)


@pytest.mark.parametrize('uuid', ESP32_IDS)
def test_real_missing_symbol_origin_uses_canvas(uuid, caplog):
    data = load(uuid)
    symbol = data['result']['dataStr']
    assert 'x' not in symbol['head'] and 'y' not in symbol['head']
    coords = Coordinates(symbol, symbol=True)
    assert (coords.x, coords.y) == (3000.0, 4000.0)
    assert 'from canvas' in caplog.text
    c = convert_response(data)
    assert len(c.pins) == len(c.pads) == 16
    assert max(abs(v) for p in c.pins for v in (p.x, p.y)) < 20
    assert {p.number for p in c.pins} == {p.number for p in c.pads}
    properties = children(one(sexpr(c.symbol), 'symbol'), 'property')
    assert all(abs(float(value)) < 50 for p in properties for value in one(p, 'at')[1:3])
    if uuid == ESP32_IDS[0]:
        pin = next(p for p in c.pins if p.number == '16')
        assert (pin.x, pin.y, pin.length) == pytest.approx((13.97, 8.89, 2.54))
        ys = sorted(p.y for p in c.pins if p.x > 0)
        assert all(b - a == pytest.approx(2.54) for a, b in zip(ys, ys[1:]))
    else:
        pin = next(p for p in c.pins if p.number == '0')
        assert (pin.x, pin.y, pin.length) == pytest.approx((-17.78, 6.35, 5.08))
    # Filling in the omitted head origin must produce exactly the same conversion.
    complete = copy.deepcopy(data)
    complete['result']['dataStr']['head'].update(x=3000, y=4000)
    assert convert_response(complete) == c


@pytest.mark.parametrize('fixture', sorted(FIXTURES.glob('*.json')), ids=lambda p: p.stem)
@pytest.mark.parametrize('symbol', [True, False])
def test_canvas_origin_matches_explicit_origin_without_changing_scale(fixture, symbol):
    response = json.loads(fixture.read_bytes())['result']
    if not symbol and not response.get('packageDetail'):
        return  # A verified symbol-only source has no footprint origin.
    data = response['dataStr'] if symbol else response['packageDetail']['dataStr']
    original = Coordinates(data, symbol=symbol)
    without_head_origin = copy.deepcopy(data)
    without_head_origin['head'].pop('x', None)
    without_head_origin['head'].pop('y', None)
    fallback = Coordinates(without_head_origin, symbol=symbol)
    assert (fallback.x, fallback.y) == (original.x, original.y)
    # The unit conversion remains exactly 10 mil per source drawing unit.
    assert fallback.point(original.x + 10, original.y + 10) == pytest.approx(
        (2.54, -2.54 if symbol else 2.54)
    )


@pytest.mark.parametrize('missing', [None, '', 'undefined', 'invalid'])
def test_partial_head_origin_falls_back_per_axis(missing):
    data = load(ESP32_IDS[0])['result']['dataStr']
    data['head'].update(x=2990, y=missing)
    coords = Coordinates(data, symbol=True)
    assert (coords.x, coords.y) == (2990.0, 4000.0)


def test_explicit_zero_origin_is_preserved():
    data = load(ESP32_IDS[0])['result']['dataStr']
    data['head'].update(x=0, y=0)
    coords = Coordinates(data, symbol=True)
    assert (coords.x, coords.y) == (0.0, 0.0)


def test_unrecoverable_origin_fails_without_guessing():
    data = load(ESP32_IDS[0])['result']['dataStr']
    data.pop('canvas')
    with pytest.raises(ValueError, match='Cannot determine x origin from head or canvas'):
        Coordinates(data, symbol=True)


@pytest.mark.parametrize('uuid', ESP32_IDS)
@pytest.mark.kicad
def test_kicad_import_preserves_near_origin_geometry(uuid, tmp_path):
    executable = shutil.which('kicad-cli')
    if not executable:
        pytest.skip('Optional native KiCad import regression')
    c = write_conversion(load(uuid), tmp_path / 'libraries')
    symbol = tmp_path / 'libraries' / f'{c.name}.kicad_sym'
    env = dict(os.environ)
    for key in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
        directory = tmp_path / key.lower()
        directory.mkdir()
        env[key] = str(directory)
    run = subprocess.run(
        [executable, 'sym', 'upgrade', '--force', str(symbol)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    parsed = one(sexpr(symbol.read_text(encoding='utf-8')), 'symbol')
    pins = [p for unit in children(parsed, 'symbol') for p in children(unit, 'pin')]
    assert len(pins) == 16
    for p in pins:
        x, y, _ = map(float, one(p, 'at')[1:])
        assert max(abs(x), abs(y)) < 20
        source = next(pin for pin in c.pins if pin.number == one(p, 'number')[1])
        assert (x, y) == pytest.approx((source.x, source.y), abs=1e-4)
        assert float(one(p, 'length')[1]) == pytest.approx(source.length, abs=1e-4)
    for prop in children(parsed, 'property'):
        assert all(abs(float(v)) < 50 for v in one(prop, 'at')[1:3])
    # The footprint's physical dimensions are independent of the missing symbol origin.
    pretty = tmp_path / 'libraries' / f'{c.name}.pretty'
    run = subprocess.run(
        [executable, 'fp', 'upgrade', '--force', str(pretty)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    footprint = sexpr((pretty / f'{c.name}.kicad_mod').read_text(encoding='utf-8'))
    pads = children(footprint, 'pad')
    assert len(pads) == 16
    for p in pads:
        source = next(pad for pad in c.pads if pad.number == p[1])
        assert list(map(float, one(p, 'size')[1:])) == pytest.approx(
            [source.width, source.height], abs=1e-4
        )
        assert list(map(float, one(p, 'at')[1:3])) == pytest.approx([source.x, source.y], abs=1e-4)

    # KiCad's ordinary SVG export auto-crops to the drawing and can hide this bug.
    # Include an origin marker to reproduce the editor's origin-to-drawing view.
    opener = f'(symbol "{c.name}_0_1"\n'
    marker = '(circle (center 0 0) (radius 0.5) (stroke (width 0.1) (type default)) (fill (type none)))\n'
    assert opener in c.symbol
    with_origin = tmp_path / 'origin-check.kicad_sym'
    with_origin.write_text(c.symbol.replace(opener, opener + marker), encoding='utf-8')
    svg_dir = tmp_path / 'svg'
    run = subprocess.run(
        [executable, 'sym', 'export', 'svg', '--output', str(svg_dir), str(with_origin)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    svg = ET.parse(next(svg_dir.glob('*.svg'))).getroot()
    width = float(svg.attrib['width'].removesuffix('mm'))
    height = float(svg.attrib['height'].removesuffix('mm'))
    assert 10 < width < 100 and 10 < height < 100, (width, height)
