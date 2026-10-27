"""Filesystem cache and conversion orchestration."""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile

from .client import EasyEDAClient, FetchError, StopRun, UUID
from .converter import document, safe_name, write_conversion
from .validation import validate_libraries
from .models import parse_svgnode
from .files import atomic_write

log = logging.getLogger(__name__)


def read_response(raw, expected=None):
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
    matches = []
    if root.exists():
        for raw in root.glob('*/raw.json'):
            try:
                data = json.loads(raw.read_bytes())
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
    result = data['result']
    if result.get('packageDetail'):
        return result['packageDetail']
    puuid = document(result['dataStr'])['head'].get('puuid', '')
    if not UUID.fullmatch(puuid):
        raise ValueError('Missing packageDetail and valid head.puuid')
    cached = folder / 'package_raw.json'
    if cached.exists() and not force:
        return read_response(cached.read_bytes(), puuid)['result']
    if client is None:
        raise ValueError('Footprint fallback is not cached; run fetch --force to retrieve it')
    log.warning('Missing packageDetail; fetching footprint fallback %s', puuid)
    raw = client.component(puuid)
    response = read_response(raw, puuid)
    atomic_write(cached, raw)
    return response['result']


def experimental_model(package, folder, name, client):
    data = document(package['dataStr'])
    uuid = data['head'].get('uuid_3d') or ''
    for shape in data.get('shape', []):
        if shape.startswith('SVGNODE~'):
            try:
                model = parse_svgnode(shape)
                uuid = model.uuid
                log.debug('Source model placement (unverified): %s', model)
            except (ValueError, KeyError, TypeError, AttributeError):
                log.warning('Unrecognized experimental SVGNODE: %s', shape)
    if not uuid:
        log.warning('No 3D model reference; continuing without a model')
        return
    if not UUID.fullmatch(uuid):
        log.warning('Invalid or unsupported 3D model UUID; continuing without a model')
        return
    try:
        raw = client.request(f'https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}')
        if not raw.lstrip().startswith(b'ISO-10303-21;'):
            raise FetchError('Model endpoint did not return a STEP file')
        atomic_write(folder / f'{name}.step', raw)
        log.warning('Experimental STEP downloaded, but not attached: placement/rotation requires a model-bearing sample. '
                    'Add it manually in KiCad until transforms are verified.')
    except StopRun:
        raise
    except FetchError as e:
        log.warning('3D model download failed; continuing without it: %s', e)


def libraries_complete(folder):
    return (any(p.is_file() for p in folder.glob('*.kicad_sym')) and
            any(p.is_file() for p in folder.glob('*.pretty/*.kicad_mod')))


def run_items(items, root: Path, *, cached_only=False, force=False, dry_run=False,
              delay=4., with_3d=False, validate=False, verbose=False):
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

    def error_status(uuid, status):
        try:
            append_log(root, uuid, status)
        except Exception:
            log.error('Could not write fetch log; check output folder permissions.', exc_info=verbose)

    with EasyEDAClient(delay) as client:
        for index, uuid in enumerate(items):
            try:
                cached = find_cache(root, uuid)
                if cached_only and not cached:
                    raise ValueError('No raw.json cache found; fetch this component first')
                if cached and libraries_complete(cached) and not cached_only and not force and not dry_run:
                    log.info('Skipping cached item %s', uuid)
                    append_log(root, uuid, 'skipped')
                    remember(cached)
                    skipped += 1
                    continue
                # Dry runs read existing raw bytes even with --force, and write only in a temp directory.
                using_cache = bool(cached and (cached_only or dry_run or not force))
                if using_cache:
                    log.info('re-converting from cache: %s', uuid)
                raw = ((cached / 'raw.json').read_bytes() if using_cache else client.component(uuid))
                data = read_response(raw, uuid)
                title = data['result'].get('title') or uuid
                folder = cached or root / f'{safe_name(title)}_{uuid[:8]}'
                if folder.exists() and libraries_complete(folder) and not cached and not force and not dry_run:
                    log.info('Skipping existing folder %s', folder)
                    append_log(root, uuid, 'skipped')
                    remember(folder)
                    skipped += 1
                    continue
                if dry_run:
                    with tempfile.TemporaryDirectory(prefix='easyeda2kicad-') as tmp:
                        target = Path(tmp)
                        atomic_write(target / 'raw.json', raw)
                        if cached and (cached / 'package_raw.json').exists():
                            atomic_write(target / 'package_raw.json', (cached / 'package_raw.json').read_bytes())
                        package = resolve_package(data, target, None if cached or cached_only else client)
                        converted = write_conversion(data, target, package)
                        log.info('Dry run %s: %d pins, %d pads', uuid, len(converted.pins), len(converted.pads))
                        if validate and not validate_libraries(target, converted.name):
                            raise ValueError('KiCad validation failed; rerun with --verbose for details')
                        if with_3d:
                            log.warning('Dry run: 3D downloads are not performed')
                        succeeded += 1
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                if not using_cache:
                    atomic_write(folder / 'raw.json', raw)
                package = resolve_package(data, folder, None if using_cache else client, force=force and not using_cache)
                converted = write_conversion(data, folder, package)
                remember(folder)
                if validate and not validate_libraries(folder, converted.name):
                    raise ValueError('KiCad validation failed; check the libraries or rerun with --verbose')
                if with_3d:
                    if using_cache:
                        log.warning('Cached conversion does not download models; use fetch --force --3d')
                    else:
                        experimental_model(package, folder, converted.name, client)
                log.info('Converted %s: %d pins, %d pads -> %s', uuid, len(converted.pins), len(converted.pads), folder)
                append_log(root, uuid, 'converted' if cached_only else 'ok')
                succeeded += 1
            except StopRun as e:
                log.error('%s', e, exc_info=verbose)
                if not dry_run:
                    error_status(uuid, 'stopped')
                failures += 1
                summary(len(items) - index - 1)
                return 1
            except Exception as e:
                failures += 1
                log.error('%s: %s', uuid, str(e).replace('\n', ' '), exc_info=verbose)
                if not dry_run:
                    error_status(uuid, 'error')
    summary()
    return int(failures > 0)
