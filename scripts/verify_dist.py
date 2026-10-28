"""Smoke-check an installed release in an isolated environment, without HTTP."""

import argparse
import json
import subprocess
import sys
import sysconfig
import tempfile
from importlib.metadata import distribution
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    args = parser.parse_args()
    import httpx

    from euc2k import __version__
    from euc2k.publication import libraries_complete
    from euc2k.workflow import run_items

    metadata = distribution('euc2k')
    assert metadata.version == __version__ == args.version
    assert {e.name: e.value for e in metadata.entry_points if e.group == 'console_scripts'} == {
        'euc2k': 'euc2k.cli:main'
    }
    command = Path(sysconfig.get_path('scripts')) / (
        'euc2k.exe' if sys.platform == 'win32' else 'euc2k'
    )

    def run(arguments, cwd, *, stdin=None, expected=0):
        result = subprocess.run(
            arguments,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return result.stdout + result.stderr

    def refuse(*unused_args, **unused_kwargs):
        raise AssertionError('Network is forbidden during installed-package smoke checks')

    httpx.HTTPTransport.handle_request = refuse
    with tempfile.TemporaryDirectory(prefix='euc2k-installed-') as temporary:
        root = Path(temporary)
        assert run([str(command), '--version'], root).strip() == f'euc2k {args.version}'
        assert (
            run([sys.executable, '-m', 'euc2k', '--version'], root).strip()
            == f'euc2k {args.version}'
        )
        assert run([str(command), '--help'], root).startswith(
            'euc2k: EasyEDA User Contributed To KiCad'
        )
        assert 'nothing to do' in run([str(command)], root, stdin='\n')
        assert 'nothing to do' in run([sys.executable, '-m', 'euc2k'], root, stdin='\n')
        assert 'Invalid input' in run([str(command), 'invalid-input'], root, expected=1)
        assert not (root / 'output').exists()
        items = [
            '7db93ef938c54a728e02f6579db05977',
            '0010e6e3c07c4ca9b85cbb34a79052f3',
            '82015f7d9a6543b7b998917289a50b78',
        ]
        for uuid in items:
            folder = root / uuid
            folder.mkdir()
            raw = (args.fixtures / f'{uuid}.json').read_bytes()
            assert json.loads(raw)['result']['uuid'] == uuid
            (folder / 'raw.json').write_bytes(raw)
            (folder / 'user.txt').write_bytes(b'preserve user files')
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        assert run_items(items, root, cached_only=True, dry_run=True) == 0
        assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
        assert run_items(items, root, cached_only=True) == 0
        for uuid in items:
            folder = root / uuid
            assert libraries_complete(folder, expected_uuid=uuid)
            assert (folder / 'raw.json').read_bytes() == before[folder / 'raw.json']
            assert (folder / 'user.txt').read_bytes() == b'preserve user files'
        assert len(list(root.glob('*/*.kicad_sym'))) == 3
        assert len(list(root.glob('*/*.pretty/*.kicad_mod'))) == 2
        assert run_items(items, root) == 0  # Complete caches must be skipped offline.
    print(
        f'Installed euc2k {args.version}: metadata, commands, errors, paths, cache and bytes PASS'
    )


if __name__ == '__main__':
    main()
