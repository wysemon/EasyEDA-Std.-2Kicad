import json
import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / 'fixtures'
OLD = '7db93ef938c54a728e02f6579db05977'
NEW = 'f6ad09a5a9e24d199330c64690aa6c38'


def pytest_configure(config):
    if os.environ.get('EE2KICAD_REQUIRE_KICAD') and not shutil.which('kicad-cli'):
        raise pytest.UsageError(
            'Native integration requires kicad-cli on PATH; no silent skip is allowed'
        )


@pytest.fixture(autouse=True)
def native_kicad_requirement(request):
    if request.node.get_closest_marker('kicad') and not shutil.which('kicad-cli'):
        pytest.skip('Optional native integration: kicad-cli is not installed')


@pytest.fixture(params=[OLD, NEW])
def response(request):
    return json.loads((FIXTURES / f'{request.param}.json').read_bytes())


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch, request):
    import httpx

    if request.node.get_closest_marker('live'):
        if os.environ.get('CI') or os.environ.get('EE2KICAD_DISABLE_LIVE'):
            pytest.skip('Live network tests are disabled in CI and by EE2KICAD_DISABLE_LIVE')
        return

    def refuse(*args, **kwargs):
        raise AssertionError('Live HTTP is forbidden in tests')

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', refuse)
