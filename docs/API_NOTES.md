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

## Fields verified against the fixtures

Positions below are zero-based after splitting a record on `~`, including type.
`dataStr` may also arrive as a JSON string. Missing, empty and `undefined` fields
use defaults where supported; copper text geometry requires explicit values. One drawing unit is 0.254 mm, regardless of canvas grid units.
Subtract each document's head.x/y; negate Y only for symbols. When head.x/y
is missing, blank, `undefined` or invalid, use the canvas origin per axis:
symbol canvas indices 13/14, footprint canvas indices 16/17 (zero-based,
including CA). Keep valid explicit zeros. If neither origin source is usable,
fail clearly instead of silently treating the drawing as originating at zero
or guessing an anchor from the bounding box.

| Record | Fields |
| --- | --- |
| Symbol R | x=1, y=2, corner radii=3/4, width=5, height=6, stroke width=8, fill=10 |
| Symbol E | center x/y=1/2, radii=3/4, stroke=6, fill=8 |
| Symbol A | SVG path=1, helperDots=2, stroke color=3, stroke width=4, style=5, fill=6 |
| Symbol PL/PG | point pairs=1, stroke color=2, stroke width=3, style=4, fill=5 |
| Symbol PT | SVG path=1, stroke color=2, stroke width=3 (derived regression; no real PT fixture) |
| Symbol T | x/y=2/3, rotation=4, font size=7 (pt), text=12 |
| Symbol P | main section: electrical type=2, fallback number=3, x/y=4/5, rotation=6; split `^^`: path=2, name=3, number=4, inversion=5, clock=6 |
| Pin labels | text=4 inside name/number subsections; empty electrical type defaults to unspecified |
| Footprint RECT | x/y=1/2, width/height=3/4, layer=5, id=6 (verified by OLED) |
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
PAD plating accepts `Y/N`, `yes/no`, `true/false` and `1/0` without case
sensitivity. The older `b156dd17` header fixture verifies `yes`. Empty, missing
or unknown through-hole plating defaults to plated with a warning; it never
silently becomes NPTH. SMD pads do not use plating. Geometry/drill/layer checks
still apply. The `N` mapping is a derived calibration checked with native KiCad;
it is not an additional real non-plated component sample. NPTH pads use outer
copper/mask layers, matching KiCad's native EasyEDA importer.

**Fixture discrepancy resolved by user:** MAX98357A has **9** P records,
not 7. Speaker pins `+` and `--` duplicate numbers 1 and 2 of the seven header
pins. The user requested keeping all nine pins and reporting duplicate numbers.
Do not discard either speaker connection. TP4056 has four pins. Both packages have the expected 7/4 pads.

## Layers and output conventions

