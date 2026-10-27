"""Offline regressions for the cache, pacing, portability and export review."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from easyeda2kicad_local import workflow
from easyeda2kicad_local.cli import app
from easyeda2kicad_local.client import EasyEDAClient
from easyeda2kicad_local.converter import convert_response
from easyeda2kicad_local.geometry import path_segments
from test_client import make_client
from test_entrypoint import invoke_main
from test_symbol_layout import children, one, sexpr, texts
from test_workflow import install_cache
from conftest import NEW, OLD, FIXTURES

BOOTSTRAP = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/bootstrap.py'))
ensure_installed = BOOTSTRAP['ensure_installed']


@pytest.mark.parametrize('partial', ['raw', 'symbol', 'footprint', 'empty-pretty'])
def test_partial_libraries_reconvert_without_network(response, tmp_path, monkeypatch, caplog, partial):
    folder, raw = install_cache(tmp_path, response)
    if partial == 'symbol':
        (folder / 'partial.kicad_sym').write_text('partial')
    elif partial in ('footprint', 'empty-pretty'):
        pretty = folder / 'partial.pretty'
        pretty.mkdir()
        if partial == 'footprint':
            (pretty / 'partial.kicad_mod').write_text('partial')
    def forbidden(*args, **kwargs):
        pytest.fail('No network operation is allowed for a cached component')
    monkeypatch.setattr(EasyEDAClient, 'request', forbidden)
    monkeypatch.setattr(EasyEDAClient, 'component', forbidden)
    caplog.set_level('INFO')
    assert workflow.run_items([response['result']['uuid']], tmp_path, with_3d=True) == 0
    assert 're-converting from cache' in caplog.text
    assert (folder / 'raw.json').read_bytes() == raw
    assert list(folder.glob('*.kicad_sym')) and list(folder.glob('*.pretty/*.kicad_mod'))


def test_cached_missing_package_does_not_fetch(response, tmp_path, monkeypatch):
    folder, _ = install_cache(tmp_path, response)
    response['result'].pop('packageDetail')
    (folder / 'raw.json').write_text(json.dumps(response))
    monkeypatch.setattr(EasyEDAClient, 'component', lambda *a: pytest.fail('must stay offline'))
    assert workflow.run_items([response['result']['uuid']], tmp_path) == 1


def test_attribute_error_fails_only_one_item(tmp_path, monkeypatch, capsys):
    for uuid in (OLD, NEW):
        install_cache(tmp_path, json.loads((FIXTURES / f'{uuid}.json').read_bytes()))
    original = workflow.write_conversion
    def malformed(data, *args):
        if data['result']['uuid'] == OLD:
            raise AttributeError('injected malformed component')
        return original(data, *args)
    monkeypatch.setattr(workflow, 'write_conversion', malformed)
    assert workflow.run_items([OLD, NEW], tmp_path) == 1
    assert '1 succeeded, 1 failed, 0 skipped' in capsys.readouterr().out
    entries = (tmp_path / 'fetch_log.tsv').read_text().splitlines()
    assert f'\t{OLD}\terror' in entries[0]
    assert f'\t{NEW}\tok' in entries[1]


@pytest.mark.parametrize('delay', ['0', '0.99', '-1'])
def test_delay_minimum_cli(delay):
    result = CliRunner().invoke(app, ['fetch', NEW, '--delay', delay])
    assert result.exit_code != 0 and '1' in result.output


@pytest.mark.parametrize('delay', [0., .99, -1., float('nan'), float('inf')])
def test_delay_minimum_client(delay):
    with pytest.raises(ValueError, match='at least 1 second'):
        EasyEDAClient(delay)


def test_delay_one_second_is_valid():
    with EasyEDAClient(1.) as client:
        assert client.delay == 1.


@pytest.mark.parametrize('compact,spaced', [
    ('M0 0a5 5 0 01 5 5', 'M0 0a5 5 0 0 1 5 5'),
    ('M0 0A5 5 0 015 5', 'M0 0A5 5 0 0 1 5 5'),
    ('M0 0a5 5 0 10-5-5', 'M0 0a5 5 0 1 0 -5 -5'),
    ('M0 0a5 5 0 01 5 5 5 5 0 10-5-5', 'M0 0a5 5 0 0 1 5 5 5 5 0 1 0 -5 -5'),
])
def test_compact_arc_flags(compact, spaced):
    assert list(path_segments(compact)) == list(path_segments(spaced))


@pytest.mark.parametrize('path', ['M0 0A5 5 0 21 5 5', 'M0 0A5 5 0 -1 0 5 5'])
def test_invalid_arc_flag(path):
    with pytest.raises(ValueError, match='flag'):
        list(path_segments(path))


@pytest.mark.parametrize('retry', ['9999', 'inf', format_datetime(datetime.now(timezone.utc) + timedelta(hours=1))])
def test_retry_after_cap(retry, caplog):
    client, clock, calls = make_client([503, 200], {'Retry-After': retry})
    with client:
        client.component(NEW)
    assert clock.sleeps == [0., 300.]
    messages = [record.getMessage() for record in caplog.records if 'capped' in record.getMessage()]
    assert messages == ['Retry-After exceeds 300 seconds; capped at 300 seconds.']


@pytest.mark.parametrize('cached', [False, True])
def test_caller_relative_paths(monkeypatch, tmp_path, cached):
    caller = tmp_path / 'caller' / 'child'
    caller.mkdir(parents=True)
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (caller.parent / 'links.txt').write_text(NEW)
    monkeypatch.chdir(checkout)
    monkeypatch.setenv('EE2KICAD_CWD', str(caller))
    calls = []
    monkeypatch.setattr(workflow.EasyEDAClient, 'component', lambda *a: pytest.fail('offline'))
    monkeypatch.setattr('easyeda2kicad_local.cli.run_items', lambda items, root, **kwargs: calls.append((items, root)) or 0)
    args = ['convert', NEW] if cached else ['fetch', '--file', '../links.txt']
    args += ['--output', '../result']
    assert invoke_main(monkeypatch, args) == 0
    assert calls == [([NEW], caller.parent / 'result')]


def test_caller_default_file_and_output(monkeypatch, tmp_path):
    caller = tmp_path / 'caller'
    caller.mkdir()
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (caller / 'links.txt').write_text(NEW)
    monkeypatch.chdir(checkout)
    monkeypatch.setenv('EE2KICAD_CWD', str(caller))
    calls = []
    monkeypatch.setattr('easyeda2kicad_local.cli.run_items', lambda items, root, **kwargs: calls.append((items, root)) or 0)
    assert invoke_main(monkeypatch, [], '\n') == 0
    assert calls == [([NEW], caller / 'output')]


def test_bootstrap_hash_refresh_and_failed_install(tmp_path, monkeypatch):
    (tmp_path / '.venv').mkdir()
    project = tmp_path / 'pyproject.toml'
    project.write_text('[project]\nname="first"\n')
    marker = tmp_path / '.venv/.ee2kicad-ready'
    marker.write_text('')  # Old marker format also triggers refresh.
    calls = []
    monkeypatch.setattr(BOOTSTRAP['subprocess'], 'run', lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    assert ensure_installed(tmp_path) == 0
    assert marker.read_text().strip() == hashlib.sha256(project.read_bytes()).hexdigest()
    assert ensure_installed(tmp_path) == 0 and len(calls) == 1
    previous = marker.read_bytes()
    project.write_text('[project]\nname="second"\n')
    monkeypatch.setattr(BOOTSTRAP['subprocess'], 'run', lambda cmd, **kw: SimpleNamespace(returncode=1))
    assert ensure_installed(tmp_path) == 1
    assert marker.read_bytes() == previous
    monkeypatch.setattr(BOOTSTRAP['subprocess'], 'run', lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    assert ensure_installed(tmp_path) == 0 and len(calls) == 2
    assert marker.read_text().strip() == hashlib.sha256(project.read_bytes()).hexdigest()


def test_windows_launcher_cleanup_and_shared_bootstrap():
    # Static safeguard on non-Windows hosts; native CMD is tested separately when available.
    script = (Path(__file__).parents[1] / 'run.bat').read_text()
    assert "in ('chcp')" in script
    assert 'set "EE2KICAD_CWD=%CD%"' in script
    assert '"%~dp0scripts\\bootstrap.py"' in script
    cleanup = script.split(':finish\n')[1]
    assert 'chcp %ee_codepage%' in cleanup
    assert cleanup.index('chcp %ee_codepage%') < cleanup.index('exit /b %ee_exit%')
    assert script.count('exit /b') == 1  # All failure and success paths use cleanup.


def test_modern_footprint_properties_and_text_size(response):
    converted = convert_response(response)
    fp = sexpr(converted.footprint)
    assert one(fp, 'version')[1] == '20240108'
    properties = {p[1]: p for p in children(fp, 'property')}
    assert set(properties) == {'Reference', 'Value'}
    assert not [p for p in children(fp, 'fp_text') if p[1] in ('reference', 'value')]
    for prop in properties.values():
        assert list(map(float, one(one(one(prop, 'effects'), 'font'), 'size')[1:])) == [1.27, 1.27]
    drawing = texts(converted.symbol) + children(fp, 'fp_text')
    assert drawing
    for text in drawing:
        assert list(map(float, one(one(one(text, 'effects'), 'font'), 'size')[1:])) == [1.905, 1.905]
    # Both pin-name and pin-number fonts retain their original property size.
    for unit in children(one(sexpr(converted.symbol), 'symbol'), 'symbol'):
        for pin in children(unit, 'pin'):
            for key in ('name', 'number'):
                assert list(map(float, one(one(one(one(pin, key), 'effects'), 'font'), 'size')[1:])) == [1.27, 1.27]


def test_rotation_slot_verification_is_documented(response):
    pads = [line.split('~') for line in response['result']['packageDetail']['dataStr']['shape']
            if line.startswith('PAD~')]
    assert pads
    assert all(abs(float(p[4]) - float(p[5])) < 1e-6 for p in pads)
    assert all(float(p[13]) - 2 * float(p[9]) <= .0011 for p in pads)
    notes = (Path(__file__).parents[1] / 'docs/API_NOTES.md').read_text()
    assert 'rotation sign and slot orientation remain unverified' in notes
