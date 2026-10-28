"""The CLI and network client expose only symbol/footprint conversion."""

import copy

import httpx
import pytest
from test_new_fixtures import SX, load
from typer.testing import CliRunner

from euc2k.cli import app
from euc2k.client import EasyEDAClient, FetchError
from euc2k.converter import convert_response
from euc2k.workflow import run_items


def test_removed_model_option_is_rejected():
    runner = CliRunner()
    help_result = runner.invoke(app, ['fetch', '--help'])
    assert '--3d' not in help_result.output
    result = runner.invoke(app, ['fetch', SX, '--3d'])
    assert result.exit_code != 0 and 'No such option' in result.output


def test_model_host_is_rejected_without_request():
    calls = []

    def request(req):
        calls.append(req)
        return httpx.Response(200)

    with EasyEDAClient(client=httpx.Client(transport=httpx.MockTransport(request))) as client:
        with pytest.raises(FetchError, match='Refusing destination'):
            client.request('https://modules.easyeda.com/example')
    assert not calls


def test_source_model_metadata_has_no_effect_on_2d():
    original = load(SX)
    without_metadata = copy.deepcopy(original)
    data = without_metadata['result']['packageDetail']['dataStr']
    data['shape'] = [record for record in data['shape'] if not record.startswith('SVGNODE~')]
    assert convert_response(original) == convert_response(without_metadata)


def test_fetch_with_source_model_metadata_only_writes_2d(tmp_path, monkeypatch):
    import json

    data = load(SX)

    def forbid_request(*args, **kwargs):
        pytest.fail('There must be no secondary model request')

    monkeypatch.setattr(EasyEDAClient, 'component', lambda self, uuid: json.dumps(data).encode())
    monkeypatch.setattr(EasyEDAClient, 'request', forbid_request)
    assert run_items([SX], tmp_path) == 0
    files = [p for p in tmp_path.rglob('*') if p.is_file()]
    assert {p.suffix for p in files} == {'.kicad_sym', '.kicad_mod', '.txt', '.json', '.tsv'}
    assert all(
        '(model ' not in p.read_text(encoding='utf-8') for p in files if p.suffix == '.kicad_mod'
    )
