"""Stage-and-publish bookkeeping with rollback and next-run crash recovery."""

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
from pathlib import Path

from .files import atomic_write
from .sexpr import children, contains, descendants, loads

log = logging.getLogger(__name__)
COMPLETE = '.ee2kicad-complete.json'
PENDING = '.ee2kicad-pending.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(folder, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p in ('.', '..') for p in path.parts):
        raise ValueError('unsafe conversion manifest path')
    # Manifests are local data, not permission to follow user-created links.
    target = folder / path
    if any(p.is_symlink() for p in [folder, target, *target.parents] if p != folder.parent):
        raise ValueError(f'refusing symlink in output path: {target}')
    return target


def footprint_has_model(path):
    return contains(loads(path.read_text(encoding='utf-8')), 'model')


def source_counts(folder):
    raw = folder / 'raw.json'
    if not raw.exists():
        return None
    result = json.loads(raw.read_bytes())['result']
    symbol = result['dataStr']
    symbol = json.loads(symbol) if isinstance(symbol, str) else symbol
    if symbol.get('subparts'):
        raise ValueError('multi-unit cache is incomplete')
    package = result.get('packageDetail')
    if not package:
        package = json.loads((folder / 'package_raw.json').read_bytes())['result']
    footprint = package['dataStr']
    footprint = json.loads(footprint) if isinstance(footprint, str) else footprint
    pins = sum(raw.split('~', 1)[0] == 'P' for raw in symbol['shape'])
    pads = sum(raw.split('~', 1)[0] in ('PAD', 'VIA', 'HOLE') for raw in footprint['shape'])
    if not pins or not any(raw.startswith('PAD~') for raw in footprint['shape']):
        raise ValueError('no source pins or pads')
    return pins, pads


def valid_library(path, symbol=False, expected=None):
    tree = loads(path.read_text(encoding='utf-8'))

    def numeric(node, kind, counts):
        fields = children(node, kind)
        if len(fields) != 1:
            raise ValueError(f'missing/duplicate {kind}')
        values = list(map(float, fields[0][1:]))
        if len(values) not in counts or not all(math.isfinite(v) for v in values):
            raise ValueError(f'invalid {kind}')
        return values

    if symbol:
        pins = list(descendants(tree, 'pin'))
        if expected is not None and len(pins) != expected:
            return False
        for pin in pins:
            numeric(pin, 'at', (3,))
            if numeric(pin, 'length', (1,))[0] <= 0 or not children(pin, 'number')[0][1]:
                return False
        return tree[0] == 'kicad_symbol_lib' and bool(pins)
    pads = children(tree, 'pad')
    if expected is not None and len(pads) != expected:
        return False
    for pad in pads:
        numeric(pad, 'at', (2, 3))
        if min(numeric(pad, 'size', (2,))) <= 0 or not children(pad, 'layers'):
            return False
        if pad[2] in ('thru_hole', 'np_thru_hole'):
            drill = children(pad, 'drill')[0][1:]
            if drill[0] == 'oval':
                drill = drill[1:]
            if not drill or not all(math.isfinite(float(d)) and float(d) > 0 for d in drill):
                return False
    return tree[0] in ('footprint', 'module') and bool(pads) and not contains(tree, 'model')


def libraries_complete(folder):
    """Check committed hashes; accept structurally usable pre-manifest 2D output."""
    if (folder / PENDING).exists():
        return False
    try:
        counts = source_counts(folder)
        manifest = folder / COMPLETE
        if manifest.exists():
            data = json.loads(manifest.read_bytes())
            if data['version'] != 1 or not isinstance(data['files'], dict):
                return False
            paths = [local_path(folder, name) for name in data['files']]
            if not all(
                p.is_file() and digest(p) == data['files'][p.relative_to(folder).as_posix()]
                for p in paths
            ):
                return False
            symbols = [p for p in paths if p.suffix == '.kicad_sym']
            footprints = [p for p in paths if p.suffix == '.kicad_mod']
        else:
            symbols = list(folder.glob('*.kicad_sym'))
            footprints = list(folder.glob('*.pretty/*.kicad_mod'))
            if any(not s.with_suffix('.pretty').is_dir() for s in symbols):
                return False
        return (
            bool(symbols and footprints)
            and all(valid_library(p, True, counts[0] if counts else None) for p in symbols)
            and all(valid_library(p, False, counts[1] if counts else None) for p in footprints)
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return False


def recover(folder):
    """Roll an interrupted publication back before considering its cache complete."""
    journal = folder / PENDING
    if not journal.exists():
        return
    data = json.loads(journal.read_bytes())
    backup_name = data['backup']
    if (
        data['version'] != 1
        or not backup_name.startswith('.ee2kicad-backup-')
        or Path(backup_name).name != backup_name
    ):
        raise ValueError('invalid recovery journal; preserve this folder and inspect it manually')
    backup = local_path(folder, backup_name)
    for entry in data['paths']:
        target = local_path(folder, entry['path'])
        saved = local_path(backup, entry['path'])
        if entry['existed']:
            atomic_write(target, saved.read_bytes())
        else:
            target.unlink(missing_ok=True)
            if target.parent != folder:
                try:
                    target.parent.rmdir()
                except OSError:
                    pass  # Never remove a nonempty directory or unrelated user file.
    journal.unlink()
    shutil.rmtree(backup)
    stage_name = data.get('stage', '')
    if stage_name.startswith('.ee2kicad-stage-') and Path(stage_name).name == stage_name:
        stage = local_path(folder.parent, stage_name)
        if stage.exists():
            shutil.rmtree(stage)
    log.warning('Recovered interrupted conversion in %s; previous files restored.', folder)


def publish(stage, folder, paths):
    """Publish staged files, replacing completion metadata last; preserve other files."""
    folder.mkdir(parents=True, exist_ok=True)
    recover(folder)
    paths = [*paths, COMPLETE]
    backup = Path(tempfile.mkdtemp(prefix='.ee2kicad-backup-', dir=folder))
    entries = []
    try:
        for relative in paths:
            target = local_path(folder, relative)
            if target.exists() and not target.is_file():
                raise ValueError(f'output path is not a file: {target}')
            entries.append({'path': relative, 'existed': target.exists()})
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(saved, target.read_bytes())
        atomic_write(
            folder / PENDING,
            json.dumps(
                {'version': 1, 'backup': backup.name, 'stage': stage.name, 'paths': entries}
            ),
        )
        for relative in paths:
            target = local_path(folder, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / relative, target)
        (folder / PENDING).unlink()
    except BaseException:
        if (folder / PENDING).exists():
            recover(folder)
        raise
    finally:
        # If rollback itself failed, retain its journal and backup for the next run.
        if not (folder / PENDING).exists():
            shutil.rmtree(backup, ignore_errors=True)


def write_manifest(stage, paths, uuid):
    atomic_write(
        stage / COMPLETE,
        json.dumps(
            {'version': 1, 'uuid': uuid, 'files': {path: digest(stage / path) for path in paths}},
            sort_keys=True,
        )
        + '\n',
    )
