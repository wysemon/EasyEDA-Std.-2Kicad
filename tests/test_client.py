import httpx
import pytest
from conftest import NEW

from easyeda2kicad_local.client import HEADERS, EasyEDAClient, FetchError, StopRun, parse_uuid


@pytest.mark.parametrize('text', [NEW, NEW.upper(), f'https://easyeda.com/component/{NEW}/?abc=1'])
def test_input(text):
    assert parse_uuid(text) == NEW


@pytest.mark.parametrize('text', ['abc', f'https://evil.test/component/{NEW}',
                                  f'https://easyeda.com@evil.test/component/{NEW}',
                                  f'http://easyeda.com/component/{NEW}', f'https://easyeda.com/foo/{NEW}'])
def test_reject_input(text):
    with pytest.raises(ValueError):
        parse_uuid(text)


class Clock:
    now = 100.

    def __init__(self):
        self.sleeps = []

    def sleep(self, value):
        self.sleeps.append(value)
        self.now += value


def make_client(statuses, headers=None):
    calls = []
    queue = iter(statuses)
    clock = Clock()

    def handler(request):
        calls.append(request)
        status = next(queue)
        return httpx.Response(status, headers=headers or {}, json={'success': True})

    client = EasyEDAClient(client=httpx.Client(transport=httpx.MockTransport(handler)),
                          sleep=clock.sleep, clock=lambda: clock.now, jitter=lambda: 1.)
    return client, clock, calls


def test_pacing_and_headers():
    client, clock, calls = make_client([200, 200])
    with client:
        client.component(NEW)
        client.component(NEW)
    assert clock.sleeps == [0., 5.]
    request = calls[0]
    assert request.url.host == 'easyeda.com'
    assert dict(request.url.params) == {'version': '6.5.60', 'uuid': NEW}
    for key, value in HEADERS.items():
        assert request.headers[key] == value


def test_backoff_max_tries():
    client, clock, calls = make_client([503, 503, 503])
    with client, pytest.raises(FetchError, match='after 3 tries'):
        client.component(NEW)
    assert clock.sleeps == [0., 30., 60.] and len(calls) == 3


def test_retry_after():
    client, clock, calls = make_client([429, 200], {'Retry-After': '75'})
    with client:
        client.component(NEW)
    assert clock.sleeps == [0., 75.]


def test_cross_item_stop():
    client, clock, calls = make_client([403, 429])
    with client, pytest.raises(StopRun):
        client.component(NEW)
    assert len(calls) == 2


def test_redirect_not_followed():
    client, clock, calls = make_client([302], {'Location': 'https://evil.test'})
    with client, pytest.raises(FetchError, match='redirects'):
        client.component(NEW)
    assert len(calls) == 1


def test_reject_destination():
    client, clock, calls = make_client([])
    with client, pytest.raises(FetchError, match='Refusing'):
        client.request('https://evil.test/')
    assert not calls


@pytest.mark.parametrize('host', ['easyeda.com', 'www.easyeda.com', 'WWW.EASYEDA.COM'])
@pytest.mark.parametrize('suffix', ['', '/', '?a=1', '#pin1', '/?a=1#pin1'])
def test_url_variants(host, suffix):
    assert parse_uuid(f'https://{host}/component/{NEW}{suffix}') == NEW


@pytest.mark.parametrize('host', ['www.easyeda.com.evil.test', 'easyeda.com.evil.test',
                                  'evil.test', 'easyeda.com:443', 'user@easyeda.com'])
def test_reject_host_variants(host):
    with pytest.raises(ValueError):
        parse_uuid(f'https://{host}/component/{NEW}')


def test_editor_version_constant_is_sent():
    from easyeda2kicad_local.client import EDITOR_VERSION
    client, clock, calls = make_client([200])
    with client:
        client.component(NEW)
    assert EDITOR_VERSION == '6.5.60'
    assert calls[0].url.params['version'] == EDITOR_VERSION
