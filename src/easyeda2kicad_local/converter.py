"""Conversion orchestration and compatibility exports for the original API."""

import json
import logging
import math
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .client import UUID

# Explicit aliases retain the original converter module's importable helpers.
# Implementations live in focused modules; callers need not change imports.
from .credits import owner as owner
from .credits import render_credits
from .files import atomic_write, read_limited
from .footprint import LAYERS as LAYERS
from .footprint import Pad as Pad
from .footprint import footprint_graphic as footprint_graphic
from .footprint import layer as layer
from .footprint import parse_pad as parse_pad
from .footprint import render_footprint
from .publication import (
    check_identity,
    digest,
    footprint_has_model,
    libraries_complete,
    local_path,
    publish,
    recover,
    write_manifest,
)
from .sexpr import children, loads
from .shared import UNIT as UNIT
from .shared import Coordinates as Coordinates
from .shared import document as document
from .shared import effects as effects
from .shared import f as f
from .shared import fill as fill
from .shared import num as num
from .shared import poly as poly
from .shared import prefix as prefix
from .shared import q as q
from .shared import safe_name as safe_name
from .shared import short_description as short_description
from .shared import stroke as stroke
from .shared import svg_graphics as svg_graphics
from .symbol import SYMBOL_TEXT_SIZE_CAP as SYMBOL_TEXT_SIZE_CAP
from .symbol import Pin as Pin
from .symbol import parse_pin as parse_pin
from .symbol import render_symbol
from .symbol import symbol_graphic as symbol_graphic
from .symbol import symbol_label_position as symbol_label_position
from .symbol import symbol_text_angle as symbol_text_angle
from .symbol import unit_one as unit_one
from .validation import validate_libraries

log = logging.getLogger(__name__)
# Inner copper is recognized as electrical even where its export is unsupported:
# an unmapped copper record must fail instead of disappearing as decoration.
COPPER_LAYERS = {'1', '2', '11', *(str(i) for i in range(21, 53))}
MAX_PRIMITIVES = 100_000


@dataclass
class Conversion:
    """A complete in-memory conversion, with KiCad geometry expressed in mm."""

    name: str
    pins: list[Pin]
    pads: list[Pad]
    symbol: str
    footprint: str
    credits: str


