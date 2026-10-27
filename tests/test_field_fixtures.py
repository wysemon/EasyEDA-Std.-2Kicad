"""Regression cases supplied after testing real components in KiCad."""

import copy
import json
import logging
import math
from collections import Counter
from pathlib import Path

import pytest

from easyeda2kicad_local.converter import convert_response
from easyeda2kicad_local.geometry import point_pairs
from easyeda2kicad_local.sexpr import children, descendants, loads
from easyeda2kicad_local.shared import UNIT

FIXTURES = Path(__file__).parent / 'fixtures'
HEADER = 'b156dd172f7646a6a0d70c948b98a414'


def load(uuid):
    return json.loads((FIXTURES / f'{uuid}.json').read_bytes())


def test_legacy_header_yes_plating():
    converted = convert_response(load(HEADER))
    assert len(converted.pads) == len(converted.pins) == 16
    assert all(p.kind == 'thru_hole' and p.drill > 0 for p in converted.pads)


POLYGON_IDS = ['c1e9a7b5304f4595a62af862fec3a102', 'c50879e99f214b40a692b31827f5fe31']


@pytest.mark.parametrize('uuid,count', list(zip(POLYGON_IDS, [3, 9])))
def test_polygon_pads_with_omitted_dimensions(uuid, count):
    response = load(uuid)
    before = copy.deepcopy(response)
    converted = convert_response(response)
    assert response == before
    assert len(converted.pads) == count
    assert all(p.polygon and p.width > 0 and p.height > 0 for p in converted.pads)
    for raw, pad in zip(
        (
            s
            for s in response['result']['packageDetail']['dataStr']['shape']
            if s.startswith('PAD~')
        ),
        converted.pads,
    ):
        source = point_pairs(raw.split('~')[10], minimum=3)
        angle = math.radians(-pad.angle)
        for (x, y), (sx, sy) in zip(pad.polygon, source):
            world = (
                pad.x + x * math.cos(angle) - y * math.sin(angle),
                pad.y + x * math.sin(angle) + y * math.cos(angle),
            )
            assert world == pytest.approx(((sx - 400) * UNIT, (sy - 300) * UNIT))


def test_all_bad_pads_are_reported_with_raw_records():
    response = load(POLYGON_IDS[0])
    shapes = response['result']['packageDetail']['dataStr']['shape']
    invalid = [
        'PAD~BAD~400~300~4~4~1~~bad-shape~0~~0~~0~~Y',
        'PAD~RECT~400~300~-1~4~1~~bad-width~0~~0~~0~~Y',
        'PAD~RECT~400~300~4~0~1~~bad-height~0~~0~~0~~Y',
        'PAD~RECT~400~300~4~4~15~~bad-layer~0~~0~~0~~Y',
        'PAD~RECT~400~300~bad~4~1~~nonnumeric-width~0~~0~~0~~Y',
        'PAD~RECT~400~300~4~nan~1~~nonfinite-height~0~~0~~0~~Y',
    ]
    shapes.extend(invalid)
    with pytest.raises(ValueError) as failure:
        convert_response(response)
    assert all(raw in str(failure.value) for raw in invalid)
    assert all(word in str(failure.value) for word in ('shape', 'width', 'height', 'layer'))
    assert "invalid pad width 'bad'" in str(failure.value)
    assert "invalid pad height 'nan'" in str(failure.value)


def test_bare_point_regions_are_closed_and_exported():
    converted = convert_response(load(POLYGON_IDS[0]))
    polygons = children(loads(converted.footprint), 'fp_poly')
    assert len(polygons) == 4
    assert all(children(p, 'layer') == [['layer', 'Dwgs.User']] for p in polygons)
    for p in polygons:
        pts = children(p, 'pts')[0][1:]
        assert pts[0] == pts[-1]


@pytest.mark.parametrize(
    'path', ['0 0 1', '0 0 1 0 garbage', '0 0 1 0 2 0', '0 0 4 4 0 4 4 0 5 -1']
)
def test_invalid_bare_copper_polygon_still_fails(path):
    response = load(POLYGON_IDS[0])
    response['result']['packageDetail']['dataStr']['shape'].append(f'SOLIDREGION~1~~{path}~solid')
    with pytest.raises(ValueError, match='invalid essential footprint SOLIDREGION'):
        convert_response(response)


