"""Essential record failures are fatal; optional drawings and duplicates are not."""

import copy
import json

import pytest
from conftest import FIXTURES
from test_symbol_layout import children, one, sexpr
from test_workflow import install_cache, snapshot

from euc2k.converter import convert_response
from euc2k.footprint import layer
from euc2k.workflow import libraries_complete, run_items


@pytest.mark.parametrize(
    'side,raw',
    [
        ('symbol', 'P~invalid'),
        ('symbol', 'P'),
        ('footprint', 'PAD~invalid'),
        ('footprint', 'PAD'),
        ('footprint', 'HOLE~0~0~0'),
        ('footprint', 'VIA~0~0~0~~0'),
        ('footprint', 'TRACK~1~1~~invalid'),
        ('footprint', 'TRACK~1~21~~0 0 10 10'),
        ('footprint', 'SOLIDREGION~1~~M0 0 Q 2 2 5 5~solid'),
    ],
)
def test_one_bad_essential_record_fails_whole_component(response, side, raw):
    doc = (
        response['result']['dataStr']
        if side == 'symbol'
        else response['result']['packageDetail']['dataStr']
    )
    doc['shape'].append(raw)
    with pytest.raises(ValueError, match='invalid essential'):
        convert_response(response)


def test_essential_failure_does_not_publish_and_batch_continues(response, tmp_path, capsys):
    folder, _ = install_cache(tmp_path, response)
    other = copy.deepcopy(response)
    other['result']['uuid'] = 'a' * 32
    second = tmp_path / 'another'
    second.mkdir()
    (second / 'raw.json').write_text(json.dumps(other))
    response['result']['packageDetail']['dataStr']['shape'].append('PAD~invalid')
    (folder / 'raw.json').write_text(json.dumps(response))
    before = snapshot(folder)
    assert run_items([response['result']['uuid'], 'a' * 32], tmp_path) == 1
    assert snapshot(folder) == before and not libraries_complete(folder)
    assert libraries_complete(second)
    assert '1 succeeded, 1 failed' in capsys.readouterr().out


def test_optional_graphic_warns_but_all_electrical_records_survive(response, caplog):
    original = convert_response(response)
    response['result']['dataStr']['shape'].append('DECORATION~not implemented')
    response['result']['packageDetail']['dataStr']['shape'].append('DECORATION~not implemented')
    converted = convert_response(response)
    assert converted == original
    assert (
        'skipping optional symbol' in caplog.text and 'skipping optional footprint' in caplog.text
    )
    assert response['result']['uuid'] in caplog.text


@pytest.mark.parametrize('side', ['symbol', 'footprint'])
def test_empty_electrical_collection_is_rejected(response, side):
    doc = (
        response['result']['dataStr']
        if side == 'symbol'
        else response['result']['packageDetail']['dataStr']
    )
    prefix = 'P~' if side == 'symbol' else 'PAD~'
    doc['shape'] = [r for r in doc['shape'] if not r.startswith(prefix)]
    with pytest.raises(ValueError, match='no usable pins or pads'):
        convert_response(response)


def test_duplicates_and_unmatched_physical_pads_are_retained(response, caplog):
    symbol = response['result']['dataStr']
    pin = next(r for r in symbol['shape'] if r.startswith('P~'))
    symbol['shape'].append(pin)
    package = response['result']['packageDetail']['dataStr']
    fields = next(r for r in package['shape'] if r.startswith('PAD~')).split('~')
    fields[8] = 'UNPOPULATED'
    package['shape'].append('~'.join(fields))
    c = convert_response(response)
    assert sum(p.number == fields[8] for p in c.pads) == 1
    assert c.pins.count(c.pins[0]) >= 2
    assert 'Duplicate symbol pin number' in caplog.text


