"""Full component identity must agree before a cache can be skipped or replaced."""

import copy
import json

import pytest
from test_workflow import install_cache, snapshot

from easyeda2kicad_local.client import EasyEDAClient
from easyeda2kicad_local.converter import convert_response, write_conversion
from easyeda2kicad_local.publication import COMPLETE, digest, libraries_complete
from easyeda2kicad_local.workflow import run_items


def colliding_component(response):
    other = copy.deepcopy(response)
    uuid = response['result']['uuid']
    other['result']['uuid'] = uuid[:8] + ('a' if uuid[8] != 'a' else 'b') + uuid[9:]
    assert convert_response(other).name == convert_response(response).name
    return other


@pytest.mark.parametrize('force', [False, True])
@pytest.mark.parametrize('remaining', ['all', 'raw', 'manifest', 'symbol'])
def test_colliding_uuid_prefix_cannot_overwrite_any_cache(
    response, tmp_path, monkeypatch, caplog, force, remaining
):
    folder, raw = install_cache(tmp_path, response)
    write_conversion(response, folder)
    if remaining != 'all':
        for path in list(folder.rglob('*')):
            if path.is_file() and not (
                remaining == 'raw'
                and path.name == 'raw.json'
                or remaining == 'manifest'
                and path.name == COMPLETE
                or remaining == 'symbol'
                and path.suffix == '.kicad_sym'
            ):
                path.unlink()
    (folder / 'notes.txt').write_bytes(b'User notes must survive.\n')
    before = snapshot(folder)
    other = colliding_component(response)
    calls = []

    def component(self, uuid):
        calls.append(uuid)
        return json.dumps(other).encode()

    monkeypatch.setattr(EasyEDAClient, 'component', component)
    uuid = other['result']['uuid']
    assert run_items([uuid], tmp_path, force=force) == 1
    assert calls == [uuid]
    assert 'identity conflict' in caplog.text and '--output' in caplog.text
    assert snapshot(folder) == before
    if remaining in ('all', 'raw'):
        assert (folder / 'raw.json').read_bytes() == raw


def test_direct_conversion_refuses_same_prefix_component(response, tmp_path):
    folder = tmp_path / 'component'
    write_conversion(response, folder)
    before = snapshot(folder)
    with pytest.raises(ValueError, match='identity conflict'):
        write_conversion(colliding_component(response), folder)
    assert snapshot(folder) == before


@pytest.mark.parametrize(
    'source', ['manifest', 'raw', 'symbol', 'footprint', 'symbol-name', 'link']
)
def test_cache_completion_checks_identity_beyond_hashes(response, tmp_path, source):
    folder, _ = install_cache(tmp_path, response)
    converted = write_conversion(response, folder)
    manifest = folder / COMPLETE
    data = json.loads(manifest.read_bytes())
    uuid = response['result']['uuid']
    other_uuid = colliding_component(response)['result']['uuid']
    if source == 'manifest':
        data['uuid'] = other_uuid
    else:
        path = {
            'raw': folder / 'raw.json',
            'symbol': folder / f'{converted.name}.kicad_sym',
            'symbol-name': folder / f'{converted.name}.kicad_sym',
            'link': folder / f'{converted.name}.kicad_sym',
            'footprint': folder / f'{converted.name}.pretty' / f'{converted.name}.kicad_mod',
        }[source]
        text = path.read_text(encoding='utf-8')
        if source in ('raw', 'symbol'):
            text = text.replace(uuid, other_uuid)
        elif source in ('symbol-name', 'footprint'):
            text = text.replace(f'"{converted.name}"', '"another-name"', 1)
        else:
            text = text.replace(f'"{converted.name}:{converted.name}"', '"wrong:footprint"')
        path.write_text(text, encoding='utf-8')
        data['files'][path.relative_to(folder).as_posix()] = digest(path)
    manifest.write_text(json.dumps(data), encoding='utf-8')
    assert not libraries_complete(folder)


@pytest.mark.parametrize('metadata', ['raw.json', COMPLETE])
def test_conflicting_cache_identity_fails_offline_without_repairing_over_it(
    response, tmp_path, monkeypatch, caplog, metadata
):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    uuid = response['result']['uuid']
    other_uuid = colliding_component(response)['result']['uuid']
    path = folder / metadata
    path.write_text(path.read_text().replace(uuid, other_uuid), encoding='utf-8')
    # Select the raw identity; completion metadata must still agree.
    requested = other_uuid if metadata == 'raw.json' else uuid
    before = snapshot(folder)
    monkeypatch.setattr(EasyEDAClient, 'component', lambda *a: pytest.fail('must stay offline'))
    assert run_items([requested], tmp_path, cached_only=True) == 1
    assert snapshot(folder) == before
    assert 'identity conflict' in caplog.text


def test_uuid_case_is_not_an_identity_conflict(response, tmp_path):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    manifest = folder / COMPLETE
    data = json.loads(manifest.read_bytes())
    data['uuid'] = data['uuid'].upper()
    manifest.write_text(json.dumps(data), encoding='utf-8')
    assert libraries_complete(folder, expected_uuid=response['result']['uuid'].upper())
    assert not libraries_complete(
        folder, expected_uuid=colliding_component(response)['result']['uuid']
    )


def test_legacy_output_still_requires_matching_source_identity(response, tmp_path):
    folder, _ = install_cache(tmp_path, response)
    write_conversion(response, folder)
    (folder / COMPLETE).unlink()
    assert libraries_complete(folder)
    raw = folder / 'raw.json'
    raw.write_text(
        raw.read_text().replace(
            response['result']['uuid'], colliding_component(response)['result']['uuid']
        )
    )
    assert not libraries_complete(folder)