BUZZER = '82015f7d9a6543b7b998917289a50b78'


def test_symbol_only_exports_no_invented_footprint(caplog):
    converted = convert_response(load(BUZZER))
    assert len(converted.pins) == 2 and not converted.pads and not converted.footprint
    symbol = children(loads(converted.symbol), 'symbol')[0]
    assert [p[2] for p in children(symbol, 'property') if p[1] == 'Footprint'] == ['']
    assert 'symbol only: no footprint in source' in converted.credits
    assert 'symbol only: no footprint in source' in caplog.text


def test_symbol_only_cached_workflow_and_completion(tmp_path, monkeypatch, capsys):
    from easyeda2kicad_local.client import EasyEDAClient
    from easyeda2kicad_local.publication import libraries_complete
    from easyeda2kicad_local.workflow import run_items

    folder = tmp_path / 'buzzer'
    folder.mkdir()
    raw = (FIXTURES / f'{BUZZER}.json').read_bytes()
    (folder / 'raw.json').write_bytes(raw)
    monkeypatch.setattr(EasyEDAClient, 'component', lambda *_: pytest.fail('No network allowed'))
    assert run_items([BUZZER], tmp_path, cached_only=True) == 0
    report = capsys.readouterr().out
    assert '1 succeeded, 0 failed' in report and 'Succeeded with warning: 1' in report
    assert 'Symbol Libraries' in report and 'Footprint Libraries' not in report
    assert libraries_complete(folder, expected_uuid=BUZZER)
    assert not list(folder.glob('*.pretty'))
    assert (folder / 'raw.json').read_bytes() == raw
    assert 'succeeded-with-warning' in (tmp_path / 'fetch_log.tsv').read_text()
    assert run_items([BUZZER], tmp_path) == 0
    assert '1 skipped' in capsys.readouterr().out


def test_known_footprint_not_silently_downgraded_to_symbol_only():
    response = load(HEADER)
    response['result'].pop('packageDetail')
    with pytest.raises(ValueError, match='missing footprint'):
        convert_response(response)


def test_symbol_only_failed_validation_preserves_existing(tmp_path, monkeypatch):
    from test_workflow import snapshot

    from easyeda2kicad_local.converter import write_conversion

    folder = tmp_path / 'buzzer'
    folder.mkdir()
    (folder / 'user.txt').write_bytes(b'keep')
    before = snapshot(folder)
    monkeypatch.setattr('easyeda2kicad_local.converter.validate_libraries', lambda *_: False)
    with pytest.raises(ValueError, match='KiCad validation failed'):
        write_conversion(load(BUZZER), folder, validate=True)
    assert snapshot(folder) == before


STM32 = '0010e6e3c07c4ca9b85cbb34a79052f3'


def symbol_unit_nodes(converted):
    return children(children(loads(converted.symbol), 'symbol')[0], 'symbol')


def test_stm32_all_48_pins_exported_once_in_two_units():
    response = load(STM32)
    before = copy.deepcopy(response)
    converted = convert_response(response)
    units = symbol_unit_nodes(converted)
    assert [u[1] for u in units] == [f'{converted.name}_1_1', f'{converted.name}_2_1']
    assert [len(children(u, 'pin')) for u in units] == [9, 39]
    numbers = [children(p, 'number')[0][1] for u in units for p in children(u, 'pin')]
    assert Counter(numbers) == Counter(map(str, range(1, 49)))
    assert Counter(p.number for p in converted.pads) == Counter(numbers)
    assert len(converted.pins) == len(converted.pads) == 48
    assert all(len(children(u, 'rectangle')) == 1 for u in units)
    assert response == before
    # Reference/Value are above unit 1, not the taller unit 2.
    props = children(children(loads(converted.symbol), 'symbol')[0], 'property')
    visible = [p for p in props if p[1] in ('Reference', 'Value')]
    assert [float(children(p, 'at')[0][2]) for p in visible] == pytest.approx([14.732, 12.192])


