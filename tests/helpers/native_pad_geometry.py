"""Measure source and generated pads using KiCad's independent importers."""

import json
import os
import re
import sys
from pathlib import Path


def main():
    source, pretty = map(Path, sys.argv[1:])
    for key in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
        location = source.parent / key.lower()
        location.mkdir(exist_ok=True)
        os.environ[key] = str(location)
    import pcbnew

    major = int(re.search(r'\d+', pcbnew.GetBuildVersion())[0])

    def point(v):
        return [pcbnew.ToMM(v.x), pcbnew.ToMM(v.y)]

    def measure(fp):
        result = []
        for pad in fp.Pads():
            # KiCad 9 added the layer argument; KiCad 8's optional argument
            # instead selects polygon approximation error, not a copper layer.
            polygon = (
                pad.GetEffectivePolygon(pad.GetLayer()) if major >= 9 else pad.GetEffectivePolygon()
            )
            outline = polygon.COutline(0)
            points = [point(outline.CPoint(i)) for i in range(outline.PointCount())]
            drill_box = None
            if pad.HasHole():
                hole = pad.GetEffectiveHoleShape()
                box = hole.BBox()
                drill_box = point(box.GetSize())
            result.append(
                {
                    'number': pad.GetNumber(),
                    'attribute': int(pad.GetAttribute()),
                    'at': point(pad.GetPosition()),
                    'angle': pad.GetOrientationDegrees(),
                    'size': point(pad.GetSize()),
                    'drill': point(pad.GetDrillSize()),
                    'hole_bounds': drill_box,
                    'layers': list(pad.GetLayerSet().Seq()),
                    'outline': points,
                }
            )
        return result

    # KiCad 10 renamed the factory; keep the same independent native loaders.
    factory = pcbnew.PCB_IO_MGR.FindPlugin if major >= 10 else pcbnew.PCB_IO_MGR.PluginFind
    importer = factory(pcbnew.PCB_IO_MGR.EASYEDA)
    source_fp = importer.FootprintLoad(str(source), 'orientation')
    assert source_fp is not None, 'Native EasyEDA importer returned no footprint'
    original = measure(source_fp)
    loader = factory(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    generated = loader.FootprintLoad(str(pretty), 'orientation')
    assert generated is not None, 'Native KiCad importer returned no footprint'
    print(json.dumps({'source': original, 'generated': measure(generated)}))


if __name__ == '__main__':
    main()
