# EasyEDA Standard API and conversion notes

## Endpoint and scope

The supplied browser HAR description verifies editor 6.5.60's public endpoint:
`GET https://easyeda.com/api/components/{uuid}?version=6.5.60&uuid={uuid}`.
Send Accept `application/json, text/javascript, */*; q=0.01`,
X-Requested-With `XMLHttpRequest`, Referer `https://easyeda.com/editor`,
and a browser User-Agent. No search, login, cookies, or authentication bypass.
API success is `success:true`; `result.dataStr` is the symbol and
`result.packageDetail.dataStr` is its footprint. Missing packageDetail is
resolved using symbol `head.puuid` through the same endpoint. Preserve responses
as bytes; fallback responses live separately in `package_raw.json`.

## Fields verified against the two fixtures

Positions below are zero-based after splitting a record on `~`, including type.
`dataStr` may also arrive as a JSON string. Missing, empty and `undefined` fields
use defaults. One drawing unit is 0.254 mm, regardless of canvas grid units.
Subtract each document's head.x/y; negate Y only for symbols.

| Record | Fields |
| --- | --- |
| Symbol R | x=1, y=2, corner radii=3/4, width=5, height=6, stroke width=8, fill=10 |
| Symbol E | center x/y=1/2, radii=3/4, stroke=6, fill=8 |
| Symbol T | x/y=2/3, rotation=4, font size=7 (pt), text=12 |
| Symbol P | main section: electrical type=2, fallback number=3, x/y=4/5, rotation=6; split `^^`: path=2, name=3, number=4, inversion=5, clock=6 |
| Pin labels | text=4 inside name/number subsections; empty electrical type defaults to unspecified |
| TRACK | width=1, layer=2, net=3, point pairs=4 |
| ARC | width=1, layer=2, net=3, SVG path=4 |
| SOLIDREGION | layer=1, net=2, SVG path=3, fill type=4 |
| TEXT | x/y=2/3, stroke width=4, rotation=5, mirror=6, layer=7, height=9, text=10, ignored stroke path=11 |
| PAD | shape=1, x/y=2/3, width/height=4/5, layer=6, net=7, number=8, hole radius=9, polygon points=10, rotation=11, id=12, hole length=13, hole points=14, plated=15; later fields vary |

Pin path `M x y h/v distance` gives connection point, direction into the body,
and length. Pin label visibility does not determine electrical connectivity.
Round fixture pads: 7.6 units = 1.9304 mm; drill 3.936 units = 0.999744 mm;
holeLength 3.937 differs only by rounding, so do not create a microscopic slot.
Square fixture pads: 5.937 units = 1.507998 mm; pitch 60 x 70 units =
15.24 x 17.78 mm. Round pad pitch: 10 units = 2.54 mm.

**Fixture discrepancy resolved by user:** MAX98357A has **9** P records,
not 7. Speaker pins `+` and `--` duplicate numbers 1 and 2 of the seven header
pins. The user requested keeping all nine pins and reporting duplicate numbers.
Do not discard either speaker connection. TP4056 has four pins. Both packages have the expected 7/4 pads.

## Layers and output conventions

1/2 = F.Cu/B.Cu; 3/4 = F.SilkS/B.SilkS; 5/6 = F.Paste/B.Paste;
7/8 = F.Mask/B.Mask; 10 = Edge.Cuts; 11 = through-hole *.Cu + *.Mask;
12/13 = F.Fab; 14 = B.Fab; 99/100/101 = F.Fab. Unmapped layers warn.
Generate F.CrtYd from declared geometry BBox plus 0.25 mm (include pad extents).
KiCad 8/9 modern S-expressions use start/mid/end arcs. SVG circular arcs are
converted through the SVG endpoint-to-center algorithm; elliptical arcs are
sampled as polylines and reported. No third-party conversion source is copied.

## Unverified / bounded support

Only R/P/E/T and TRACK/ARC/SOLIDREGION/TEXT/PAD occur in these fixtures.
Other documented records are implemented conservatively and must be checked
against real samples: PL/PG/PT/A/C, VIA/HOLE/CIRCLE/RECT, custom polygon pads,
slots, multilayer SMD, electrical-type mappings, pin clock/inversion, subparts.
Unsupported paths or records warn with their raw line and are skipped.
Subparts are unverified: warn and use unit 1 only when a recognizable shape
container is supplied; do not guess unrecognized layouts.

Neither fixture has SVGNODE or uuid_3d. The proposed modules.easyeda.com OBJ
and STEP endpoints and transforms remain unverified. Request a model-bearing
sample before finalizing 3D. Do not invent model placement from head origins.

## Implementation and validation plan

1. Build a sequential httpx fetcher with pacing, bounded retries, cross-item
   throttling detection, byte-preserving cache and append-only status log.
2. Implement independent tolerant geometry parsers and KiCad serializers,
   footprint first, then symbol, credits and optional model handling.
3. Expose Typer fetch/convert commands, file input, force, delay, dry-run and
   verbose flags. Cached convert performs no network requests.
4. Validate fixture geometry, coordinates, directions, credits, output syntax,
   caching and error handling with offline pytest tests and mocked HTTP only.
