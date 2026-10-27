"""Offline migration, staged publication, rollback and crash-recovery checks."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_workflow import install_cache, snapshot

from easyeda2kicad_local import converter, publication
from easyeda2kicad_local.client import EasyEDAClient
from easyeda2kicad_local.converter import write_conversion
from easyeda2kicad_local.workflow import libraries_complete, run_items


@pytest.fixture(autouse=True)
def forbid_component_requests(monkeypatch):
    monkeypatch.setattr(
        EasyEDAClient, 'component', lambda *a: pytest.fail('cached operations must be offline')
    )


def legacy(response, folder, *, old_name=False):
    c = write_conversion(response, folder)
    (folder / publication.COMPLETE).unlink()
    if old_name:
        name = c.name.rsplit('_', 1)[0]
        symbol = folder / f'{c.name}.kicad_sym'
        symbol.rename(folder / f'{name}.kicad_sym')
        pretty = folder / f'{c.name}.pretty'
        pretty.rename(folder / f'{name}.pretty')
        fp = folder / f'{name}.pretty' / f'{c.name}.kicad_mod'
        fp.rename(fp.with_name(f'{name}.kicad_mod'))
        for path in [folder / f'{name}.kicad_sym', folder / f'{name}.pretty' / f'{name}.kicad_mod']:
            path.write_text(path.read_text().replace(c.name, name), encoding='utf-8')
    fp = next(folder.glob('*.pretty/*.kicad_mod'))
    fp.write_text(
        fp.read_text().rstrip()[:-1] + '\n(model "legacy.step" (offset (xyz 0 0 0)))\n)\n',
        encoding='utf-8',
    )
    return c, fp


@pytest.mark.parametrize('old_name', [False, True])
def test_legacy_3d_cache_migrates_offline_and_is_idempotent(response, tmp_path, old_name):
    folder, raw = install_cache(tmp_path, response)
    c, fp = legacy(response, folder, old_name=old_name)
    models = folder / 'legacy.3dshapes'
    models.mkdir()
    (models / 'legacy.step').write_bytes(b'user owned model')
    (folder / 'CREDITS.txt').write_text('User attribution\nkeep verbatim\n', encoding='utf-8')
    assert publication.footprint_has_model(fp)
    assert not libraries_complete(folder)
    uuid = response['result']['uuid']
    assert run_items([uuid], tmp_path) == 0
    assert libraries_complete(folder)
    assert all(not publication.footprint_has_model(p) for p in folder.glob('*.pretty/*.kicad_mod'))
    assert (folder / 'raw.json').read_bytes() == raw
    assert (models / 'legacy.step').read_bytes() == b'user owned model'
    assert (
        next(folder.glob('CREDITS.previous-*.txt')).read_text()
        == 'User attribution\nkeep verbatim\n'
    )
    assert (folder / f'{c.name}.kicad_sym').exists()
    before = snapshot(folder)
    times = {p: p.stat().st_mtime_ns for p in folder.rglob('*') if p.is_file()}
    assert run_items([uuid], tmp_path) == 0
    assert snapshot(folder) == before
    assert {p: p.stat().st_mtime_ns for p in times} == times


def test_legacy_missing_footprint_cache_fails_offline(response, tmp_path, caplog):
    folder, _ = install_cache(tmp_path, response)
    legacy(response, folder)
    response['result'].pop('packageDetail')
    raw = json.dumps(response).encode()
    (folder / 'raw.json').write_bytes(raw)
    before = snapshot(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 1
    assert snapshot(folder) == before
    assert 'Footprint fallback is not cached' in caplog.text
    assert not libraries_complete(folder)


def test_valid_pre_manifest_2d_output_is_skipped(response, tmp_path, capsys):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    (folder / publication.COMPLETE).unlink()
    assert libraries_complete(folder)
    before = snapshot(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert snapshot(folder) == before
    assert '1 skipped' in capsys.readouterr().out


def test_pre_manifest_missing_pin_is_not_skipped(response, tmp_path):
    folder, _ = install_cache(tmp_path, response)
    c = write_conversion(response, folder)
    (folder / publication.COMPLETE).unlink()
    symbol = folder / f'{c.name}.kicad_sym'
    symbol.write_text(c.symbol.replace(c.pins[0].render(), '', 1), encoding='utf-8')
    assert not libraries_complete(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert libraries_complete(folder)


def test_pre_manifest_partial_multiunit_is_rejected_without_replacing(response, tmp_path, caplog):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    (folder / publication.COMPLETE).unlink()
    response['result']['dataStr']['subparts'] = [{'shape': ['P~invalid']}, {'shape': ['P~other']}]
    (folder / 'raw.json').write_text(json.dumps(response))
    before = snapshot(folder)
    assert not libraries_complete(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 1
    assert 'Multi-unit' in caplog.text
    assert snapshot(folder) == before


def test_foreign_converter_owned_library_is_not_migrated(response, tmp_path, caplog):
    folder, _ = install_cache(tmp_path, response)
    legacy(response, folder)
    other = json.loads(json.dumps(response))
    other['result']['uuid'] = 'a' * 32
    foreign = tmp_path / 'foreign'
    c, fp = legacy(other, foreign)
    shutil.copy2(foreign / f'{c.name}.kicad_sym', folder)
    shutil.copytree(fp.parent, folder / fp.parent.name)
    kept = (folder / fp.parent.name / fp.name).read_bytes()
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert (folder / fp.parent.name / fp.name).read_bytes() == kept
    assert 'Leaving unassociated legacy library' in caplog.text
    assert libraries_complete(folder)


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize(
    'failure', ['symbol', 'footprint', 'credits', 'manifest', 'before-publish', 'during-publish']
)
def test_failure_never_publishes_partial_or_destroys_previous(
    response, tmp_path, monkeypatch, existing, failure
):
    folder = tmp_path / 'component'
    if existing:
        write_conversion(response, folder)
    folder.mkdir(exist_ok=True)
    (folder / 'keep.txt').write_text('unrelated user file')
    before = snapshot(folder)
    original_write = converter.atomic_write
    suffix = {'symbol': '.kicad_sym', 'footprint': '.kicad_mod', 'credits': 'CREDITS.txt'}.get(
        failure
    )

    def fail_write(path, content):
        if suffix and path.name.endswith(suffix):
            original_write(path, b'partial staged write')
            raise OSError('injected write failure')
        original_write(path, content)

    monkeypatch.setattr(converter, 'atomic_write', fail_write)
    if failure in ('manifest', 'before-publish'):

        def fail(*args):
            raise OSError('injected before final publish')

        monkeypatch.setattr(
            converter, 'write_manifest' if failure == 'manifest' else 'publish', fail
        )
    if failure == 'during-publish':
        original_replace = publication.os.replace
        calls = 0

        def replace(source, target):
            nonlocal calls
            if '.ee2kicad-stage-' in str(source) and Path(source).name == Path(target).name:
                calls += 1
                if calls == 2:
                    raise OSError('injected publication failure')
            original_replace(source, target)

        monkeypatch.setattr(publication.os, 'replace', replace)
    response['result']['description'] = 'Changed source to make replacement observable'
    with pytest.raises(OSError, match='injected'):
        write_conversion(response, folder)
    assert snapshot(folder) == before
    assert libraries_complete(folder) is existing
    assert not list(tmp_path.rglob('.ee2kicad-stage-*'))
    assert not list(tmp_path.rglob('.ee2kicad-backup-*'))


@pytest.mark.parametrize('existing', [False, True])
def test_failed_validation_keeps_previous_and_retry_publishes(
    response, tmp_path, monkeypatch, existing
):
    folder, raw = install_cache(tmp_path, response)
    if existing:
        write_conversion(response, folder)
    before = snapshot(folder)
    monkeypatch.setattr(converter, 'validate_libraries', lambda *a: False)
    uuid = response['result']['uuid']
    assert run_items([uuid], tmp_path, cached_only=True, validate=True) == 1
    assert snapshot(folder) == before
    assert libraries_complete(folder) is existing
    monkeypatch.setattr(converter, 'validate_libraries', lambda *a: True)
    assert run_items([uuid], tmp_path, cached_only=True, validate=True) == 0
    assert libraries_complete(folder)
    assert (folder / 'raw.json').read_bytes() == raw


def test_missing_requested_validator_cannot_skip_complete_cache(response, tmp_path, monkeypatch):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    before = snapshot(folder)
    monkeypatch.setattr('easyeda2kicad_local.validation.shutil.which', lambda _: None)
    assert run_items([response['result']['uuid']], tmp_path, validate=True) == 1
    assert snapshot(folder) == before


def test_corrupt_libraries_rebuild_and_preserve_edited_bytes(response, tmp_path):
    folder, _ = install_cache(tmp_path, response)
    c = write_conversion(response, folder)
    symbol = folder / f'{c.name}.kicad_sym'
    broken = c.symbol[: len(c.symbol) // 2]
    symbol.write_text(broken, encoding='utf-8')
    assert not libraries_complete(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert libraries_complete(folder)
    assert next(folder.glob('*.kicad_sym.previous-*')).read_text() == broken


@pytest.mark.parametrize('kind', ['symbol', 'footprint'])
@pytest.mark.parametrize('encoding', ['invalid-utf8', 'utf16'])
def test_unreadable_owned_library_rebuilds_offline_and_preserves_bytes(
    response, tmp_path, kind, encoding
):
    folder, raw = install_cache(tmp_path, response)
    c = write_conversion(response, folder)
    path = (
        folder / f'{c.name}.kicad_sym'
        if kind == 'symbol'
        else folder / f'{c.name}.pretty' / f'{c.name}.kicad_mod'
    )
    original = path.read_bytes()
    damaged = (
        b'\xff\xfe damaged\x00bytes'
        if encoding == 'invalid-utf8'
        else original.decode('utf-8').encode('utf-16')
    )
    path.write_bytes(damaged)
    assert not libraries_complete(folder)
    uuid = response['result']['uuid']
    assert run_items([uuid], tmp_path, cached_only=True) == 0
    assert libraries_complete(folder)
    assert path.read_bytes() == original
    assert next(path.parent.glob(path.name + '.previous-*')).read_bytes() == damaged
    assert (folder / 'raw.json').read_bytes() == raw
    before = snapshot(folder)
    assert run_items([uuid], tmp_path) == 0
    assert snapshot(folder) == before


def test_unreadable_unowned_library_is_never_overwritten(response, tmp_path):
    c = converter.convert_response(response)
    path = tmp_path / f'{c.name}.kicad_sym'
    path.write_bytes(b'\xff another tool or user file')
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match='Cannot confirm ownership.*move it aside'):
        write_conversion(response, tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('broken', ['', '(kicad_symbol_lib (symbol "x" (pin input line)))'])
def test_empty_or_balanced_but_incomplete_library_is_not_skipped(response, tmp_path, broken):
    folder, _ = install_cache(tmp_path, response)
    c = write_conversion(response, folder)
    (folder / f'{c.name}.kicad_sym').write_text(broken)
    assert not libraries_complete(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert libraries_complete(folder)
    assert next(folder.glob('*.kicad_sym.previous-*')).read_text() == broken


def test_balanced_incomplete_legacy_pad_is_not_complete(response, tmp_path):
    folder, _ = install_cache(tmp_path, response)
    c = write_conversion(response, folder)
    (folder / publication.COMPLETE).unlink()
    fp = folder / f'{c.name}.pretty' / f'{c.name}.kicad_mod'
    fp.write_text(f'(footprint "{c.name}" (generator "easyeda2kicad-local") (pad "1" smd rect))')
    assert not libraries_complete(folder)
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert libraries_complete(folder)
    assert list(fp.parent.glob('*.kicad_mod.previous-*'))


def test_rollback_failure_keeps_recovery_material(response, tmp_path, monkeypatch):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    before = snapshot(folder)
    original = publication.os.replace
    publishing = 0
    failed = False

    def replace(source, target):
        nonlocal publishing, failed
        if '.ee2kicad-stage-' in str(source) and Path(source).name == Path(target).name:
            publishing += 1
            if publishing == 2:
                failed = True
                raise OSError('publish interrupted')
        elif failed and Path(target).suffix == '.kicad_sym':
            raise OSError('rollback interrupted')
        return original(source, target)

    monkeypatch.setattr(publication.os, 'replace', replace)
    response['result']['description'] = 'replacement'
    with pytest.raises(OSError, match='rollback interrupted'):
        write_conversion(response, folder)
    assert (folder / publication.PENDING).exists()
    assert list(folder.glob('.ee2kicad-backup-*'))
    assert not libraries_complete(folder)
    monkeypatch.setattr(publication.os, 'replace', original)
    publication.recover(folder)
    assert snapshot(folder) == before
    assert libraries_complete(folder)


def test_legacy_migration_preserves_separate_package_cache(response, tmp_path):
    folder, _ = install_cache(tmp_path, response)
    legacy(response, folder)
    package = response['result'].pop('packageDetail')
    raw = json.dumps(response).encode()
    package_raw = json.dumps({'success': True, 'result': package}).encode()
    (folder / 'raw.json').write_bytes(raw)
    (folder / 'package_raw.json').write_bytes(package_raw)
    assert run_items([response['result']['uuid']], tmp_path) == 0
    assert (folder / 'raw.json').read_bytes() == raw
    assert (folder / 'package_raw.json').read_bytes() == package_raw
    assert libraries_complete(folder)


def test_replacement_preserves_existing_source_and_libraries_on_real_process_exit(
    response, tmp_path
):
    folder, raw = install_cache(tmp_path, response)
    write_conversion(response, folder)
    before = snapshot(folder)
    script = """
