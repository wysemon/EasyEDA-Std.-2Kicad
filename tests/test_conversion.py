import copy
import json
import math
import os
import shutil
import subprocess

import pytest
from conftest import OLD

from easyeda2kicad_local.converter import (
    Coordinates,
    convert_response,
    document,
    parse_pad,
    prefix,
    safe_name,
    write_conversion,
)
from easyeda2kicad_local.geometry import path_segments


def test_golden_geometry(response, caplog):
    c = convert_response(response)
    is_old = response['result']['uuid'] == OLD
    assert len(c.pins) == (9 if is_old else 4)
    assert len(c.pads) == (7 if is_old else 4)
    assert {p.number for p in c.pins} <= {p.number for p in c.pads}
    assert all(p.kind == 'thru_hole' and p.drill == pytest.approx(1, abs=.001) for p in c.pads)
    assert all(p.width == pytest.approx(1.9304 if is_old else 1.507998) for p in c.pads)
    assert all(p.shape == ('circle' if is_old else 'rect') for p in c.pads)
    assert all('(drill oval' not in p.render() for p in c.pads)
    if is_old:
        ys = sorted(p.y for p in c.pads)
        assert all(b - a == pytest.approx(2.54) for a, b in zip(ys, ys[1:]))
        assert 'Duplicate symbol pin number 1' in caplog.text
        header = next(p for p in c.pins if p.name == 'VIN')
        assert (header.x, header.y) == pytest.approx((-16.51, -9.652))
        assert header.angle == 0 and header.length == pytest.approx(5.08)
        assert next(p for p in c.pins if p.name == '+').angle == 180
        assert c.footprint.count('(fp_arc ') == 6
    else:
        assert max(p.x for p in c.pads) - min(p.x for p in c.pads) == pytest.approx(15.24, abs=.001)
        assert max(p.y for p in c.pads) - min(p.y for p in c.pads) == pytest.approx(17.78, abs=.001)
        pin = next(p for p in c.pins if p.number == '3')
        assert (pin.x, pin.y) == pytest.approx((8.89, 14.224))
        assert pin.angle == 270 and pin.length == pytest.approx(5.08)
        assert pin.electrical == 'unspecified'
        assert 'doduchieu255' in c.credits and 'sharan.b' in c.credits
        assert '(property "Reference" "AP"' in c.symbol
    assert 'F.CrtYd' in c.footprint
    assert f'"{c.name}:{c.name}"' in c.symbol


def test_tolerant_unknown_and_missing_pad_warning(response, caplog):
    changed = copy.deepcopy(response)
    changed['result']['dataStr']['shape'].append('FUTURE~whatever')
    changed['result']['packageDetail']['dataStr']['shape'] = [
        s for s in changed['result']['packageDetail']['dataStr']['shape']
        if not (s.startswith('PAD~') and len(s.split('~')) > 8 and s.split('~')[8] == '1')]
    c = convert_response(changed)
    assert len(c.pads) >= 3
    assert 'FUTURE~whatever' in caplog.text
    assert 'Symbol pin numbers missing from footprint: 1' in caplog.text


def test_string_documents_and_multiunit(response, caplog):
    changed = copy.deepcopy(response)
    changed['result']['dataStr'] = json.dumps(changed['result']['dataStr'])
    changed['result']['packageDetail']['dataStr'] = json.dumps(changed['result']['packageDetail']['dataStr'])
    assert convert_response(changed).pads


def test_slot_rotation_polygon_and_smd(response):
    data = document(response['result']['packageDetail']['dataStr'])
    raw = next(s for s in data['shape'] if s.startswith('PAD~'))
    fields = raw.split('~')
    fields[13] = '8'
    c = Coordinates(data)
    assert '(drill oval 2.032 0.999744)' in parse_pad('~'.join(fields), c).render()
    fields[6], fields[1] = '2', 'OVAL'
    pad = parse_pad('~'.join(fields), c)
    assert pad.kind == 'smd' and not pad.drill and 'B.Paste' in pad.layers
    fields[1], fields[10] = 'POLYGON', '0 0 10 0 5 10'
    assert '(primitives (gr_poly' in parse_pad('~'.join(fields), c).render()


