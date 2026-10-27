"""Filesystem cache and conversion orchestration."""

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .client import UUID, EasyEDAClient, FetchError, StopRun
from .converter import document, safe_name, write_conversion
from .files import MAX_INPUT_BYTES, atomic_write, read_limited
from .publication import check_identity, recover
from .publication import libraries_complete as libraries_complete
from .validation import validate_libraries

log = logging.getLogger(__name__)


def read_response(raw, expected=None):
    """Validate the API envelope and requested identity without altering bytes."""
    if len(raw) > MAX_INPUT_BYTES:
        raise FetchError('component response exceeds supported size')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('success') is not True:
        raise FetchError('Component is unavailable/private or API returned success:false')
    result = data.get('result')
    if not isinstance(result, dict) or not result.get('dataStr'):
        raise FetchError('Component response is missing result/dataStr')
    if expected and result.get('uuid', '').lower() != expected.lower():
        raise FetchError('Response UUID does not match requested component')
    return data


def find_cache(root, uuid):
    """Find a component by stored UUID, independent of its title or folder name."""
    matches = []
    if root.exists():
        for raw in root.glob('*/raw.json'):
            try:
                data = json.loads(read_limited(raw))
                if data.get('result', {}).get('uuid', '').lower() == uuid:
                    matches.append(raw.parent)
            except (ValueError, AttributeError, OSError):
                log.warning('Unreadable cache: %s', raw)
    if len(matches) > 1:
        raise ValueError(f'Multiple cached folders for {uuid}; resolve ambiguity before converting')
    return matches[0] if matches else None


def append_log(root, uuid, status):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'fetch_log.tsv').open('a', encoding='utf-8') as stream:
        stream.write(f'{datetime.now(timezone.utc).isoformat()}\t{uuid}\t{status}\n')


def resolve_package(data, folder, client=None, *, force=False):
    """Prefer embedded footprint data; allow HTTP only with an explicit client.

    Passing ``None`` is the offline boundary used by cached conversion. Missing
    fallback data must fail there rather than silently reaching the network.
    """
    result = data['result']
    if result.get('packageDetail'):
        return result['packageDetail']
    puuid = document(result['dataStr'])['head'].get('puuid', '')
    if not UUID.fullmatch(puuid):
        raise ValueError('Missing packageDetail and valid head.puuid')
    cached = folder / 'package_raw.json'
    if cached.exists() and not force:
        return read_response(read_limited(cached), puuid)['result']
    if client is None:
        raise ValueError('Footprint fallback is not cached; run fetch --force to retrieve it')
    log.warning('Missing packageDetail; fetching footprint fallback %s', puuid)
    raw = client.component(puuid)
    response = read_response(raw, puuid)
    atomic_write(cached, raw)
    return response['result']


def run_items(
    items,
    root: Path,
    *,
    cached_only=False,
    force=False,
    dry_run=False,
    delay=4.0,
    validate=False,
    verbose=False,
):
    """Process a batch and return 0 on success, 1 if any component failed.

    Keep one client for cross-item pacing and denial detection. Dry runs may
    read existing output, but all their writes belong to disposable directories.
    """
    failures = succeeded = skipped = 0
    libraries = set()

    def remember(folder):
        for symbol in folder.glob('*.kicad_sym'):
            pretty = symbol.with_suffix('.pretty')
            if pretty.is_dir():
                libraries.add((symbol.resolve(), pretty.resolve()))

    def summary(unprocessed=0):
        print(f'Summary: {succeeded} succeeded, {failures} failed, {skipped} skipped.')
        print(f'Output: {root.resolve()}')
        if unprocessed:
            print(f'Not processed: {unprocessed} (run stopped).')
        if dry_run:
            print('Dry run: no output files were saved.')
        for symbol, pretty in sorted(libraries):
            print(f'add {symbol} in Symbol Libraries')
            print(f'add {pretty} in Footprint Libraries')

    def record_status(uuid, status):
        try:
            append_log(root, uuid, status)
        except Exception:
            log.warning(
                'Could not write fetch log; check output folder permissions.', exc_info=verbose
            )

    with EasyEDAClient(delay) as client:
        for index, uuid in enumerate(items):
            try:
                cached = find_cache(root, uuid)
                if cached_only and not cached:
                    raise ValueError('No raw.json cache found; fetch this component first')
                if cached and not dry_run:
                    check_identity(cached, uuid)
                    # Restore a previous complete snapshot before deciding
                    # whether an interrupted replacement can be skipped.
                    recover(cached)
                if (
                    cached
                    and libraries_complete(cached, expected_uuid=uuid)
                    and not cached_only
                    and not force
                    and not dry_run
                ):
                    if validate:
                        for symbol in cached.glob('*.kicad_sym'):
                            if not validate_libraries(cached, symbol.stem):
                                raise ValueError(
                                    'KiCad validation failed or unavailable; existing libraries were kept'
                                )
                    log.info('Skipping cached item %s', uuid)
                    record_status(uuid, 'skipped')
                    remember(cached)
                    skipped += 1
                    continue
                # Dry runs read existing raw bytes even with --force, and write only in a temp directory.
                using_cache = bool(cached and (cached_only or dry_run or not force))
                if using_cache:
                    log.info('re-converting from cache: %s', uuid)
                raw = read_limited(cached / 'raw.json') if using_cache else client.component(uuid)
                data = read_response(raw, uuid)
                title = data['result'].get('title') or uuid
                folder = cached or root / f'{safe_name(title)}_{uuid[:8]}'
                check_identity(folder, uuid, name=f'{safe_name(title)}_{uuid[:8]}')
                # New downloads remain available for an offline retry even if
                # conversion fails. Existing cache bytes change only on commit.
                if not dry_run and not (folder / 'raw.json').exists():
                    folder.mkdir(parents=True, exist_ok=True)
                    atomic_write(folder / 'raw.json', raw)
                with tempfile.TemporaryDirectory(prefix='easyeda2kicad-') as tmp:
                    target = Path(tmp)
                    sources = {'raw.json': raw}
                    if cached and (cached / 'package_raw.json').exists():
                        atomic_write(
                            target / 'package_raw.json', read_limited(cached / 'package_raw.json')
                        )
                    package = resolve_package(
                        data,
                        target,
                        None if using_cache else client,
                        force=force and not using_cache,
                    )
                    if (target / 'package_raw.json').exists():
                        sources['package_raw.json'] = (target / 'package_raw.json').read_bytes()
                        if not dry_run and not (folder / 'package_raw.json').exists():
                            atomic_write(folder / 'package_raw.json', sources['package_raw.json'])
                    converted = write_conversion(
                        data,
                        target if dry_run else folder,
                        package,
                        validate=validate,
                        sources=sources,
                    )
                if dry_run:
                    log.info(
                        'Dry run %s: %d pins, %d pads',
                        uuid,
                        len(converted.pins),
                        len(converted.pads),
                    )
                    succeeded += 1
                    continue
                remember(folder)
                log.info(
                    'Converted %s: %d pins, %d pads -> %s',
                    uuid,
                    len(converted.pins),
                    len(converted.pads),
                    folder,
                )
                record_status(uuid, 'converted' if cached_only else 'ok')
                succeeded += 1
            except StopRun as e:
                log.error('%s', e, exc_info=verbose)
                if not dry_run:
                    record_status(uuid, 'stopped')
                failures += 1
                summary(len(items) - index - 1)
                return 1
            except Exception as e:
                failures += 1
                log.error('%s: %s', uuid, str(e).replace('\n', ' '), exc_info=verbose)
                if not dry_run:
                    record_status(uuid, 'error')
    summary()
    return int(failures > 0)
