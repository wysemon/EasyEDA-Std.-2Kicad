import copy
import json

from conftest import FIXTURES
from typer.testing import CliRunner

from easyeda2kicad_local.cli import app
from easyeda2kicad_local.client import EasyEDAClient, StopRun
from easyeda2kicad_local.converter import safe_name
from easyeda2kicad_local.workflow import run_items


def install_cache(tmp_path, response):
    result = response['result']
    folder = tmp_path / f'{safe_name(result["title"])}_{result["uuid"][:8]}'
    folder.mkdir()
    raw = (FIXTURES / f'{result["uuid"]}.json').read_bytes()
    (folder / 'raw.json').write_bytes(raw)
    return folder, raw


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_cached_convert_and_dry_run(response, tmp_path):
    folder, raw = install_cache(tmp_path, response)
    uuid = response['result']['uuid']
    before = snapshot(tmp_path)
    assert run_items([uuid], tmp_path, dry_run=True, force=True) == 0
    assert snapshot(tmp_path) == before
    assert run_items([uuid], tmp_path, cached_only=True) == 0
    assert (folder / 'raw.json').read_bytes() == raw
    assert list(folder.glob('*.kicad_sym')) and list(folder.glob('*.pretty/*.kicad_mod'))
    assert run_items([uuid], tmp_path) == 0
    assert 'skipped' in (tmp_path / 'fetch_log.tsv').read_text()


def test_fetch_success_and_force(response, tmp_path, monkeypatch):
    raw = (FIXTURES / f'{response["result"]["uuid"]}.json').read_bytes()
    calls = []

    def component(self, uuid):
        calls.append(uuid)
        return raw

    monkeypatch.setattr(EasyEDAClient, 'component', component)
    uuid = response['result']['uuid']
    assert run_items([uuid], tmp_path) == 0
    assert run_items([uuid], tmp_path) == 0
    assert run_items([uuid], tmp_path, force=True) == 0
    assert calls == [uuid, uuid]
    assert next(tmp_path.glob('*/raw.json')).read_bytes() == raw


def test_fallback_is_separate_and_offline(response, tmp_path, monkeypatch):
    original = copy.deepcopy(response)
    package = original['result'].pop('packageDetail')
    calls = []

    def component(self, uuid):
        calls.append(uuid)
        return json.dumps(original if uuid == original['result']['uuid'] else
                          {'success': True, 'result': package}).encode()

    monkeypatch.setattr(EasyEDAClient, 'component', component)
    uuid = original['result']['uuid']
    assert run_items([uuid], tmp_path) == 0
    assert calls == [uuid, package['uuid']]
    assert 'packageDetail' not in json.loads(next(tmp_path.glob('*/raw.json')).read_bytes())['result']
    assert next(tmp_path.glob('*/package_raw.json')).exists()
    assert run_items([uuid], tmp_path, cached_only=True) == 0
    assert len(calls) == 2


def test_private_continues_and_stop_aborts(response, tmp_path, monkeypatch):
    uuid = response['result']['uuid']
    monkeypatch.setattr(EasyEDAClient, 'component', lambda self, u: b'{"success":false}')
    assert run_items([uuid, '0' * 32], tmp_path) == 1
    assert len((tmp_path / 'fetch_log.tsv').read_text().splitlines()) == 2

    def stop(*args):
        raise StopRun('stopping')

    monkeypatch.setattr(EasyEDAClient, 'component', stop)
    assert run_items([uuid, '0' * 32], tmp_path) == 1
    assert len((tmp_path / 'fetch_log.tsv').read_text().splitlines()) == 3


def test_cli_file_and_errors(response, tmp_path):
    folder, raw = install_cache(tmp_path, response)
    uuid = response['result']['uuid']
    runner = CliRunner()
    links = tmp_path / 'links.txt'
    links.write_text(f'# comment\n\nhttps://easyeda.com/component/{uuid}/?a=1\n{uuid}\n')
    assert runner.invoke(app, ['fetch', '--file', str(links), '-o', str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ['convert', uuid, '-o', str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ['fetch']).exit_code != 0
    assert runner.invoke(app, ['fetch', 'garbage']).exit_code != 0
    assert runner.invoke(app, ['fetch', uuid, '--delay', '-1']).exit_code != 0
    assert runner.invoke(app, ['convert', '0' * 32, '-o', str(tmp_path)]).exit_code != 0


def test_log_failure_does_not_mislabel_committed_conversion(response, tmp_path, monkeypatch, capsys, caplog):
    from easyeda2kicad_local import workflow

    folder, _ = install_cache(tmp_path, response)
    def fail_log(*args):
        raise OSError('log is not writable')
    monkeypatch.setattr(workflow, 'append_log', fail_log)
    uuid = response['result']['uuid']
    assert run_items([uuid], tmp_path) == 0
    assert workflow.libraries_complete(folder)
    assert '1 succeeded, 0 failed' in capsys.readouterr().out
    assert 'Could not write fetch log' in caplog.text
    assert run_items([uuid], tmp_path) == 0
    assert '0 failed, 1 skipped' in capsys.readouterr().out