5. Document setup, library import, limitations and upstream credits. Do not
   claim full KiCad import validation without an available KiCad parser.

## CLI portability and validation

Input URLs accept precisely easyeda.com or www.easyeda.com over HTTPS, optional
trailing slash, query and fragment. Requests still use the canonical easyeda.com
API host. The SVG number regex recognizes signs as separators (`10-5`), compact
commands (`M500 233h -10`), relative h/v and exponent notation. Offline tests
exercise pin paths from both original fixtures and compact/spaced equivalents.
`--validate` upgrades temporary copies with KiCad CLI; generated originals are
never upgraded in place. A successful upgrade checks parsing, not geometry or
connectivity. The launchers bootstrap once, use UTF-8 and retain request pacing.

## Text angles and symbol property placement

Verified using the installed KiCad **9.0.2** stock libraries, not inferred from
EasyEDA field names:

| Kind | Stock example | Stored angle for vertical text |
| --- | --- | --- |
| Symbol graphic `(text ...)` | `Amplifier_Audio.kicad_sym`, SSM2018, `GAIN CORE`, `(at -1.27 0 900)` | **900**, tenths of a degree |
| Symbol `(property ...)` | `Device.kicad_sym`, FerriteBead, Reference `(at -3.81 0.635 90)` and Value `(at 3.81 0 90)` | **90**, degrees |
| Footprint `(fp_text ...)` | `Button_Switch_SMD.pretty/SW_DIP_SPSTx01_Slide_6.7x4.1mm_W6.73mm_P2.54mm_LowProfile_JPin.kicad_mod`, `${REFERENCE}`, `(at 2.58 0 90)` | **90**, degrees |

Exporting these stock libraries with KiCad CLI gives SVG `rotate(-90 ...)`:
bottom-to-top reading direction. Reflect the symbol orientation when converting
Y-down to Y-up, then scale **only graphic-text angles** by ten:

| EasyEDA T rotation (degrees) | KiCad symbol graphic angle |
| --- | --- |
| 0 | 0 |
| 90 | 2700 |
| 180 | 1800 |
| 270 | 900 |

Properties remain horizontal at 0 degrees. Footprint text retains its existing
degree angles and Y-down coordinates; do not apply the symbol multiplier.
Fixture-based tests cover every cardinal angle on both documents, and all four
symbol graphic angle values survive a KiCad CLI upgrade/save round trip.

Reference and Value use the default centered 1.27 mm font. Their X position is
the center of converted non-text body geometry (fallback: the full drawing).
Value sits 2.54 mm above the full converted envelope, with Reference 2.54 mm
higher. The envelope includes pin paths, conservative rotated text extents and
the source BBox. Circle/arc envelopes are conservative. This also works without
a BBox. Every other property has `hide` inside `effects`, including EasyEDA UUID;
source, author and other metadata remain stored.

## Review fixes and remaining rotation/slot verification

The footprint declares KiCad 8 version `20240108` and emits `property "Reference"`
and `property "Value"`, rather than legacy `fp_text reference/value` records.
User drawing labels remain `fp_text user`. Both symbol T drawing text and
footprint TEXT drawing labels now use **75 mil = 1.905 mm**, irrespective of the
source font size. Property and pin-label fonts stay at 1.27 mm. The symbol's
text envelope uses the actual exported size when placing Reference/Value.

**EasyEDA pad/text rotation sign and slot orientation remain unverified.**
The old fixture has circular round pads at 180 degrees. The newer fixture has
square pads at 0/90 degrees. These symmetric shapes cannot establish rotation
sign. Both fixtures have holeRadius 1.968 and holeLength 3.937 drawing units:
the 0.001-unit difference from diameter 3.936 is rounding noise, not an oval
slot. The synthesized slot/rotation tests validate serialization only; they do
not verify EasyEDA's physical drilling convention. The earlier stock KiCad
checks establish KiCad angle units, not EasyEDA's pad/text rotation sign.

A public Standard component link/UUID or raw component JSON with an asymmetric
rotated pad and a genuine oval drill slot is requested before changing signs
or claiming orientation verification. A source screenshot/dimensioned drawing
would also allow checking the output against the intended drill axis.

SVG arcs now read flags as individual characters, so compact `01`, `10`, and
flags followed immediately by an endpoint number are supported. Client base
cooldown must be at least 1 second (default 4 + 0–2 seconds jitter remains).
Retry-After seconds/dates are capped at 300 seconds with a one-line warning.
Two consecutive 403/429 responses still stop the entire run.

A cached item is complete only with a `.kicad_sym` file and a
`.pretty/*.kicad_mod` file. Incomplete libraries are rebuilt from raw cache
without requests, including no footprint fallback or 3D download. Missing
fallback cache is an offline error; explicit `--force` allows retrieval.
Per-item exceptions are counted/logged and processing continues, except StopRun.

Both launchers call the same stdlib-only `scripts/bootstrap.py`. The ready-marker
contains the SHA-256 of pyproject.toml, and only advances after successful pip
installation. They pass their original directory via `EE2KICAD_CWD`; relative
input/output paths and interactive defaults use that directory. Windows CMD
restores the saved `chcp` code page on both success and normal failure paths.
