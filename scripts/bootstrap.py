"""Shared, stdlib-only setup refresh used before the package is installed."""

import hashlib
import subprocess
import sys
from pathlib import Path


def ensure_installed(root):
    """Refresh an editable install only when its dependency declaration changes."""
    marker = root / '.venv' / '.euc2k-ready'
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
            print(
                'Setup failed; check your internet connection and Python/pip installation, then retry.',
                file=sys.stderr,
            )
            return 1
        # A failed install leaves the old marker intact, so the next launch
        # retries setup rather than mistaking a partial install for readiness.
        marker.write_text(digest + '\n', encoding='ascii')
    except OSError as e:
        print(f'Setup failed: {e}; check checkout permissions and retry.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(ensure_installed(Path(__file__).resolve().parents[1]))