1/2 = F.Cu/B.Cu; 3/4 = F.SilkS/B.SilkS; 5/6 = F.Paste/B.Paste;
7/8 = F.Mask/B.Mask; 10 = Edge.Cuts; 11 = through-hole *.Cu + *.Mask;
12 = Dwgs.User (Document); 13/14 = F.Fab/B.Fab (Top/Bottom Assembly);
99/100/101 = User.3/User.4/User.5 (component/lead/marking shapes).
These mappings match KiCad 9's Standard importer and the layer names embedded
in our real fixtures. Unmapped drawing layers warn; unknown pad layers fail.
We do not map model layer 19 or add inner-copper support in this audit.
Layer 15 (Mechanical) drawings remain skipped, with one count summary per
component instead of a warning for each element.
Generate F.CrtYd from exported pads, holes and non-text physical outlines,
with 0.25 mm margin rounded outwards to a 0.05 mm grid. Do not use source BBox
for courtyards: it can be stale or include remote documentation/text. Include
copper/paste/mask, silkscreen, assembly, Edge.Cuts and component shape User.3;
exclude documentation, lead/marking user layers and text. Rotated pad extents
are conservative; custom pads use actual transformed vertices. Arc bounds
include only extrema on the arc, plus stroke width, not the full circle.
KiCad 8/9/10 modern S-expressions use start/mid/end arcs. SVG circular arcs are
converted through the SVG endpoint-to-center algorithm; elliptical arcs are
sampled as polylines and reported. No third-party conversion source is copied.
Filled SVG regions support a single straight-edged contour only. A second
moveto or drawing after close is rejected instead of bridging contours or
guessing hole/winding semantics. Separate stroked contours remain separate.
Empty/degenerate fills, move-only arcs and zero-length tracks cannot satisfy
an essential copper record. TEXT uses layer field 7 for the same essential
classification as other copper records, including unsupported inner copper.
Geometry that collapses at the existing six-decimal output precision is also
empty; coordinate overflow fails rather than writing infinity into a library.
Malformed copper text fails; missing coordinates, size, stroke, rotation or
mirror flags cannot use decoration defaults to invent copper geometry.
Essential copper TRACK/ARC/CIRCLE/TEXT widths must be explicit, finite, positive
numbers that remain nonzero at output precision. They bypass the decoration
stroke minimum, so valid narrow copper is not enlarged to 0.01 mm.
Filled copper contours and custom-pad polygons reject self-intersections,
nonadjacent contacts and overlapping/backtracking edges. A native KiCad 9
EasyEDA import of the nonzero-area crossing `M0 0L4 4L0 4L4 0L5 -1Z`
remains self-intersecting; neither signed area nor successful loading proves
safe copper. The converter rejects ambiguity instead of guessing fill rules.
Intersection checks use integer nanometres and at most 1,000 vertices, bounding
the pairwise scan without a geometry dependency. Custom pads also require their
serialized circular anchor to fit inside the source polygon; it cannot add
copper outside the source. Genuine offset/custom-pad conventions remain limited.
PAD/VIA/HOLE positions require explicit finite numeric coordinates; missing
positions cannot become zero. When real slot-center points are supplied, they
must agree with the supported centered, pad-axis-aligned drill within 0.001 mm
of source rounding noise. Offset, independently angled or inconsistent slots
fail rather than being recentered or resized. This does not implement those
unverified drilling conventions.

## Unverified / bounded support

In the original MAX98357A/TP4056 fixtures, only R/P/E/T and TRACK/ARC/SOLIDREGION/TEXT/PAD occur.
Other documented records are implemented conservatively and must be checked
against real samples: PT/C, VIA/HOLE/CIRCLE, custom polygon pads,
slots, multilayer SMD and pin clock/inversion.
Unsupported optional drawings warn with UUID and raw line and are skipped.
Malformed P/PAD/VIA/HOLE records and supported copper geometry fail the whole
component before publication. Empty pins, or empty pads in a supplied footprint, fail too. Duplicate
pin numbers and unmatched physical pads remain allowed and are retained.
Multi-unit support uses the verified `result.subparts` layout described below.
Nonempty subparts inside dataStr remains an unsupported layout and fails.

## Conversion pipeline

The client fetches one component at a time and preserves response bytes.
Workflow orchestration resolves cached footprint data, then the converter builds
symbol, footprint and attribution text in memory. Complete output is staged,
optionally checked with native KiCad, and published with rollback metadata.
Cached conversion passes no client to the footprint resolver and stays offline.

For module responsibilities, formatting and development commands, see
[CONTRIBUTING.md](../CONTRIBUTING.md).

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
User drawing labels remain `fp_text user`. Only symbol T graphic text is
capped: `min(source points * 25.4 / 72, 1.905)` mm (**75 mil**). Empty or
`undefined` symbol font sizes keep the existing 9 pt fallback before the cap.
Smaller symbol text is preserved. Footprint TEXT height remains source field 9
times 0.254 mm, with the existing 5-unit fallback; no cap applies. Property and
pin-label fonts stay at 1.27 mm. The symbol's text envelope uses the actual
exported size when placing Reference/Value.

