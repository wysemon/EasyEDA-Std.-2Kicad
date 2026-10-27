import json
from pathlib import Path

import pytest

from easyeda2kicad_local.converter import convert_response, write_conversion
from easyeda2kicad_local.models import parse_svgnode
from easyeda2kicad_local.workflow import experimental_model
from test_symbol_layout import children, one, sexpr, texts
from test_validation import validate_libraries

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
    c = convert_response(load(SX))
    pins = [p for unit in children(one(sexpr(c.symbol), 'symbol'), 'symbol') for p in children(unit, 'pin')]
    assert len(pins) == 4
    for pin in pins:
        number = one(pin, 'number')
        assert 'hide' not in one(number, 'effects')
        assert ('hide' in one(one(pin, 'name'), 'effects')) is (number[1] == '2')
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


def test_sx_model_attrs_and_experimental_download(tmp_path):
    package = load(SX)['result']['packageDetail']
    raw = next(s for s in package['dataStr']['shape'] if s.startswith('SVGNODE~'))
    model = parse_svgnode(raw)
    assert model.uuid == '2838c4425c9145bcaa4116a1d762772f'
    assert model.origin == (4048.5394, 3035.8268)
    assert model.rotation == (0., 270., 270.)
    assert (model.z, model.width, model.height) == (21.6535, 87.4014, 67.3227)
    class FakeClient:
        def request(self, url):
            assert url.endswith('/' + model.uuid)
            return b'ISO-10303-21;\nEND-ISO-10303-21;'
    experimental_model(package, tmp_path, 'sample', FakeClient())
    assert (tmp_path / 'sample.step').read_bytes().startswith(b'ISO-10303-21;')
    # No guessed placement is attached; that needs a real 3D viewer comparison.
    assert '(model ' not in convert_response(load(SX)).footprint


@pytest.mark.parametrize('uuid', [OLED, SX])
def test_new_fixture_kicad_validation(uuid, tmp_path):
    c = write_conversion(load(uuid), tmp_path)
    assert validate_libraries(tmp_path, c.name)
