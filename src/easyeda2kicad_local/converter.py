"""Conversion orchestration and compatibility exports for the original API."""
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .credits import owner as owner
from .credits import render_credits
from .files import atomic_write
from .footprint import LAYERS as LAYERS
from .footprint import Pad as Pad
from .footprint import footprint_graphic as footprint_graphic
from .footprint import layer as layer
from .footprint import parse_pad as parse_pad
from .footprint import render_footprint
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

log = logging.getLogger(__name__)


@dataclass
class Conversion:
    name: str
    pins: list
    pads: list
    symbol: str
    footprint: str
    credits: str



def convert_response(response, package=None):
    if response.get('success') is not True:
        raise ValueError('API response did not succeed')
    result = response['result']
    data = unit_one(document(result['dataStr']))
    package = package or result.get('packageDetail')
    if not package:
        raise ValueError('missing footprint; fetch packageDetail or cache package_raw.json')
    fp = document(package['dataStr'])
    name = safe_name(result.get('title') or result['uuid']) + '_' + result['uuid'][:8]
    sc, fc = Coordinates(data, True), Coordinates(fp)
    pins, pads, sg, fg = [], [], [], []
    for raw in fp.get('shape', []):
        try:
            if raw.startswith('PAD~'):
                pads.append(parse_pad(raw, fc))
            else:
                fg.extend(footprint_graphic(raw, fc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            log.warning('Skipping footprint element (%s): %s', e, raw)
    for raw in data.get('shape', []):
        try:
            if raw.startswith('P~'):
                pins.append(parse_pin(raw, sc))
            else:
                sg.extend(symbol_graphic(raw, sc))
        except (ValueError, IndexError, KeyError, TypeError) as e:
            log.warning('Skipping symbol element (%s): %s', e, raw)
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


def write_conversion(response, folder: Path, package=None):
    converted = convert_response(response, package)
    folder.mkdir(parents=True, exist_ok=True)
    pretty = folder / f'{converted.name}.pretty'
    pretty.mkdir(exist_ok=True)
    atomic_write(pretty / f'{converted.name}.kicad_mod', converted.footprint)
    atomic_write(folder / f'{converted.name}.kicad_sym', converted.symbol)
    atomic_write(folder / 'CREDITS.txt', converted.credits)
    return converted
