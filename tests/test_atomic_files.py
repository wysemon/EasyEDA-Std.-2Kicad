from pathlib import Path

import pytest

from easyeda2kicad_local import files
from easyeda2kicad_local.converter import write_conversion
from easyeda2kicad_local.workflow import libraries_complete


@pytest.mark.parametrize(
    'name', ['test.kicad_sym', 'test.kicad_mod', 'CREDITS.txt', 'raw.json', 'package_raw.json']
)
@pytest.mark.parametrize('exists', [False, True])
def test_mid_write_failure_preserves_original_and_cleans_temp(name, exists, tmp_path, monkeypatch):
    target = tmp_path / name
    if exists:
        target.write_bytes(b'original complete data')
    original_temp = files.tempfile.NamedTemporaryFile

    def fail_temp(*args, **kwargs):
        stream = original_temp(*args, **kwargs)
        original_write = stream.write

        def partial_write(data):
            original_write(data[: len(data) // 2])
            raise OSError('simulated interruption mid-write')

        stream.write = partial_write
        return stream

    monkeypatch.setattr(files.tempfile, 'NamedTemporaryFile', fail_temp)
    with pytest.raises(OSError, match='mid-write'):
        files.atomic_write(target, b'new complete data')
    assert target.exists() is exists
    if exists:
        assert target.read_bytes() == b'original complete data'
    assert not list(tmp_path.glob('.*.tmp'))


def test_replace_is_in_same_directory_and_preserves_utf8(tmp_path, monkeypatch):
    original_replace = files.os.replace

    def replace(source, destination):
        assert Path(source).parent == Path(destination).parent
        return original_replace(source, destination)

    monkeypatch.setattr(files.os, 'replace', replace)
    target = tmp_path / 'CREDITS.txt'
    files.atomic_write(target, '作者\r\nOriginal license')
    assert target.read_bytes() == '作者\r\nOriginal license'.encode('utf-8')


def test_interrupted_conversion_cannot_look_complete(response, tmp_path, monkeypatch):
    def fail_replace(*args):
        raise OSError('interrupted before replace')

    monkeypatch.setattr(files.os, 'replace', fail_replace)
    with pytest.raises(OSError):
        write_conversion(response, tmp_path)
    assert not libraries_complete(tmp_path)
    assert not list(tmp_path.rglob('*.tmp'))