MAX98357A symbol sizes before/after the cap (mm): SPKR 3.175 (missing size,
9 pt fallback) → 1.905; I2S MONO AMP 2.293056 (6.5 pt) → 1.905;
MAX98357A 2.822222 (8 pt) → 1.905.

**Historical status: pad/text rotation sign and slot orientation remain unverified
in the original two fixtures alone.** The audit below adds real pad/slot evidence;
full text layout and genuine rear/custom source examples remain limited.
The old fixture has circular round pads at 180 degrees. The newer fixture has
square pads at 0/90 degrees. These symmetric shapes cannot establish rotation
sign. Both fixtures have holeRadius 1.968 and holeLength 3.937 drawing units:
the 0.001-unit difference from diameter 3.936 is rounding noise, not an oval
slot. The synthesized slot/rotation tests validate serialization only; they do
not verify EasyEDA's physical drilling convention. The earlier stock KiCad
checks establish KiCad angle units, not EasyEDA's pad/text rotation sign.

The audit obtained trustworthy examples from KiCad's stored EasyEDA Standard
board. Additional genuine custom-polygon and rear-mounted samples, with a
source drawing, are still useful for checking those remaining cases.

SVG arcs now read flags as individual characters, so compact `01`, `10`, and
flags followed immediately by an endpoint number are supported. Client base
cooldown must be at least 1 second (default 4 + 0–2 seconds jitter remains).
Retry-After seconds/dates are capped at 300 seconds with a one-line warning.
Two consecutive 403/429 responses still stop the entire run.

A cached item is complete only with usable `.kicad_sym` and
`.pretty/*.kicad_mod` files containing pins/pads and no model references.
New output also has `.ee2kicad-complete.json` with per-file SHA-256 hashes.
A pending publish journal always makes output incomplete. Legacy 2D output
without a manifest is accepted after structural and cached source-count checks.
Completion also checks the full UUID against raw.json and the symbol's EasyEDA
UUID property, the symbol/footprint entry names against their filenames, and
the symbol's Footprint property against its paired library. Comparisons of UUIDs
ignore hex letter case. Conflicting cache/manifest/target-symbol identities fail
before any replacement or initial cache write, even with `--force`. The usual
title-plus-eight-UUID-character naming stays unchanged; a collision requires a
different output root rather than sharing another component's folder.
Legacy unit-1 outputs with nonempty subparts, or outputs missing source pins,
pads, vias or holes, cannot silently pass this check. Incomplete libraries are rebuilt from raw cache
without requests, including no footprint fallback. Missing
fallback cache is an offline error; explicit `--force` allows retrieval.
Per-item exceptions are counted/logged and processing continues, except StopRun.

### Parser work limits

HTTP bodies are read incrementally and limited to 16 MiB; an oversized body
fails that item without retrying. Denial counting and cooldowns stay in effect
on read failures and rejected bodies. Cached/parser inputs
are limited to 16 MiB per file or document; each document
allows 10,000 shape records. A geometry string allows 1,000,000 characters and
100,000 parsed/emitted points (including ellipse samples). Each symbol or
footprint allows 100,000 generated drawing primitives. The local KiCad reader
allows 250,000 tokens and 64 nesting levels and scans flat expressions linearly.
These generous bounds prevent oversized coordinates, sampling amplification
and deep recursion from exhausting resources. Exceeding a limit on an essential
record or whole component fails before publication; optional drawings retain
their existing warning/skip behavior. Limits do not truncate or rewrite source
bytes. Existing files remain available after a rejected conversion.

Both launchers call the same stdlib-only `scripts/bootstrap.py`. The ready-marker
contains the SHA-256 of pyproject.toml, and only advances after successful pip
installation. They pass their original directory via `EE2KICAD_CWD`; relative
input/output paths and interactive defaults use that directory. Windows CMD
restores the saved `chcp` code page on both success and normal failure paths.

## OLED and SX1308 real fixtures

