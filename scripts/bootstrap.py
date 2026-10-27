"""Shared, stdlib-only setup refresh used before the package is installed."""
import hashlib
from pathlib import Path
import subprocess
import sys


def ensure_installed(root):
    marker = root / '.venv' / '.ee2kicad-ready'
    try:
        digest = hashlib.sha256((root / 'pyproject.toml').read_bytes()).hexdigest()
        try:
            installed = marker.read_text(encoding='ascii').strip()
        except (OSError, UnicodeError):
            installed = ''
        if installed == digest:
            return 0
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-e', str(root)], cwd=root)
        if result.returncode:
            print('Setup failed; check your internet connection and Python/pip installation, then retry.', file=sys.stderr)
            return 1
        marker.write_text(digest + '\n', encoding='ascii')
    except OSError as e:
        print(f'Setup failed: {e}; check checkout permissions and retry.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(ensure_installed(Path(__file__).resolve().parents[1]))
