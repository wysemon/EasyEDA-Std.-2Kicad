import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_workflow import install_cache, snapshot

from easyeda2kicad_local.converter import write_conversion
from easyeda2kicad_local.validation import validate_libraries
from easyeda2kicad_local.workflow import run_items


def test_missing_kicad_one_note(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: None)
    assert validate_libraries(tmp_path, 'unused')
    assert capsys.readouterr().out.splitlines() == ['Validation skipped: kicad-cli is not on PATH.']


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
    assert [call[1:4] for call in calls] == [['sym', 'upgrade', '--force'], ['fp', 'upgrade', '--force']]
    assert snapshot(tmp_path) == before
    assert all(not Path(call[-1]).exists() for call in calls)
    assert capsys.readouterr().out.count('PASS') == 2


def test_validation_failure_is_nonzero(response, tmp_path, monkeypatch, capsys):
    install_cache(tmp_path, response)
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: 'kicad-cli')
    monkeypatch.setattr('easyeda2kicad_local.validation.subprocess.run',
                        lambda *a, **kw: SimpleNamespace(returncode=1, stdout='', stderr='invalid'))
    assert run_items([response['result']['uuid']], tmp_path, cached_only=True, validate=True) == 1
    report = capsys.readouterr().out
    assert report.count('FAIL') == 2 and '0 succeeded, 1 failed, 0 skipped' in report


def test_real_kicad_upgrade(response, tmp_path):
    if not shutil.which('kicad-cli'):
        pytest.skip('Optional KiCad upgrade integration: CLI is not installed')
    c = write_conversion(response, tmp_path)
    before = snapshot(tmp_path)
    assert validate_libraries(tmp_path, c.name)
    assert snapshot(tmp_path) == before
