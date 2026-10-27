"""Bound pathological local input and parser amplification without timing tests."""

import httpx
import pytest
from conftest import NEW
from test_client import Clock
from test_workflow import install_cache, snapshot

from easyeda2kicad_local import client, converter, files, geometry, sexpr, shared, workflow
from easyeda2kicad_local.client import EasyEDAClient, FetchError


def test_bounded_read_preserves_bytes_and_rejects_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(files, 'MAX_INPUT_BYTES', 8)
    path = tmp_path / 'raw.json'
    original = b'\xef\xbb\xbf\r\n123'
    path.write_bytes(original)
    assert files.read_limited(path) == original
    path.write_bytes(original + b'!')
    with pytest.raises(ValueError, match='byte limit'):
        files.read_limited(path)
    assert path.read_bytes() == original + b'!'


def test_response_limit_runs_before_decoding(monkeypatch):
    monkeypatch.setattr(workflow, 'MAX_INPUT_BYTES', 4)
    with pytest.raises(FetchError, match='exceeds supported size'):
        workflow.read_response(b'not JSON')


def test_http_response_is_bounded_closed_and_next_item_remains_paced(monkeypatch):
    class Body(httpx.SyncByteStream):
        read = 0
        closed = False

        def __iter__(self):
            for _ in range(10):
                self.read += 1
                yield b'x' * 65_536

        def close(self):
            self.closed = True

    body, clock, calls = Body(), Clock(), []

    def handle(request):
        calls.append(request)
        return (
            httpx.Response(200, stream=body)
            if len(calls) == 1
            else httpx.Response(200, content=b'raw\r\n')
        )

    monkeypatch.setattr(client, 'MAX_INPUT_BYTES', 65_536)
    with EasyEDAClient(
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        sleep=clock.sleep,
        clock=lambda: clock.now,
        jitter=lambda: 1,
    ) as connection:
        with pytest.raises(FetchError, match='exceeds'):
            connection.component(NEW)
        assert body.read == 2 and body.closed
        assert connection.component(NEW) == b'raw\r\n'
    assert clock.sleeps == [0, 5] and len(calls) == 2


def test_failed_stream_closes_and_keeps_the_cooldown():
    class BrokenBody(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b'partial'
            raise httpx.ReadError('connection lost')

        def close(self):
            self.closed = True

    body, clock = BrokenBody(), Clock()
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=body)))
    with EasyEDAClient(
        client=http, sleep=clock.sleep, clock=lambda: clock.now, jitter=lambda: 1
    ) as connection:
        with pytest.raises(FetchError, match='Network request failed.*ReadError'):
            connection.component(NEW)
        assert body.closed and connection.next_request == clock.now + 5


def test_oversized_success_still_resets_consecutive_denials(monkeypatch):
    statuses, clock, calls = iter([403, 200, 403, 200]), Clock(), []

    def handle(request):
        calls.append(request)
        return httpx.Response(next(statuses), content=b'too large' if len(calls) == 2 else b'ok')

    monkeypatch.setattr(client, 'MAX_INPUT_BYTES', 2)
    http = httpx.Client(transport=httpx.MockTransport(handle))
    with EasyEDAClient(
        client=http, sleep=clock.sleep, clock=lambda: clock.now, jitter=lambda: 1
    ) as connection:
        with pytest.raises(FetchError, match='exceeds'):
            connection.component(NEW)
        assert connection.component(NEW) == b'ok'
    assert clock.sleeps == [0, 30, 5, 30] and len(calls) == 4


@pytest.mark.parametrize('parser', [geometry.numbers, lambda p: list(geometry.path_segments(p))])
def test_geometry_text_limit(parser, monkeypatch):
    monkeypatch.setattr(geometry, 'MAX_GEOMETRY_CHARS', 8)
    assert parser('M0 0L1 1')
    with pytest.raises(ValueError, match='exceeds supported size'):
        parser('M0 0L1 1 ')


