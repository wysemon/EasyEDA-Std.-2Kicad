"""Angle units, property visibility and layout regressions for both fixtures."""
import copy
import json
import os
import re
import shutil
import subprocess

import pytest
from conftest import OLD

from easyeda2kicad_local.converter import convert_response, write_conversion


def sexpr(text):
    """Read generated/round-tripped KiCad expressions independently of the writer."""
    tokens = iter(re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text))

    def read(token):
        if token != '(':
            return json.loads(token) if token.startswith('"') else token
        result = []
        for token in tokens:
            if token == ')':
                return result
            result.append(read(token))
        raise AssertionError('unclosed S-expression')

    return read(next(tokens))


def children(node, kind):
    return [part for part in node if isinstance(part, list) and part and part[0] == kind]


def one(node, kind):
    return children(node, kind)[0]


def texts(symbol):
    return [text for unit in children(one(sexpr(symbol), 'symbol'), 'symbol')
            for text in children(unit, 'text')]


@pytest.mark.parametrize('source,expected', [(0, '0'), (90, '2700'), (180, '1800'), (270, '900')])
def test_exact_symbol_text_angle_on_both_fixtures(response, source, expected):
    data = response['result']['dataStr']
    count = 0
    for i, raw in enumerate(data['shape']):
        if raw.startswith('T~'):
            fields = raw.split('~')
            fields[4] = str(source)
            data['shape'][i] = '~'.join(fields)
            count += 1
    converted = convert_response(response)
    nodes = texts(converted.symbol)
    assert len(nodes) == count > 0
    assert all(one(node, 'at')[3] == expected for node in nodes)
    # Property fields have a separate degree convention and remain horizontal.
    properties = children(one(sexpr(converted.symbol), 'symbol'), 'property')
    assert all(one(prop, 'at')[3] == '0' for prop in properties)


def test_real_fixture_labels_are_vertical(response):
    converted = convert_response(response)
    actual = {node[1]: one(node, 'at')[3] for node in texts(converted.symbol)}
    if response['result']['uuid'] == OLD:
        assert actual['MAX98357A'] == actual['I2S MONO AMP'] == '900'
        assert actual['SPKR'] == '0'
    else:
        assert actual['USB'] == '2700'


@pytest.mark.parametrize('source', [0, 90, 180, 270])
def test_footprint_text_angles_stay_in_degrees(response, source):
    data = response['result']['packageDetail']['dataStr']
    count = 0
    for i, raw in enumerate(data['shape']):
        if raw.startswith('TEXT~'):
            fields = raw.split('~')
            fields[5] = str(source)
            data['shape'][i] = '~'.join(fields)
            count += 1
    converted = convert_response(response)
    nodes = [n for n in children(sexpr(converted.footprint), 'fp_text') if n[1] == 'user']
    assert len(nodes) == count > 0
    assert all(float(one(node, 'at')[3]) == source for node in nodes)


def test_reference_value_position_and_hidden_metadata(response):
    c = convert_response(response)
    props = {node[1]: node for node in children(one(sexpr(c.symbol), 'symbol'), 'property')}
    assert {'Footprint', 'Datasheet', 'Description', 'Author', 'Source', 'EasyEDA UUID'} <= props.keys()
    for name, prop in props.items():
        effects = one(prop, 'effects')
        assert ('hide' not in effects) is (name in ('Reference', 'Value'))
        assert list(map(float, one(one(effects, 'font'), 'size')[1:])) == [1.27, 1.27]
        assert children(effects, 'justify') == ([] if name in ('Reference', 'Value') else [['justify', 'left']])
    assert props['EasyEDA UUID'][2] == response['result']['uuid']
    ref = list(map(float, one(props['Reference'], 'at')[1:]))
    value = list(map(float, one(props['Value'], 'at')[1:]))
    data = response['result']['dataStr']
    # Fixtures' non-text body extents: x=395.27..495.27 and x=2945..3055.
    left, right = (395.27, 495.27) if response['result']['uuid'] == OLD else (2945, 3055)
    center = ((left + right) / 2 - data['head']['x']) * .254
    assert ref[0] == value[0] == pytest.approx(center, abs=1e-6)
    assert ref[1] - value[1] == pytest.approx(2.54)
    box = data['BBox']
    top = (data['head']['y'] - box['y']) * .254
    assert value[1] - .635 > top
    assert value[1] - .635 > max(pin.y for pin in c.pins)
    assert ref[2] == value[2] == 0


