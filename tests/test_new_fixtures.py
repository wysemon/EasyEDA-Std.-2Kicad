import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_symbol_layout import children, one, sexpr, texts
from test_validation import validate_libraries

from easyeda2kicad_local.converter import convert_response, write_conversion

FIXTURES = Path(__file__).parent / 'fixtures'
OLED = '6c69c66aa27f4c50aceb6e8226ef8d27'
SX = '437e88cd34c64c1697331fe341e4a10f'


def load(uuid):
    return json.loads((FIXTURES / f'{uuid}.json').read_bytes())


def test_oled_rects_and_unknown_layer(caplog):
    data = load(OLED)
    c = convert_response(data)
    rects = children(sexpr(c.footprint), 'fp_rect')
    assert len([r for r in rects if one(r, 'layer')[1] == 'F.SilkS']) == 2
    assert 'unsupported layer' not in caplog.text
    data['result']['packageDetail']['dataStr']['shape'].append('RECT~1~2~3~4~777~unknown')
    convert_response(data)
    assert 'unsupported layer 777' in caplog.text


@pytest.mark.parametrize('uuid', [OLED, SX])
def test_hidden_properties_below_drawing(uuid):
    data = load(uuid)
    c = convert_response(data)
    props = children(one(sexpr(c.symbol), 'symbol'), 'property')
    hidden = [p for p in props if p[1] not in ('Reference', 'Value')]
    positions = [tuple(map(float, one(p, 'at')[1:3])) for p in hidden]
    assert len(set(positions)) == len(hidden)
    bbox = data['result']['dataStr']['BBox']
    head = data['result']['dataStr']['head']
    bottom = (head['y'] - bbox['y'] - bbox['height']) * .254
    assert all(y + .635 < min(bottom, *(p.y for p in c.pins)) for _, y in positions)
    assert len({x for x, y in positions}) == 1
    assert all(a[1] - b[1] == pytest.approx(1.27) for a, b in zip(positions, positions[1:]))
    assert all(one(one(p, 'effects'), 'justify') == ['justify', 'left'] for p in hidden)
    description = next(p[2] for p in props if p[1] == 'Description')
    assert len(description) <= 80 and description == ' '.join(description.split())
    if uuid == SX:
        assert len(description) == 80 and description.endswith('...')
        assert data['result']['description'] in c.credits


def test_sx_pin_name_flag_numbers_and_author_text():
    data = load(SX)
    source_before = json.dumps(data)
    c = convert_response(data)
    assert json.dumps(data) == source_before
    source_pin = next(pin for pin in c.pins if pin.number == '2')
    assert source_pin.name == 'GND' and not source_pin.name_visible
    properties = {p[1]: p[2] for p in children(one(sexpr(c.symbol), 'symbol'), 'property')}
    assert json.loads(properties['EasyEDA Hidden Pin Names']) == [{'number': '2', 'name': 'GND'}]
    pins = [p for unit in children(one(sexpr(c.symbol), 'symbol'), 'symbol') for p in children(unit, 'pin')]
    assert len(pins) == 4
    for pin in pins:
        number = one(pin, 'number')
        assert 'hide' not in one(number, 'effects')
        assert one(pin, 'name')[1] == ('~' if number[1] == '2' else {'1': 'GND', '3': 'OUT', '4': 'Vin'}[number[1]])
        assert 'hide' not in one(one(pin, 'name'), 'effects')
    assert [t[1] for t in texts(c.symbol)].count('GND') == 2
    assert {'Vin', 'OUT'} <= {t[1] for t in texts(c.symbol)}


def test_original_pin_numbers_always_visible(response):
    c = convert_response(response)
    for unit in children(one(sexpr(c.symbol), 'symbol'), 'symbol'):
        for pin in children(unit, 'pin'):
            assert 'hide' not in one(one(pin, 'number'), 'effects')


def test_oled_license_copied_verbatim():
    data = load(OLED)
    license_text = data['result']['packageDetail']['dataStr']['head']['license']
    c = convert_response(data)
    assert f'License (from source) [footprint]:\n{license_text}\n' in c.credits
    assert 'JLCEDA/EasyEDA Official Library - https://lceda.cn/ - https://easyeda.com' in c.credits
    data['result']['dataStr']['head']['license'] = '  A symbol license\n with whitespace.  '
    assert data['result']['dataStr']['head']['license'] in convert_response(data).credits


@pytest.mark.parametrize('uuid', [OLED, SX])
def test_new_fixture_kicad_validation(uuid, tmp_path):
    c = write_conversion(load(uuid), tmp_path)
    assert validate_libraries(tmp_path, c.name)


def test_sx_hidden_name_survives_kicad_save_and_is_not_rendered(tmp_path):
    executable = shutil.which('kicad-cli')
    if not executable:
        pytest.skip('Optional native KiCad round-trip and SVG test')
    c = write_conversion(load(SX), tmp_path / 'libraries')
    source = tmp_path / 'libraries' / f'{c.name}.kicad_sym'
    env = dict(os.environ)
    for key in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
        location = tmp_path / key.lower()
        location.mkdir()
        env[key] = str(location)
    upgrade = subprocess.run([executable, 'sym', 'upgrade', '--force', str(source)],
                             env=env, capture_output=True, text=True, timeout=30)
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    symbol = one(sexpr(source.read_text()), 'symbol')
    pins = [pin for unit in children(symbol, 'symbol') for pin in children(unit, 'pin')]
    hidden = next(pin for pin in pins if one(pin, 'number')[1] == '2')
    assert one(hidden, 'name')[1] == '~'
    assert 'hide' not in one(one(hidden, 'number'), 'effects')
    metadata = next(prop for prop in children(symbol, 'property') if prop[1] == 'EasyEDA Hidden Pin Names')
    assert json.loads(metadata[2]) == [{'number': '2', 'name': 'GND'}]
    effects = one(metadata, 'effects')
    assert 'hide' in effects or ['hide', 'yes'] in effects
    svg_dir = tmp_path / 'svg'
    export = subprocess.run([executable, 'sym', 'export', 'svg', '--output', str(svg_dir), str(source)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert export.returncode == 0, export.stdout + export.stderr
    svg = ET.parse(next(svg_dir.glob('*.svg')))
    labels = [node.text for node in svg.iter() if node.tag.rsplit('}', 1)[-1] == 'text']
    # Two author-drawn GND labels plus the visible pin 1 name; pin 2 adds none.
    assert labels.count('GND') == 3
    assert labels.count('Vin') == 2 and labels.count('OUT') == 2
    assert labels.count('2') == 1  # Its pin number remains visible.
    assert '~' not in labels