def test_point_limit_counts_arc_sampling_and_number_lists(monkeypatch):
    monkeypatch.setattr(geometry, 'MAX_GEOMETRY_POINTS', 4)
    assert len(geometry.point_pairs('0 0 1 1 2 2 3 3')) == 4
    with pytest.raises(ValueError, match='point count'):
        geometry.point_pairs('0 0 1 1 2 2 3 3 4 4')
    assert len(list(geometry.path_segments('M0 0L1 1L2 2'))) == 2
    with pytest.raises(ValueError, match='point count'):
        list(geometry.path_segments('M0 0L1 1L2 2L3 3'))
    with pytest.raises(ValueError, match='point count'):
        list(geometry.path_segments('M0 0A10 5 0 0 1 10 5'))


def test_nonfinite_svg_coordinates_fail_before_arc_math():
    with pytest.raises(ValueError, match='nonfinite SVG coordinate'):
        list(geometry.path_segments('M0 0A1e999 5 0 0 1 10 5'))


def test_expression_depth_and_token_limits(monkeypatch):
    assert sexpr.loads('(' * sexpr.MAX_DEPTH + 'x' + ')' * sexpr.MAX_DEPTH)
    with pytest.raises(ValueError, match='nesting depth'):
        sexpr.loads('(' * (sexpr.MAX_DEPTH + 1) + 'x' + ')' * (sexpr.MAX_DEPTH + 1))
    monkeypatch.setattr(sexpr, 'MAX_TOKENS', 5)
    assert sexpr.loads('(a b c)') == ['a', 'b', 'c']
    with pytest.raises(ValueError, match='token count'):
        sexpr.loads('(a b c d)')


def test_expression_size_limit(monkeypatch):
    monkeypatch.setattr(sexpr, 'MAX_INPUT_BYTES', 3)
    assert sexpr.loads('(a)') == ['a']
    with pytest.raises(ValueError, match='exceeds supported size'):
        sexpr.loads('(aa)')


def test_flat_expression_does_not_repeatedly_copy_its_remaining_input():
    class TrackedText(str):
        copied = 0

        def __getitem__(self, key):
            value = super().__getitem__(key)
            if isinstance(key, slice):
                self.copied += len(value)
            return value

    text = TrackedText('(root' + ' value' * 5_000 + ')  \n')
    assert len(sexpr.loads(text)) == 5_001
    assert text.copied <= len(text)


def test_source_record_and_document_limits(monkeypatch):
    monkeypatch.setattr(shared, 'MAX_SHAPES', 2)
    assert shared.document({'shape': ['R~0', 'R~1']})['shape'] == ['R~0', 'R~1']
    with pytest.raises(ValueError, match='geometry exceeds supported size'):
        shared.document({'shape': ['R~0'] * 3})
    monkeypatch.setattr(shared, 'MAX_INPUT_BYTES', 8)
    with pytest.raises(ValueError, match='document exceeds supported size'):
        shared.document('{"shape": []}')
    with pytest.raises(ValueError, match='geometry exceeds supported size'):
        shared.document({'shape': ['R~' + '0' * 7]})


@pytest.mark.parametrize('side', ['symbol', 'footprint'])
def test_component_primitive_budget_is_fatal_and_preserves_cache(
    response, tmp_path, monkeypatch, caplog, side
):
    folder, raw = install_cache(tmp_path, response)
    converter.write_conversion(response, folder, sources={'raw.json': raw})
    before = snapshot(folder)
    monkeypatch.setattr(converter, 'MAX_PRIMITIVES', 100)
    monkeypatch.setattr(converter, f'{side}_graphic', lambda *a: ['injected primitive'] * 101)
    monkeypatch.setattr(EasyEDAClient, 'component', lambda *a: pytest.fail('offline only'))
    assert workflow.run_items([response['result']['uuid']], tmp_path, cached_only=True) == 1
    assert snapshot(folder) == before
    assert f'{side} exceeds supported primitive count' in caplog.text