def test_layout_tracks_shifted_origin_without_bbox(response):
    response['result']['dataStr'].pop('BBox')
    original = convert_response(response)
    moved = copy.deepcopy(response)
    moved['result']['dataStr']['head']['x'] += 37
    moved['result']['dataStr']['head']['y'] += 53
    converted = convert_response(moved)
    for before, after in zip(children(one(sexpr(original.symbol), 'symbol'), 'property'),
                             children(one(sexpr(converted.symbol), 'symbol'), 'property')):
        if before[1] not in ('Reference', 'Value'):
            continue
        ax, ay, _ = map(float, one(before, 'at')[1:])
        bx, by, _ = map(float, one(after, 'at')[1:])
        assert bx - ax == pytest.approx(-37 * .254, abs=1e-6)
        assert by - ay == pytest.approx(53 * .254, abs=1e-6)


def test_text_envelope_clears_labels_above_body(response):
    original = convert_response(response)
    original_value = next(prop for prop in children(one(sexpr(original.symbol), 'symbol'), 'property')
                          if prop[1] == 'Value')
    data = response['result']['dataStr']
    raw = next(s for s in data['shape'] if s.startswith('T~'))
    fields = raw.split('~')
    fields[2], fields[3], fields[4] = str(data['head']['x']), str(data['head']['y'] - 200), '270'
    fields[7], fields[12] = '9pt', 'LONG LABEL ABOVE BODY (xy 500 500)'
    data['shape'].append('~'.join(fields))
    c = convert_response(response)
    value = next(prop for prop in children(one(sexpr(c.symbol), 'symbol'), 'property') if prop[1] == 'Value')
    # Half the conservative length plus anchor, with room for the property glyphs.
    text_top = 200 * .254 + len(fields[12]) * 1.905 / 2
    assert float(one(value, 'at')[2]) - .635 > text_top
    assert one(value, 'at')[1] == one(original_value, 'at')[1]


@pytest.mark.kicad
def test_cardinal_angles_survive_kicad_roundtrip(response, tmp_path):
    executable = shutil.which('kicad-cli')
    if not executable:
        pytest.skip('Optional KiCad CLI round-trip test')
    data = response['result']['dataStr']
    template = next(s for s in data['shape'] if s.startswith('T~'))
    data['shape'] = [s for s in data['shape'] if not s.startswith('T~')]
    for angle in (0, 90, 180, 270):
        fields = template.split('~')
        fields[4], fields[12] = str(angle), f'Rotation_{angle}'
        data['shape'].append('~'.join(fields))
    c = write_conversion(response, tmp_path / 'original')
    copy = tmp_path / 'check.kicad_sym'
    shutil.copy2(tmp_path / 'original' / f'{c.name}.kicad_sym', copy)
    env = dict(os.environ)
    for name in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
        directory = tmp_path / name.lower()
        directory.mkdir()
        env[name] = str(directory)
    run = subprocess.run([executable, 'sym', 'upgrade', '--force', str(copy)],
                         env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert {t[1]: one(t, 'at')[3] for t in texts(copy.read_text())} == {
        'Rotation_0': '0', 'Rotation_90': '2700', 'Rotation_180': '1800', 'Rotation_270': '900'}
    # Hidden fields must stay hidden when KiCad reads and saves the library.
    for prop in children(one(sexpr(copy.read_text()), 'symbol'), 'property'):
        if prop[1] in ('Reference', 'Value'):
            assert 'hide' not in one(prop, 'effects') and not children(one(prop, 'effects'), 'hide')
        else:
            hidden = one(prop, 'effects')
            assert 'hide' in hidden or ['hide', 'yes'] in hidden