def test_each_unit_uses_its_own_origin():
    response = load(STM32)
    expected = convert_response(response)
    response['result']['subparts'][1]['dataStr']['head'].update(x=2990, y=4010)
    converted = convert_response(response)
    assert converted.pins[:9] == expected.pins[:9]
    for pin, before in zip(converted.pins[9:], expected.pins[9:]):
        assert (pin.x, pin.y) == pytest.approx((before.x + 2.54, before.y + 2.54))


@pytest.mark.parametrize(
    'failure',
    ['missing-data', 'empty', 'bad-pin', 'bad-graphic', 'parent-mismatch', 'nested', 'bad-list'],
)
def test_unparseable_unit_fails_instead_of_exporting_partial_symbol(failure):
    response = load(STM32)
    parts = response['result']['subparts']
    if failure == 'missing-data':
        parts[1].pop('dataStr')
    elif failure == 'empty':
        parts[1]['dataStr']['shape'] = []
    elif failure == 'bad-pin':
        parts[1]['dataStr']['shape'].append('P~invalid')
    elif failure == 'bad-graphic':
        parts[1]['dataStr']['shape'].append('UNSUPPORTED~drawing')
    elif failure == 'parent-mismatch':
        response['result']['dataStr']['shape'].append('T~extra')
    elif failure == 'nested':
        parts[1]['subparts'] = [{}]
    else:
        response['result']['subparts'] = {'unknown': {}}
    with pytest.raises(ValueError, match='unit|Multi-unit'):
        convert_response(response)


def test_multiunit_count_is_bounded():
    response = load(STM32)
    response['result']['subparts'] *= 51
    with pytest.raises(ValueError, match='at most 100'):
        convert_response(response)


def test_stm32_partial_legacy_cache_is_reconverted_offline(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    from easyeda2kicad_local.client import EasyEDAClient
    from easyeda2kicad_local.converter import write_conversion
    from easyeda2kicad_local.publication import COMPLETE, libraries_complete
    from easyeda2kicad_local.workflow import run_items

    response = load(STM32)
    incomplete = copy.deepcopy(response)
    incomplete['result'].pop('subparts')
    folder = tmp_path / 'stm32'
    partial = write_conversion(incomplete, folder)
    assert len(partial.pins) == 9
    (folder / COMPLETE).unlink()
    raw = (FIXTURES / f'{STM32}.json').read_bytes()
    (folder / 'raw.json').write_bytes(raw)
    assert not libraries_complete(folder)
    monkeypatch.setattr(EasyEDAClient, 'component', lambda *_: pytest.fail('No network allowed'))
    assert run_items([STM32], tmp_path) == 0
    assert libraries_complete(folder, expected_uuid=STM32)
    assert 're-converting from cache' in caplog.text
    assert (folder / 'raw.json').read_bytes() == raw
    assert (
        len(list(descendants(loads((folder / f'{partial.name}.kicad_sym').read_text()), 'pin')))
        == 48
    )


@pytest.mark.kicad
def test_stm32_native_upgrade_and_export_preserve_both_units(tmp_path):
    import subprocess

    from easyeda2kicad_local.converter import write_conversion

    converted = write_conversion(load(STM32), tmp_path, validate=True)
    path = tmp_path / f'{converted.name}.kicad_sym'
    upgraded = tmp_path / 'roundtrip.kicad_sym'
    upgraded.write_bytes(path.read_bytes())
    run = subprocess.run(
        ['kicad-cli', 'sym', 'upgrade', '--force', str(upgraded)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    units = children(children(loads(upgraded.read_text()), 'symbol')[0], 'symbol')
    assert [len(children(u, 'pin')) for u in units if children(u, 'pin')] == [9, 39]
    assert Counter(
        children(p, 'number')[0][1] for u in units for p in children(u, 'pin')
    ) == Counter(map(str, range(1, 49)))
    svg = tmp_path / 'svg'
    svg.mkdir()
    run = subprocess.run(
        ['kicad-cli', 'sym', 'export', 'svg', '--output', str(svg), str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert len(list(svg.glob('*.svg'))) == 2