`6c69c66aa27f4c50aceb6e8226ef8d27` verifies footprint RECT:
`RECT~x~y~width~height~layer~id~...`; **layer is index 5**, id index 6.
Its two RECT records use layer 3 (F.SilkS). Unknown layers still warn and skip.
Its footprint head contains an official-library license string, copied verbatim
under `License (from source)` in CREDITS, alongside the existing source note.
Any symbol-head license is preserved separately too.

Hidden symbol properties form a left-justified column below the full drawing
and pins, at 1.27 mm intervals. Description whitespace is collapsed and its
property is at most 80 characters including `...`; CREDITS retains full source
Description, and raw.json is unchanged. Only Reference/Value remain visible.
The pin-name subsection flag controls name visibility; number flags are ignored
and numbers remain visible. SX1308 pin 2's name is hidden; author T labels stay.
KiCad does not preserve `hide` inside individual pin-name effects. Hidden names
therefore use KiCad's `~` blank-name marker. The original names remain in the
parsed pins, raw data, and hidden `EasyEDA Hidden Pin Names` JSON property.
A KiCad 9 save/SVG regression verifies that pin 2 remains blank, its number
remains visible, and the author's own GND/Vin/OUT text remains intact.

The SX1308 source includes SVGNODE metadata. This app exports only 2D
symbols and footprints: SVGNODE records and other model metadata are ignored,
without fetching or attaching models. Original raw responses are preserved.

All generated libraries, CREDITS and raw/fallback cache files use same-directory
temporary files followed by `os.replace()`. Interrupted writes leave the old
complete file (or no file), and normal failures remove temporary files. Conversions now stage every artifact before publishing. Explicit validation runs
on disposable copies before publication and fails if KiCad is unavailable.
Publication backs up replaced files, records `.ee2kicad-pending.json`, replaces
artifacts and installs completion metadata last. Normal failures roll back;
the next non-dry run recovers a journal left by process interruption. Recovery
preserves caches and unrelated files. This is recoverable multi-file publication,
not an atomic directory swap or a guarantee against filesystem/power failure.
A hard kill before journaling can leave unused hidden staging/backup directories.
After confirming no converter is running, these can be inspected and cleaned
up manually; do not remove recovery material while a pending journal exists.
Do not run concurrent conversions into the same component folder.

Legacy converter-owned footprints with actual `(model ...)` nodes are regenerated
from cached source. Pre-UUID library names are regenerated in place as aliases when their paired
symbol UUID verifies ownership; unassociated libraries are left untouched with
a manual-cleanup warning;
current UUID-suffixed libraries are also written. Source SVGNODE metadata alone
does not trigger migration. Existing STEP/WRL files are never removed. Missing
footprint cache fails offline. Changed attribution, changed legacy libraries and manifest-detected edits
are preserved in hash-suffixed previous files. Unrelated library files are not
overwritten.

Manifest-owned damaged libraries can be rebuilt without decoding their old
contents. Invalid UTF-8 or UTF-16 files are preserved byte-for-byte in previous
files before replacement. Unreadable libraries without matching ownership
metadata are refused, so an unrelated user file is never inferred to be ours.

CI runs the offline suite on Ubuntu and Windows, on Python 3.11 and 3.12.
Only dependency installation uses the network; component HTTP requests
are blocked by test fixtures. Native launcher tests run on their own platform.
Live smoke tests are explicitly excluded and disabled in CI.

`client.EDITOR_VERSION` is the single API editor-version setting (currently
`6.5.60`). The component request uses this constant for its version parameter.

Library names are now `safe_name(title) + "_" + uuid[:8]`. This applies to
symbol/footprint library filenames, internal names and the Footprint property.
Component output folder names already followed this scheme and remain stable.

## Optional live smoke check

