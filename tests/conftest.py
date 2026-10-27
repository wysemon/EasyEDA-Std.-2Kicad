import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / 'fixtures'
OLD = '7db93ef938c54a728e02f6579db05977'
NEW = 'f6ad09a5a9e24d199330c64690aa6c38'


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