@pytest.mark.parametrize(
    'source,expected',
    [
        ('0', 'unspecified'),
        ('1', 'input'),
        ('2', 'output'),
        ('3', 'bidirectional'),
        ('4', 'passive'),
        ('', 'unspecified'),
        ('undefined', 'unspecified'),
        ('999', 'unspecified'),
    ],
)
def test_verified_electrical_types(response, source, expected, caplog):
    shape = response['result']['dataStr']['shape']
    for index, raw in enumerate(shape):
        if raw.startswith('P~'):
            fields = raw.split('~')
            fields[2] = source
            shape[index] = '~'.join(fields)
    c = convert_response(response)
    assert all(pin.electrical == expected for pin in c.pins)
    if source == '999':
        assert 'Unknown electrical type' in caplog.text and 'using unspecified' in caplog.text
    else:
        assert 'Unknown electrical type' not in caplog.text


@pytest.mark.parametrize(
    'parts',
    [[{'shape': ['P~...']}, {'shape': ['P~...']}], {'A': {}, 'B': {}}, ['unknown'], 'unknown'],
)
@pytest.mark.parametrize('top_level', [True, False])
def test_nonempty_subparts_are_rejected_even_with_top_level_shapes(response, parts, top_level):
    data = response['result']['dataStr']
    data['subparts'] = parts
    if not top_level:
        data.pop('shape')
    with pytest.raises(ValueError, match='Multi-unit.*refusing a partial'):
        convert_response(response)


@pytest.mark.parametrize('empty', [None, [], {}])
def test_empty_subparts_preserve_single_unit_behavior(response, empty):
    expected = convert_response(response)
    response['result']['dataStr']['subparts'] = empty
    assert convert_response(response) == expected


@pytest.mark.parametrize(
    'source,expected',
    [
        ('1', 'F.Cu'),
        ('2', 'B.Cu'),
        ('3', 'F.SilkS'),
        ('4', 'B.SilkS'),
        ('5', 'F.Paste'),
        ('6', 'B.Paste'),
        ('7', 'F.Mask'),
        ('8', 'B.Mask'),
        ('10', 'Edge.Cuts'),
        ('12', 'Dwgs.User'),
        ('13', 'F.Fab'),
        ('14', 'B.Fab'),
        ('99', 'User.3'),
        ('100', 'User.4'),
        ('101', 'User.5'),
    ],
)
def test_layer_mappings_match_native_importer(response, source, expected):
    data = response['result']['packageDetail']['dataStr']
    data['shape'].append(f'RECT~0~0~10~20~{source}~mapping-test')
    fp = sexpr(convert_response(response).footprint)
    rect = next(r for r in children(fp, 'fp_rect') if one(r, 'layer')[1] != 'F.CrtYd')
    assert one(rect, 'layer')[1] == expected


def test_unknown_layer_is_not_arbitrarily_mapped(response, caplog):
    with pytest.raises(ValueError, match='unsupported layer 777'):
        layer('777')
    response['result']['packageDetail']['dataStr']['shape'].append('RECT~0~0~10~20~777~unsupported')
    convert_response(response)
    assert 'unsupported layer 777' in caplog.text


@pytest.mark.parametrize(
    'field,value', [(1, 'FUTURE_SHAPE'), (4, '0'), (6, '777'), (9, '-1'), (13, '-5')]
)
def test_invalid_or_unsupported_pad_cannot_disappear(response, field, value):
    data = response['result']['packageDetail']['dataStr']
    raw = next(r for r in data['shape'] if r.startswith('PAD~'))
    fields = raw.split('~')
    fields[field] = value
    data['shape'][data['shape'].index(raw)] = '~'.join(fields)
    with pytest.raises(ValueError, match='invalid essential footprint PAD'):
        convert_response(response)


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('*.json')), ids=lambda p: p.stem)
def test_all_real_fixtures_remain_usable(path):
    c = convert_response(json.loads(path.read_bytes()))
    assert c.pins
    assert bool(c.pads) == bool(c.footprint)