`pytest -m live` selects one smoke test and one public component UUID, using
EasyEDAClient's default pacing and bounded retries. No search or package
fallback request is made. It checks the response and in-memory conversion. The
normal pytest selection is `not live`; CI explicitly excludes live tests and
the network fixture skips them whenever CI or EE2KICAD_DISABLE_LIVE is set.

## ESP32 origin regression

The real API responses `2e51d5a642224cf198048941f0630f26` and
`dd15f28aa16b42c0803759cacb9683e8` omit symbol head.x/y. Both retain
`3000,4000` as their symbol canvas origin. Defaulting the missing head values
to zero placed their symbols approximately 762 mm right and 1016 mm down
from KiCad's origin, making the normal-sized drawing appear tiny and displaced
in the editor. These unchanged responses are now offline regression fixtures.

Use the canvas origin without changing the 0.254 mm drawing-unit scale. Native
KiCad save/import checks verify pin positions near (0,0), pin lengths, pad
positions and physical dimensions. A native SVG regression includes an origin
marker to catch origin-to-drawing view inflation; ordinary SVG auto-cropping
alone had concealed the offset. The original four fixtures retain exactly the
same pin positions, lengths and pad dimensions as the first working commit.

## Audit reference checks

The mapping reference is KiCad's own EasyEDA Standard importer at commit
`ce707d0a6c8736cbf4689560be4fee3d6a7f7f5e` (9.0 branch):

