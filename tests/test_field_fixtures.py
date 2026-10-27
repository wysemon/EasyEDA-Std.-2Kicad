"""Regression cases supplied after testing real components in KiCad."""

import json
from pathlib import Path

from easyeda2kicad_local.converter import convert_response

FIXTURES = Path(__file__).parent / 'fixtures'
HEADER = 'b156dd172f7646a6a0d70c948b98a414'


def load(uuid):
    return json.loads((FIXTURES / f'{uuid}.json').read_bytes())


def test_legacy_header_yes_plating():
    converted = convert_response(load(HEADER))
    assert len(converted.pads) == len(converted.pins) == 16
    assert all(p.kind == 'thru_hole' and p.drill > 0 for p in converted.pads)
