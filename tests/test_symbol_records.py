"""Guard the distinct field layouts of EasyEDA symbol drawing records."""

import json

import pytest
from conftest import FIXTURES

from easyeda2kicad_local.converter import convert_response
from easyeda2kicad_local.sexpr import children, descendants, loads
from easyeda2kicad_local.shared import UNIT, Coordinates
from easyeda2kicad_local.symbol import symbol_graphic, symbol_units

BUZZER = '82015f7d9a6543b7b998917289a50b78'


def fixture_graphics():
    for path in sorted(FIXTURES.glob('*.json')):
        result = json.loads(path.read_bytes())['result']
        for index, data in enumerate(symbol_units(result), 1):
            for number, raw in enumerate(data['shape']):
                if not raw.startswith('P~'):
                    yield pytest.param(
                        data, raw, id=f'{path.stem}-unit{index}-{number}-{raw.split("~")[0]}'
                    )


@pytest.mark.parametrize('data,raw', list(fixture_graphics()))
def test_fixture_symbol_graphics_parse_with_their_own_field_layout(data, raw):
    fields = raw.split('~')
    graphics = symbol_graphic(raw, Coordinates(data, symbol=True))
    assert graphics
    width_index = {'R': 8, 'E': 6, 'PL': 3, 'PG': 3, 'A': 4}.get(fields[0])
    if width_index is not None:
        expected = max(0.01, float(fields[width_index]) * UNIT)
        for graphic in graphics:
            stroke = children(loads(graphic), 'stroke')[0]
            assert float(children(stroke, 'width')[0][1]) == pytest.approx(expected)


def test_buzzer_symbol_contains_source_arc_without_skip_warning(caplog):
    response = json.loads((FIXTURES / f'{BUZZER}.json').read_bytes())
    converted = convert_response(response)
    arcs = list(descendants(loads(converted.symbol), 'arc'))
    assert len(arcs) == 1
    arc = arcs[0]
    assert list(map(float, children(arc, 'start')[0][1:])) == pytest.approx(
        [3.175, -0.2539746], abs=1e-6
    )
    assert list(map(float, children(arc, 'end')[0][1:])) == pytest.approx(
        [-3.175, -0.2539746], abs=1e-6
    )
    assert children(children(arc, 'stroke')[0], 'width') == [['width', '0.254']]
    assert 'skipping optional symbol' not in caplog.text
    assert len(converted.pins) == 2 and not converted.footprint


@pytest.mark.parametrize('kind,width_index', [('A', 4), ('PT', 3)])
def test_arc_and_path_stroke_fields_remain_distinct(kind, width_index):
    # PT has no helperDots field; derive this calibration from the real A path.
    data = json.loads((FIXTURES / f'{BUZZER}.json').read_bytes())['result']['dataStr']
    source = next(raw for raw in data['shape'] if raw.startswith('A~')).split('~')
    fields = [kind, source[1], '#A00000', '2.5', '0', '']
    if kind == 'A':
        fields.insert(2, 'helper dots are not the width')
    assert fields[width_index] == '2.5'
    arc = loads(symbol_graphic('~'.join(fields), Coordinates(data, symbol=True))[0])
    assert arc[0] == 'arc'
    assert children(children(arc, 'stroke')[0], 'width') == [['width', '0.635']]
