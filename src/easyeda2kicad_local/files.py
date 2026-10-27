"""Per-file atomic replacement for cached source and generated artifacts."""

import os
import tempfile
from pathlib import Path

MAX_INPUT_BYTES = 16 * 1024 * 1024


def read_limited(path: Path):
    """Bound input allocation without changing cached bytes or trusting stat sizes."""
    with path.open('rb') as stream:
        content = stream.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise ValueError(f'input exceeds {MAX_INPUT_BYTES} byte limit: {path}')
    return content


def atomic_write(path: Path, content: str | bytes):
    """Replace one file via a flushed sibling; multi-file safety is publication's job."""
    data = content.encode('utf-8') if isinstance(content, str) else content
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp', delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # A sibling temporary file keeps replacement on the same filesystem.
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