def convert_response(response, package=None, *, library_name=None):
    """Render validated source data without network or filesystem operations.

    ``library_name`` is used to regenerate verified legacy library aliases;
    normal exports use the sanitized title and UUID suffix. Essential record
    errors abort the component; optional drawing errors remain visible warnings.
    """
    if response.get('success') is not True:
        raise ValueError('API response did not succeed')
    result = response['result']
    if not isinstance(result.get('uuid'), str) or not UUID.fullmatch(result['uuid']):
        raise ValueError('invalid component UUID in source response')
    data = unit_one(document(result['dataStr']))
    package = package or result.get('packageDetail')
    if not package:
        raise ValueError('missing footprint; fetch packageDetail or cache package_raw.json')
    fp = document(package['dataStr'])
    name = (
        library_name or safe_name(result.get('title') or result['uuid']) + '_' + result['uuid'][:8]
    )
    sc, fc = Coordinates(data, True), Coordinates(fp)
    pins, pads, sg, fg = [], [], [], []
    mechanical_skipped = 0
    essential_errors = []
    for raw in fp.get('shape', []):
        fields = raw.split('~')
        kind = fields[0]
        layer_index = {
            'TRACK': 2,
            'ARC': 2,
            'SOLIDREGION': 1,
            'RECT': 5,
            'CIRCLE': 5,
            'TEXT': 7,
        }.get(kind)
        # Mechanical drawings remain unsupported; summarize their omissions
        # without hiding failures in electrical records such as PAD/VIA/HOLE.
        if layer_index is not None and len(fields) > layer_index and fields[layer_index] == '15':
            mechanical_skipped += 1
            continue
        copper = (
            layer_index is not None
            and len(fields) > layer_index
            and fields[layer_index] in COPPER_LAYERS
        )
        try:
            if kind in ('PAD', 'VIA', 'HOLE'):
                indices = (2, 3) if kind == 'PAD' else (1, 2)
                if not all(math.isfinite(float(fields[i])) for i in indices):
                    raise ValueError('electrical coordinates must be explicit and finite')
            if copper and kind in ('TRACK', 'ARC', 'CIRCLE', 'TEXT'):
                index = 4 if kind in ('CIRCLE', 'TEXT') else 1
                width = float(fields[index]) * UNIT
                if not math.isfinite(width) or round(width, 6) <= 0:
                    raise ValueError('copper stroke width must be explicit and positive')
            if kind == 'TEXT' and copper:
                # Decoration defaults must not invent the size of copper lettering.
                if any(fields[i] in ('', 'undefined') for i in (2, 3, 4, 5, 6, 9)):
                    raise ValueError('missing copper text geometry')
                if fields[6] not in ('0', '1'):
                    raise ValueError('unsupported copper text mirror flag')
            if kind == 'PAD':
                pads.append(parse_pad(raw, fc))
            else:
                graphics = footprint_graphic(raw, fc)
                if copper and not graphics:
                    raise ValueError('empty copper geometry')
                fg.extend(graphics)
        except (ValueError, IndexError, KeyError, TypeError) as e:
            if kind in ('PAD', 'VIA', 'HOLE') or copper:
                essential_errors.append(f'invalid essential footprint {kind}: {e}; raw: {raw}')
            else:
                log.warning(
                    '%s: skipping optional footprint element (%s): %s', result['uuid'], e, raw
                )
        if len(fg) > MAX_PRIMITIVES:
            raise ValueError('footprint exceeds supported primitive count')
    if mechanical_skipped:
        log.warning('%s: %d elements on layer 15 skipped', result['uuid'], mechanical_skipped)
    if essential_errors:
        raise ValueError(
            f'{result["uuid"]}: ' + '; '.join(essential_errors) + '; no new libraries published'
        )
    for raw in data.get('shape', []):
        kind = raw.split('~', 1)[0]
        try:
            if kind == 'P':
                pins.append(parse_pin(raw, sc))
            else:
                sg.extend(symbol_graphic(raw, sc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            if kind == 'P':
                raise ValueError(
                    f'{result["uuid"]}: invalid essential symbol pin: {e}; no new libraries published'
                ) from e
            log.warning('%s: skipping optional symbol element (%s): %s', result['uuid'], e, raw)
        if len(sg) > MAX_PRIMITIVES:
            raise ValueError('symbol exceeds supported primitive count')
    for number, count in Counter(p.number for p in pins).items():
        if count > 1:
            log.warning('Duplicate symbol pin number %s (%s records retained)', number, count)
    missing = {p.number for p in pins} - {p.number for p in pads}
    if missing:
        log.warning('Symbol pin numbers missing from footprint: %s', ', '.join(sorted(missing)))
    if not pins or not pads:
        raise ValueError('no usable pins or pads; refusing empty library')
    footprint = render_footprint(name, fp, fc, pads, fg)
    symbol = render_symbol(result, data, name, sc, sg, pins)
    credits = render_credits(result, data, fp, package, name)
    return Conversion(name, pins, pads, symbol, footprint, credits)


def write_conversion(response, folder: Path, package=None, *, validate=False, sources=None):
    """Stage a complete set, optionally validate with KiCad, then publish it.

    ``sources`` carries untouched response bytes into the same publication.
    Structural checks always run; ``validate`` additionally requires native
    KiCad acceptance. Pre-publication failures leave old output untouched;
    publication failures use the journal and backups for rollback.
    """
    converted = convert_response(response, package)
    check_identity(folder, response['result']['uuid'], name=converted.name)
    folder.parent.mkdir(parents=True, exist_ok=True)
    recover(folder)
    with tempfile.TemporaryDirectory(prefix='.ee2kicad-stage-', dir=folder.parent) as temporary:
        stage = Path(temporary)
        artifacts = {
            f'{converted.name}.kicad_sym': converted.symbol,
            f'{converted.name}.pretty/{converted.name}.kicad_mod': converted.footprint,
            'CREDITS.txt': converted.credits,
            **(sources or {}),
        }
        # Regenerate converter-owned pre-UUID names as well, so registered old
        # libraries lose their model references without deleting any user files.
        for old in folder.glob('*.pretty/*.kicad_mod'):
            try:
                tree = loads(read_limited(old).decode('utf-8'))
            except ValueError:
                continue  # A damaged current file can still be replaced safely.
            if (
                children(tree, 'generator') == [['generator', 'easyeda2kicad-local']]
                and footprint_has_model(old)
                and old.stem != converted.name
            ):
                old_symbol = folder / f'{old.stem}.kicad_sym'
                source_uuids = []
                if old_symbol.exists():
                    old_tree = loads(read_limited(old_symbol).decode('utf-8'))
                    source_uuids = [
                        p[2]
                        for symbol in children(old_tree, 'symbol')
                        for p in children(symbol, 'property')
                        if p[1] == 'EasyEDA UUID'
                    ]
                if source_uuids != [response['result']['uuid']]:
                    log.warning(
                        'Leaving unassociated legacy library %s untouched; inspect/remove its model reference manually.',
                        old,
                    )
                    continue
                if tree[1] != old.stem or safe_name(old.stem) != old.stem:
                    raise ValueError(
                        f'Cannot safely migrate legacy footprint {old}; move it aside first'
                    )
                alias = convert_response(response, package, library_name=old.stem)
                artifacts[old.relative_to(folder).as_posix()] = alias.footprint
                if old_symbol.exists():
                    artifacts[old_symbol.name] = alias.symbol
                log.warning(
                    'Migrating legacy 3D-era library %s to 2D; existing model files are kept.',
                    old.stem,
                )
        credits = folder / 'CREDITS.txt'
        if credits.is_file() and read_limited(credits) != converted.credits.encode('utf-8'):
            saved = f'CREDITS.previous-{digest(credits)[:12]}.txt'
            artifacts[saved] = read_limited(credits)
            log.warning('Previous attribution preserved in %s.', saved)
        # Preserve edited generated files too. They may contain deliberate user
        # changes, even though their generator still identifies this converter.
        previous_manifest = folder / '.ee2kicad-complete.json'
        previous = {}
        if previous_manifest.exists():
            try:
                metadata = json.loads(read_limited(previous_manifest))
                if metadata['version'] == 1 and metadata['uuid'] == response['result']['uuid']:
                    previous = metadata['files']
                    if not isinstance(previous, dict):
                        previous = {}
            except (ValueError, KeyError, TypeError):
                previous = {}
        for relative, content in list(artifacts.items()):
            target = local_path(folder, relative)
            encoded = content.encode('utf-8') if isinstance(content, str) else content
            if (
                target.suffix in ('.kicad_sym', '.kicad_mod')
                and target.is_file()
                and read_limited(target) != encoded
                and (relative not in previous or digest(target) != previous[relative])
            ):
                saved = relative + f'.previous-{digest(target)[:12]}'
                artifacts[saved] = read_limited(target)
                log.warning('Modified or legacy library preserved in %s before rebuilding.', saved)
        for relative, content in artifacts.items():
            target = local_path(folder, relative)
            if (
                target.exists()
                and target.suffix in ('.kicad_sym', '.kicad_mod')
                and relative not in previous
            ):
                try:
                    text = read_limited(target).decode('utf-8')
                except UnicodeError as e:
                    raise ValueError(
                        f'Cannot confirm ownership of unreadable library: {target}; move it aside first'
                    ) from e
                if (
                    '(generator "easyeda2kicad-local")' not in text
                    and '(generator easyeda2kicad-local)' not in text
                ):
                    raise ValueError(
                        f'Refusing to overwrite an unrelated library: {target}; move it aside first'
                    )
            path = local_path(stage, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, content)
        if not libraries_complete(stage, expected_uuid=response['result']['uuid']):
            raise ValueError(
                'Generated library structure is incomplete; previous libraries were kept'
            )
        if validate:
            for symbol in stage.glob('*.kicad_sym'):
                if not validate_libraries(stage, symbol.stem):
                    raise ValueError(
                        'KiCad validation failed or unavailable; previous libraries were kept. Check KiCad or use --verbose.'
                    )
        paths = list(artifacts)
        write_manifest(stage, paths, response['result']['uuid'])
        publish(stage, folder, paths)
    return converted