- [PCB LayerToKi and pad/text import](https://github.com/KiCad/kicad-source-mirror/blob/ce707d0a6c8736cbf4689560be4fee3d6a7f7f5e/pcbnew/pcb_io/easyeda/pcb_io_easyeda_parser.cpp).
- [Symbol ConvertElecType](https://github.com/KiCad/kicad-source-mirror/blob/ce707d0a6c8736cbf4689560be4fee3d6a7f7f5e/eeschema/sch_io/easyeda/sch_easyeda_parser.cpp).

Pin types are 0 unspecified, 1 input, 2 output, 3 bidirectional and **4 passive**.
Empty/undefined stays unspecified; other values warn and become unspecified.
Type 4 formerly became power_in, which was incorrect for ERC.
The fixture layer tables identify 12 as Document and 13/14 as Assembly;
KiCad maps 12 to Dwgs.User, not F.Fab. Existing 1–8 and 10 mappings agree.
Layer 11 is special for through-hole pads, not a generic drawing-layer alias.
Unknown drawing layers never fall back to arbitrary fabrication layers.

Official EasyEDA documentation URLs consulted:
[Standard format](https://docs.easyeda.com/en/DocumentFormat/EasyEDA-Format-Standard/index.html)
and [PCB layers](https://docs.easyeda.com/en/PCB/Layers/index.html).
The audit environment denied access to that documentation host. Corrections
above rely on KiCad's authoritative importer plus the embedded real source
layer tables; no rules were guessed from the inaccessible pages. No importer
implementation code was copied.

## Verified pad/slot evidence and courtyard bounds

`tests/fixtures/geometry/real_pad_examples.json` contains unmodified excerpts
from KiCad's ESP32-PICO-D4 smart-watch Standard test board at the audit reference
commit above. Its provenance and separate CC-BY-NC-SA 3.0 license are included.
No component API requests are needed to run these tests.

The switch has rectangular 4.3307 × 7.4803-unit pads at **124 degrees**.
Their source polygon corners agree with KiCad's native EasyEDA import and our
native-loaded output. The positive serialized pad angle was correct and stays.
KiCad rotates local pad coordinates counterclockwise in a Y-down frame, so the
inverse transform for source polygon vertices uses **positive** math rotation.
The former negative inverse rotated custom vertices a second time. A clearly
labeled derived POLYGON calibration, retaining these real source corners,
now agrees with both native importers. This does not establish every genuine
custom-pad or offset-anchor convention.

The USB-C pad 19 has width 4.3307, height 9.4488, rotation 270, hole radius
1.2795 and holeLength 7.8741 units. Its hole-center points are horizontal and
5.3151 units apart (length minus diameter). Native KiCad imports local drill
sizes **0.65 × 2.0 mm**, rotating the long local Y axis into world X. We now put
holeLength on the longer local pad axis, matching the importer; previously it
always went on X and the hole turned 90 degrees. The 0.01 mm threshold still
suppresses rounding-only slots in all six original fixtures.

Native geometry tests compare pad position, angle, layers, polygon outlines,
drill dimensions and world hole bounding boxes. Rear-side calibration changes
an SMD source layer to B.Cu and agrees with native KiCad; a genuine asymmetric
rear-mounted component and offset/independently angled slots remain unverified.
The real rotated TEXT retains its source angle/size; the angle sign matches
KiCad's importer implementation, but baseline/justification/mirroring and full
visual text layout are not claimed to match. No sign or size change was made
to footprint text in this audit.

Courtyards no longer miss extended silkscreen/body outlines or custom polygons,
and remote text/stale BBox no longer inflates them. They are conservative 2D
bounds, not an IPC compliance or manufacturability guarantee. They remain
F.CrtYd; rear-side courtyard policy needs a genuine source comparison.

## Native integration and validation status

The Python 3.11/3.12 Ubuntu/Windows matrix remains. The native matrix installs
KiCad 8, 9 and 10 from the team's `ppa:kicad/kicad-{major}.0-releases` PPAs on
Ubuntu 24.04. The default Ubuntu repository supplies KiCad 7, so each job checks
that both kicad-cli and pcbnew report the requested major before testing.
`EE2KICAD_REQUIRE_KICAD=1` and `EE2KICAD_REQUIRE_PCBNEW=1` prevent silently
skipping the required tools. No EasyEDA network requests run in CI.

All **37 native cases** pass separately on **8.0.9**, **9.0.9** and **10.0.7**
in isolated Ubuntu 24.04 environments. Output stays at symbol version 20231120
and footprint version 20240108, compatible with KiCad 8. The geometry helper
handles the GetEffectivePolygon differences and KiCad 10's renamed FindPlugin
factory. KiCad 10 saves blank pin names as empty strings and property hide flags
outside effects; tests verify the same hidden/visible semantics and SVG labels.
Its footprint SVG exporter requires an existing output directory. Geometry,
drill, layer and text-angle assertions remain in force for every major.
Native KiCad on Windows/macOS and manual GUI inspection are not verified.

Explicit --validate now returns failure when KiCad is absent, fails or times
out. Symbol and footprint results are separate, and both are attempted on
copies. Only footprint library files are copied, not unrelated model/user files.
A 60-second timeout produces a clear diagnostic. Original files stay unchanged,
and no failed validation can publish a new completion record.

Redirects are disabled per request even for a supplied HTTP client configured
to follow them. Invalid NaN Retry-After values retain the normal backoff;
infinite/excessive values still cap at 300 seconds. Pacing, jitter and the
consecutive access-denial stop rule remain unchanged. No live component fetch
was used in this audit; reference reads came from public KiCad sources.

## Imported polygon pads and point-list regions

`c1e9a7b5304f4595a62af862fec3a102` (Eagle) and
`c50879e99f214b40a692b31827f5fe31` (Altium) contain genuine `PAD~POLYGON`
records with width/height `0`. Their absolute point pairs (field 10) define the
copper; missing dimensions are derived from the unrotated local polygon bounds.
Consecutive repeated vertices are harmless. Polygon validity and anchor containment
checks remain required; negative dimensions and invalid layers still fail. Errors
include each bad pad's raw record and reason before any libraries are published.

The Eagle transistor's `SOLIDREGION` field 3 is a bare list of XY pairs, not
an SVG path. This format is parsed as one closed polygon. The same checks for
empty, malformed, compound and self-intersecting copper regions still apply.

## Symbol-only sources

`82015f7d9a6543b7b998917289a50b78` (Device_Buzzer) contains a symbol and
a textual Origin Footprint name, but neither packageDetail nor head.puuid.
Export only the symbol, with an empty Footprint property and no `.pretty`
directory. Log `symbol only: no footprint in source`, retain that note in CREDITS,
and count the item as succeeded with warning. Validation checks only the symbol.
Completion checks accept this only with an empty association and no generated
footprint; a cached source with footprint geometry still requires all pads.
A nonempty puuid still requires the existing cached/fetched fallback; missing
fallback data, malformed UUIDs and invalid supplied footprints remain errors.

## STM32 multi-unit source

`0010e6e3c07c4ca9b85cbb34a79052f3` contains `result.subparts`: an ordered
list of objects with uuid/title/dataStr. The parent dataStr duplicates the first
unit (9 power pins). The two subpart dataStr documents contain 9 and 39 pins;
together they cover pins 1–48 exactly once, matching 48 footprint pads. The list
is authoritative: do not add the parent again. Both subparts incorrectly have
`c_para.subpart_no = "1"`, so numbering follows list order. Each document has
its own head/canvas origin, shapes and BBox.

Export each complete document into `name_1_1`, `name_2_1`, etc., with both its
body and pins in that unit, translated using its own origin. Reference/Value
clear the first unit. Hidden metadata clears all units' drawings/pins.
Incomplete/nested/unknown unit layouts, parent geometry differing from the first
unit, or any unparseable unit element fail the whole component. Duplicate pin
numbers still warn and remain stored. Limits are 100 units, 10,000 combined
shapes and the existing total primitive bound. Cache pin counts include all units;
a legacy unit-1-only export must be rebuilt from raw bytes without HTTP.

Origin fallback warnings now identify `symbol` or `footprint` (including failures
to resolve an origin). New imported fixtures omit symbol head.x/y and verify the
same 3000/4000 canvas fallback. Their footprint head origins are present and
agree with canvas fields 16/17; tests remove those head fields and verify
byte-identical footprints and unchanged pad positions, not an inferred recentering.

## LED source artwork check

`9600215afc5549bca9bc489bdc414477` (LED_LEDCHIP-LED0805) uses explicit
footprint origin (400,300), matching its canvas. Its pad centers are (400,304.134)
and (400,295.866): local KiCad (0,+1.050036) and (0,-1.050036) mm.
Three source SOLIDREGION bars on layer 3 become F.SilkS; their X coordinates
span approximately ±0.675 mm and Y is -0.299974 to 0 mm, between the pads.
Two more SOLIDREGION rectangles and two TRACK outlines are layer 12 (Document),
so they belong on Dwgs.User. The rectangles extend to Y ±1.050036 mm over
pad areas. They are the author's documentation artwork, not remote silkscreen
or an origin offset. No artwork is moved, deleted or relayered to improve looks.
The bare-point parser above now exports all five regions rather than skipping
them. Source coordinate tests and native KiCad polygon checks verify their
locations and layers. A GUI comparison with the author's original editor view
has not been performed.

## Symbol arc field-layout regression

The Device_Buzzer fixture `82015f7d9a6543b7b998917289a50b78` verifies
`A~path~helperDots~strokeColor~strokeWidth~style~fill~...`. Its stroke color
is `#A00000` at index 3; stroke width `1` is at index 4 (0.254 mm). Reading
index 3 as width skipped the buzzer's arc. Export that arc with its source
endpoints, converted through the symbol origin and Y flip. `PT` has no
helperDots field and keeps width at index 3; a derived regression guards the
difference without claiming a real PT sample.

A scan of all twelve component fixtures, including STM32 subparts, found no
other symbol field-index failures. Their drawing records are R, E, T, PL, PG
and A; existing pin checks cover P. Regression tests parse every fixture drawing
and check stroke fields for R (8), E (6), PL/PG (3) and A (4). No real C or PT
records occur in these fixtures, so their source layouts remain unverified by
real samples. This fix changes only the A stroke-width lookup.
