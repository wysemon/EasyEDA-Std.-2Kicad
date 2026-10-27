"""Conversion orchestration and compatibility exports for the original API."""
import logging
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .client import UUID
from .credits import owner as owner
from .credits import render_credits
from .files import atomic_write
from .footprint import LAYERS as LAYERS
from .footprint import Pad as Pad
from .footprint import footprint_graphic as footprint_graphic
from .footprint import layer as layer
from .footprint import parse_pad as parse_pad
from .footprint import render_footprint
from .publication import digest, footprint_has_model, local_path, publish, recover, write_manifest
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


@dataclass
class Conversion:
    name: str
    pins: list
    pads: list
    symbol: str
    footprint: str
    credits: str



def convert_response(response, package=None, *, library_name=None):
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
    name = library_name or safe_name(result.get('title') or result['uuid']) + '_' + result['uuid'][:8]
    sc, fc = Coordinates(data, True), Coordinates(fp)
    pins, pads, sg, fg = [], [], [], []
    for raw in fp.get('shape', []):
        fields = raw.split('~')
        kind = fields[0]
        layer_index = {'TRACK': 2, 'ARC': 2, 'SOLIDREGION': 1, 'RECT': 5, 'CIRCLE': 5}.get(kind)
        copper = layer_index is not None and len(fields) > layer_index and fields[layer_index] in ('1', '2', '11')
        try:
            if kind == 'PAD':
                pads.append(parse_pad(raw, fc))
            else:
                fg.extend(footprint_graphic(raw, fc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            if kind in ('PAD', 'VIA', 'HOLE') or copper:
                raise ValueError(f'{result["uuid"]}: invalid essential footprint {kind}: {e}; no new libraries published') from e
            log.warning('%s: skipping optional footprint element (%s): %s', result['uuid'], e, raw)
    for raw in data.get('shape', []):
        kind = raw.split('~', 1)[0]
        try:
            if kind == 'P':
                pins.append(parse_pin(raw, sc))
            else:
                sg.extend(symbol_graphic(raw, sc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            if kind == 'P':
                raise ValueError(f'{result["uuid"]}: invalid essential symbol pin: {e}; no new libraries published') from e
            log.warning('%s: skipping optional symbol element (%s): %s', result['uuid'], e, raw)
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
    """Build and validate privately; publish only a complete set, with rollback."""
    converted = convert_response(response, package)
    folder.parent.mkdir(parents=True, exist_ok=True)
    recover(folder)
    with tempfile.TemporaryDirectory(prefix='.ee2kicad-stage-', dir=folder.parent) as temporary:
        stage = Path(temporary)
        artifacts = {f'{converted.name}.kicad_sym': converted.symbol,
                     f'{converted.name}.pretty/{converted.name}.kicad_mod': converted.footprint,
                     'CREDITS.txt': converted.credits, **(sources or {})}
        # Regenerate converter-owned pre-UUID names as well, so registered old
        # libraries lose their model references without deleting any user files.
        for old in folder.glob('*.pretty/*.kicad_mod'):
            try:
                tree = loads(old.read_text(encoding='utf-8'))
            except ValueError:
                continue  # A damaged current file can still be replaced safely.
            if (children(tree, 'generator') == [['generator', 'easyeda2kicad-local']]
                    and footprint_has_model(old) and old.stem != converted.name):
                if tree[1] != old.stem or safe_name(old.stem) != old.stem:
                    raise ValueError(f'Cannot safely migrate legacy footprint {old}; move it aside first')
                alias = convert_response(response, package, library_name=old.stem)
                artifacts[old.relative_to(folder).as_posix()] = alias.footprint
                old_symbol = folder / f'{old.stem}.kicad_sym'
                if old_symbol.exists():
                    artifacts[old_symbol.name] = alias.symbol
                log.warning('Migrating legacy 3D-era library %s to 2D; existing model files are kept.', old.stem)
        credits = folder / 'CREDITS.txt'
        if credits.is_file() and credits.read_bytes() != converted.credits.encode('utf-8'):
            saved = f'CREDITS.previous-{digest(credits)[:12]}.txt'
            artifacts[saved] = credits.read_bytes()
            log.warning('Previous attribution preserved in %s.', saved)
        # Preserve edited generated files too. They may contain deliberate user
        # changes, even though their generator still identifies this converter.
        previous_manifest = folder / '.ee2kicad-complete.json'
        if previous_manifest.exists():
            import json
            try:
                previous = json.loads(previous_manifest.read_bytes())['files']
            except (ValueError, KeyError, TypeError):
                previous = {}
            for relative in list(artifacts):
                target = local_path(folder, relative)
                if (target.suffix in ('.kicad_sym', '.kicad_mod') and target.is_file()
                        and relative in previous and digest(target) != previous[relative]):
                    saved = relative + f'.previous-{digest(target)[:12]}'
                    artifacts[saved] = target.read_bytes()
                    log.warning('Modified library preserved in %s before rebuilding.', saved)
        for relative, content in artifacts.items():
            target = local_path(folder, relative)
            if target.exists() and target.suffix in ('.kicad_sym', '.kicad_mod'):
                text = target.read_text(encoding='utf-8')
                if '(generator "easyeda2kicad-local")' not in text and '(generator easyeda2kicad-local)' not in text:
                    raise ValueError(f'Refusing to overwrite an unrelated library: {target}; move it aside first')
            path = local_path(stage, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, content)
        if validate:
            for symbol in stage.glob('*.kicad_sym'):
                if not validate_libraries(stage, symbol.stem):
                    raise ValueError('KiCad validation failed or unavailable; previous libraries were kept. Check KiCad or use --verbose.')
        paths = list(artifacts)
        write_manifest(stage, paths, response['result']['uuid'])
        publish(stage, folder, paths)
    return converted
