import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_workflow import install_cache, snapshot

from easyeda2kicad_local.converter import write_conversion
from easyeda2kicad_local.validation import validate_libraries
from easyeda2kicad_local.workflow import run_items


def test_missing_kicad_one_note(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: None)
    assert not validate_libraries(tmp_path, 'unused')
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and 'Validation unavailable' in lines[0] and 'PATH' in lines[0]


def test_validation_uses_disposable_copies(response, tmp_path, monkeypatch, capsys):
    c = write_conversion(response, tmp_path)
    before = snapshot(tmp_path)
    calls = []
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: 'kicad-cli')

    def upgrade(args, **kwargs):
        calls.append(args)
        copy = Path(args[-1])
        assert not copy.is_relative_to(tmp_path)
        if args[1] == 'sym':
            copy.write_text('upgraded symbol')
        else:
            next(copy.glob('*.kicad_mod')).write_text('upgraded footprint')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('easyeda2kicad_local.validation.subprocess.run', upgrade)
    assert validate_libraries(tmp_path, c.name)
    assert [call[1:4] for call in calls] == [
        ['sym', 'upgrade', '--force'],
        ['fp', 'upgrade', '--force'],
    ]
    assert snapshot(tmp_path) == before
    assert all(not Path(call[-1]).exists() for call in calls)
    assert capsys.readouterr().out.count('PASS') == 2


def test_validation_failure_is_nonzero(response, tmp_path, monkeypatch, capsys):
    install_cache(tmp_path, response)
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: 'kicad-cli')
    monkeypatch.setattr(
        'easyeda2kicad_local.validation.subprocess.run',
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout='', stderr='invalid'),
    )
    assert run_items([response['result']['uuid']], tmp_path, cached_only=True, validate=True) == 1
    report = capsys.readouterr().out
    assert report.count('FAIL') == 2 and '0 succeeded, 1 failed, 0 skipped' in report


@pytest.mark.parametrize('failure', ['sym', 'fp', 'timeout', 'os-error'])
def test_independent_validation_failures_keep_originals(
    response, tmp_path, monkeypatch, capsys, caplog, failure
):
    c = write_conversion(response, tmp_path)
    before = snapshot(tmp_path)
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: 'kicad-cli')
    calls = []

    def upgrade(args, **kwargs):
        calls.append(args)
        if failure == 'timeout' and args[1] == 'sym':
            raise subprocess.TimeoutExpired(args, 60)
        if failure == 'os-error' and args[1] == 'sym':
            raise OSError('executable unavailable')
        return SimpleNamespace(returncode=int(args[1] == failure), stdout='', stderr='invalid')

    monkeypatch.setattr('easyeda2kicad_local.validation.subprocess.run', upgrade)
    assert not validate_libraries(tmp_path, c.name)
    assert [call[1] for call in calls] == ['sym', 'fp']
    assert snapshot(tmp_path) == before
    report = capsys.readouterr().out
    assert report.count('FAIL') == report.count('PASS') == 1
    if failure == 'timeout':
        assert 'timed out after 60 seconds' in caplog.text
    if failure == 'os-error':
        assert 'check the KiCad installation' in caplog.text
    assert all(not Path(call[-1]).exists() for call in calls)


def test_validation_does_not_copy_unrelated_model_or_user_files(response, tmp_path, monkeypatch):
    c = write_conversion(response, tmp_path)
    pretty = tmp_path / f'{c.name}.pretty'
    (pretty / 'user.step').write_bytes(b'unrelated model bytes')
    (pretty / 'notes.txt').write_text('keep')
    before = snapshot(tmp_path)
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: 'kicad-cli')

    def upgrade(args, **kwargs):
        if args[1] == 'fp':
            assert {p.suffix for p in Path(args[-1]).iterdir()} == {'.kicad_mod'}
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('easyeda2kicad_local.validation.subprocess.run', upgrade)
    assert validate_libraries(tmp_path, c.name)
    assert snapshot(tmp_path) == before


@pytest.mark.kicad
def test_real_kicad_upgrade(response, tmp_path):
    if not shutil.which('kicad-cli'):
        pytest.skip('Optional KiCad upgrade integration: CLI is not installed')
    c = write_conversion(response, tmp_path)
    before = snapshot(tmp_path)
    assert validate_libraries(tmp_path, c.name)
    assert snapshot(tmp_path) == before
