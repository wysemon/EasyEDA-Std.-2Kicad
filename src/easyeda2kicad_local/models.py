"""Read EasyEDA's model reference; placement remains intentionally unverified."""
from dataclasses import dataclass
import json

from .converter import num
from .client import UUID


@dataclass(frozen=True)
class ModelReference:
    uuid: str
    origin: tuple[float, float]
    rotation: tuple[float, float, float]
    z: float
    width: float
    height: float


def parse_svgnode(raw):
    if not raw.startswith('SVGNODE~'):
        raise ValueError('not an SVGNODE')
    attrs = json.loads(raw.split('~', 1)[1])['attrs']
    uuid = attrs['uuid']
    if not UUID.fullmatch(uuid):
        raise ValueError('invalid model UUID')
    origin = tuple(num(v) for v in attrs['c_origin'].split(','))
    rotation = tuple(num(v) for v in attrs['c_rotation'].split(','))
    if len(origin) != 2 or len(rotation) != 3:
        raise ValueError('invalid model origin or rotation')
    return ModelReference(uuid, origin, rotation, num(attrs['z']),
                          num(attrs['c_width']), num(attrs['c_height']))