import json, os, sys
from pathlib import Path
from easyeda2kicad_local import publication
from easyeda2kicad_local.converter import write_conversion
folder = Path(sys.argv[1])
data = json.loads((folder / 'raw.json').read_bytes())
data['result']['description'] += ' replacement with changed metadata'
original = publication.os.replace
calls = 0
def crash(source, target):
    global calls
    if '.ee2kicad-stage-' in str(source) and Path(source).name == Path(target).name:
        calls += 1
        if calls == 2:
            os._exit(23)
    original(source, target)
publication.os.replace = crash
write_conversion(data, folder)
"""
    run = subprocess.run(
        [sys.executable, '-c', script, str(folder)], timeout=30, env=dict(os.environ)
    )
    assert run.returncode == 23
    assert (folder / publication.PENDING).exists()
    assert not libraries_complete(folder)
    publication.recover(folder)
    assert snapshot(folder) == before
    assert libraries_complete(folder)
    assert (folder / 'raw.json').read_bytes() == raw
    assert not list(tmp_path.rglob('.ee2kicad-stage-*'))


def test_force_does_not_replace_cache_until_validation_passes(response, tmp_path, monkeypatch):
    folder, original_raw = install_cache(tmp_path, response)
    write_conversion(response, folder)
    before = snapshot(folder)
    response['result']['description'] = 'Fresh response'
    fresh = json.dumps(response).encode()
    calls = []

    def fetch(self, uuid):
        calls.append(uuid)
        return fresh

    monkeypatch.setattr(EasyEDAClient, 'component', fetch)
    monkeypatch.setattr(converter, 'validate_libraries', lambda *a: False)
    uuid = response['result']['uuid']
    assert run_items([uuid], tmp_path, force=True, validate=True) == 1
    assert snapshot(folder) == before
    assert (folder / 'raw.json').read_bytes() == original_raw
    monkeypatch.setattr(converter, 'validate_libraries', lambda *a: True)
    assert run_items([uuid], tmp_path, force=True, validate=True) == 0
    assert (folder / 'raw.json').read_bytes() == fresh
    assert libraries_complete(folder)
    assert calls == [uuid, uuid]


@pytest.mark.parametrize('mode', ['incomplete', 'complete', 'legacy', 'pending'])
def test_dry_run_never_changes_existing_files_or_directories(response, tmp_path, mode):
    folder, _ = install_cache(tmp_path, response)
    if mode in ('complete', 'pending'):
        write_conversion(response, folder)
    if mode == 'legacy':
        legacy(response, folder)
    if mode == 'pending':
        (folder / publication.PENDING).write_text('invalid journal must not be touched by dry run')
    before = snapshot(tmp_path)
    paths = set(tmp_path.rglob('*'))
    assert run_items([response['result']['uuid']], tmp_path, force=True, dry_run=True) == 0
    assert snapshot(tmp_path) == before
    assert set(tmp_path.rglob('*')) == paths


def test_unrelated_library_is_not_overwritten(response, tmp_path):
    name = converter.convert_response(response).name
    target = tmp_path / f'{name}.kicad_sym'
    target.write_text('(kicad_symbol_lib (generator "another-tool"))')
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match='unrelated library'):
        write_conversion(response, tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('uuid', ['../escape', '/absolute', 'a' * 31, 'a' * 32 + '/../../x'])
def test_response_uuid_cannot_escape_output(response, tmp_path, uuid):
    response['result']['uuid'] = uuid
    with pytest.raises(ValueError, match='invalid component UUID'):
        write_conversion(response, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(os.name == 'nt', reason='Symlink creation requires Windows privileges')
def test_output_symlink_is_not_followed(response, tmp_path):
    c = converter.convert_response(response)
    folder = tmp_path / 'out'
    folder.mkdir()
    outside = tmp_path / 'user-file'
    outside.write_bytes(b'keep outside bytes')
    (folder / f'{c.name}.kicad_sym').symlink_to(outside)
    with pytest.raises(ValueError, match='symlink'):
        write_conversion(response, folder)
    assert outside.read_bytes() == b'keep outside bytes'


@pytest.mark.parametrize('text', ['(', ')', '(a) (b)', '(a "unterminated)', '(a))'])
def test_strict_reader_rejects_partial_and_malformed_data(text):
    with pytest.raises(ValueError):
        publication.loads(text)


def test_model_word_in_text_is_not_a_model_reference(tmp_path):
    path = tmp_path / 'test.kicad_mod'
    path.write_text('(footprint "x" (fp_text user "(model not a reference)"))')
    assert not publication.footprint_has_model(path)
