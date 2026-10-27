"""Regression cases supplied after testing real components in KiCad."""

import copy
import json
import math
from pathlib import Path

import pytest

from easyeda2kicad_local.converter import convert_response
from easyeda2kicad_local.geometry import point_pairs
from easyeda2kicad_local.sexpr import children, loads
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
