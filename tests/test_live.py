"""Opt-in single-component smoke test. Never selected by the default suite."""

import pytest

from easyeda2kicad_local.client import EasyEDAClient
from easyeda2kicad_local.converter import convert_response
from easyeda2kicad_local.workflow import read_response


@pytest.mark.live
def test_one_public_component_live():
    # One component only: no search or footprint fallback.
    uuid = '7db93ef938c54a728e02f6579db05977'
    with EasyEDAClient() as client:
        response = read_response(client.component(uuid), uuid)
    converted = convert_response(response)
    assert converted.pins and converted.pads
    assert {pin.number for pin in converted.pins} <= {pad.number for pad in converted.pads}