@pytest.mark.parametrize('value,expected', [('U?', 'U'), ('AP1', 'AP'), ('', 'U')])
def test_reference(value, expected):
    assert prefix(value) == expected


def test_safe_filename():
    assert '/' not in safe_name('你好 a/b \\ c')
    assert safe_name('..') == 'component'


def test_svg_arc_geometry():
    kind, pts = list(path_segments('M 10 0 A 10 10 0 0 1 0 10'))[0]
    assert kind == 'arc'
    assert pts[1] == pytest.approx((math.sqrt(50), math.sqrt(50)))
    large = list(path_segments('M 10 0 A 10 10 0 1 0 0 10'))[0][1]
    assert large[1][0] < 0 and large[1][1] < 0
    assert list(path_segments('M1 2h 3v -4z'))[-1][1][-1] == (1, 2)
    with pytest.raises(ValueError):
        list(path_segments('M 0 0 Q 1 1 2 2'))


def test_credits_official(response):
    response['result']['dataStr']['head']['c_para']['Contributor'] = 'LCSC'
    assert 'JLCEDA/EasyEDA Official Library' in convert_response(response).credits


@pytest.mark.kicad
def test_kicad_imports(response, tmp_path):
    executable = shutil.which('kicad-cli')
    if not executable:
        pytest.skip('Optional KiCad CLI integration: kicad-cli is not installed')
    c = write_conversion(response, tmp_path / 'libraries')
    env = dict(os.environ)
    for name in ('XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
        directory = tmp_path / name.lower()
        directory.mkdir()
        env[name] = str(directory)
    for kind, source in [('sym', tmp_path / 'libraries' / f'{c.name}.kicad_sym'),
                         ('fp', tmp_path / 'libraries' / f'{c.name}.pretty')]:
        out = tmp_path / kind
        run = subprocess.run([executable, kind, 'export', 'svg', '--output', str(out), str(source)],
                             env=env, capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
        svgs = list(out.glob('*.svg'))
        assert svgs and all(s.stat().st_size > 100 for s in svgs), run.stdout + run.stderr


def test_fixture_pin_path_tokenization(response):
    """Compare compact and spaced forms of every real pin, in both fixtures."""
    import re

    from easyeda2kicad_local.converter import parse_pin

    data = response['result']['dataStr']
    coords = Coordinates(data, True)
    paths = []
    for raw in data['shape']:
        if not raw.startswith('P~'):
            continue
        path = raw.split('^^')[2].split('~')[0]
        paths.append(path)
        expected = list(path_segments(path))
        compact = re.sub(r'\s*([MmLlHhVv])\s*', r'\1', path)
        compact = re.sub(r'\s+(?=[+-])', '', compact)
        spaced = re.sub(r'([MmLlHhVv])', r' \1 ', path)
        assert list(path_segments(compact)) == expected
        assert list(path_segments(spaced)) == expected
        # Pin direction, start and length must also survive normalization.
        assert parse_pin(raw.replace(path, compact), coords) == parse_pin(raw, coords)
    assert len(paths) == (9 if response['result']['uuid'] == OLD else 4)
    if response['result']['uuid'] == OLD:
        assert 'M500 233h -10' in paths
    else:
        assert 'M 3035 3944 v 20' in paths


@pytest.mark.parametrize('path,points', [
    ('M10-5h-2v+3', [[(10., -5.), (8., -5.)], [(8., -5.), (8., -2.)]]),
    ('M1e1-5L.5-.25', [[(10., -5.), (.5, -.25)]]),
    ('M500 233h -10', [[(500., 233.), (490., 233.)]]),
    ('M 3035 3944 v 20', [[(3035., 3944.), (3035., 3964.)]]),
])
def test_compact_numbers_and_commands(path, points):
    assert [pts for kind, pts in path_segments(path)] == points


@pytest.mark.parametrize('title', ['CON', 'con.txt', 'NUL', 'COM1', 'LPT9.kicad_sym', 'AUX', 'PRN'])
def test_windows_reserved_names(title):
    assert safe_name(title).startswith('_')


def test_filename_length_and_unicode():
    assert len(safe_name('a' * 100)) == 60
    assert len(safe_name('CON.' + 'a' * 100)) <= 60
    assert safe_name('你好 🎸') == 'component'
    assert safe_name('électronique/module') == 'electronique_module'
