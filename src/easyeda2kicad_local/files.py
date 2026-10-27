"""Per-file atomic replacement for cached source and generated artifacts."""

import os
import tempfile
from pathlib import Path


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
