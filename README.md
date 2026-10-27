```bat
git clone https://github.com/wysemon/EasyEDA-Std.-2Kicad.git
cd EasyEDA-Std.-2Kicad
run https://easyeda.com/component/7db93ef938c54a728e02f6579db05977
```

On Linux/macOS, replace the last command with:

```sh
./run.sh https://easyeda.com/component/7db93ef938c54a728e02f6579db05977
```

Install **Python 3.11+** from [python.org](https://www.python.org/downloads/) first
(on Windows, enable the PATH option). The launcher creates `.venv` and installs
the package on its first run; subsequent runs reuse it without calling pip.
On Linux, your distribution may also require `python3-venv`. Both launchers
work when called by their full path from another directory, including paths
containing spaces. They use the **repository directory** for `output/` and
`links.txt`. The installed console commands instead use your current directory.
If dependencies change after a pull, delete `.venv/.ee2kicad-ready` to reinstall.

Run `run` (Windows) or `./run.sh` (Linux/macOS) with no arguments to paste
multiple links, one per prompt; finish with an empty line (EOF also finishes).
If `links.txt` exists, answer `Found links.txt, use it? [Y/n]` (Enter means yes).
Several links or UUIDs can also be passed on one command line. Quote links
containing shell characters such as `&`, and quote paths containing spaces.
`run convert <uuid>` / `./run.sh convert <uuid>` reuses cached data offline.

After conversion, follow the two printed KiCad steps:

1. Add the absolute `.kicad_sym` file in **Preferences → Manage Symbol Libraries**.
2. Add the absolute `.pretty` folder in **Preferences → Manage Footprint Libraries**.

Use the generated name for both libraries. The final summary counts succeeded,
failed and skipped items and prints the absolute output and library paths.
A stopped run separately reports items it did not process.

# easyeda2kicad-local

A local, link-driven EasyEDA **Standard** component converter for KiCad 8/9.
Python 3.11 or newer. No search, database, account, cookies or background service.

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/easyeda2kicad-local fetch https://easyeda.com/component/7db93ef938c54a728e02f6579db05977
.venv/bin/easyeda2kicad-local fetch --file links.txt --output output
.venv/bin/easyeda2kicad-local convert 7db93ef938c54a728e02f6579db05977
.venv/bin/python -m pytest
```

`links.txt` contains one UUID or component URL per line; blank lines and lines
starting with `#` are ignored. Multiple positional inputs are also accepted.
Trailing slashes, query strings and fragments are accepted. Only HTTPS
easyeda.com and www.easyeda.com component URLs and 32-hex UUIDs are accepted. `--verbose` exposes conversion diagnostics.

`fetch` skips existing item folders unless `--force`; cached raw responses are
not downloaded again. `convert` always regenerates from the local cache and
makes no HTTP requests. Failed/partial conversions retain raw data: use `convert`
to retry. Missing embedded footprints are fetched via head.puuid and cached as
`package_raw.json`; offline conversion requires that fallback cache too.

`--dry-run` converts into a temporary directory which is then removed; it does
not change output or the fetch log. Cached dry runs never use the network, even
with `--force`. An uncached fetch dry run may fetch the component and footprint.

## Files and KiCad import

Each component gets `output/{sanitized-title}_{uuid8}/` containing:

- `raw.json`: original API response bytes, without rewriting or enriching them
- `{name}.kicad_sym`: symbol library, including metadata and source properties
- `{name}.pretty/{name}.kicad_mod`: footprint library
- `CREDITS.txt`: source, separate authors, update times and license caution
- `package_raw.json`: only when a separate footprint lookup was needed

`output/fetch_log.tsv` is append-only (UTC timestamp, UUID, status).
Add the `.kicad_sym` in KiCad's symbol library manager and `.pretty` in its
footprint library manager, using **the generated name** for each library.
The symbol's Footprint property is `{name}:{name}`. Dimensions and origins are
converted to mm; symbols flip Y, footprints retain Y-down.

Public components may still carry third-party rights. Generated CREDITS are
attribution, not permission to redistribute. Review the original source/license.
Official/LCSC attribution follows the available contributor/license metadata.

## Request policy

One shared httpx client; strictly sequential requests to easyeda.com only.
Default cooldown is 4 seconds plus 0–2 seconds random jitter between **all**
requests, including retries and footprint fallbacks. `--delay N` changes the
base cooldown. 403/429/5xx honor Retry-After (seconds or HTTP date), otherwise
back off 30 then 60 seconds within a three-attempt limit. A third exponential
interval would be 120 seconds, but there is no fourth attempt. Two consecutive
403/429 responses stop the entire run immediately, including during retries.
Other per-item failures are logged and processing continues; any failure makes
the command exit nonzero. TLS verification remains enabled; redirects, login,
captchas and paywalls are never bypassed.

## Experimental 3D

`fetch --3d` additionally allows modules.easyeda.com and attempts a STEP download
when a model UUID is present in head.uuid_3d or SVGNODE attrs.uuid. Failures or
absent models warn and do not prevent 2D conversion (throttling still stops the
run). STEP content is checked for an ISO-10303-21 header. Neither supplied
fixture has a model. **Model transforms and automatic relative-path attachment
are deferred until a real model-bearing JSON sample is supplied**: downloaded
STEP files are retained beside the library but must be placed manually in KiCad.
OBJ/WRL conversion is not implemented. Dry runs do not download models.

## Supported geometry and limits

Pins, rectangles, circles/ellipses, text, polylines/polygons and SVG M/L/H/V/A/Z
paths; footprint pads, tracks, arcs, solid regions, text, circles/rectangles,
holes and vias. Circular SVG arcs become KiCad three-point arcs; elliptical
arcs are sampled and warn. Unsupported geometry warns with the original raw
record. Pads support round/rect/oval/custom polygons, through-hole plating,
SMD layers, slots and rotation. No design-rule or manufacturability guarantee.
Review converted geometry before fabrication. Unknown electrical types become
unspecified; unverified formats are listed in [API notes](docs/API_NOTES.md).
Multi-unit inputs warn and use unit 1 only when its shape container is recognized.

The MAX98357A fixture has **nine**, not seven, electrical pins. Per the selected
behavior, all nine are retained, including speaker pins +/-- sharing numbers
1/2 with header pins. Duplicate numbers warn. It has seven footprint pads.
TP4056 has four pins and four pads. Tests check these actual counts, geometry,
origins, orientation, credits, network behavior, caching and CLI paths offline.
No live EasyEDA request is needed to run the tests.

## Credits and license

Independent implementation from the supplied API/format description and real
fixtures, released under the repository's MIT license. No upstream code copied.
Related tools and format research:
[easyeda2kicad.py](https://github.com/uPesy/easyeda2kicad.py) (AGPL-3.0) and
[JLC2KiCadLib](https://github.com/TousstNicolas/JLC2KiCadLib).
Their source code was not incorporated. Component authors retain their rights;
see each generated CREDITS.txt.

## Short commands and optional global installation

After `pip install -e .`, `ee2kicad <link>` defaults to fetch. Both console names
also accept explicit `fetch ...` and `convert ...`, or no arguments for prompts.
To use a repository venv directly on Windows, type `.venv\Scripts\ee2kicad <link>`;
on Linux/macOS, `.venv/bin/ee2kicad <link>`.

For a global command isolated from other Python projects, from this checkout:

```sh
pipx install .
# or
uv tool install .
ee2kicad https://www.easyeda.com/component/7db93ef938c54a728e02f6579db05977
```

These routes require [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/)
and their tool bin directory on PATH; the launcher route needs neither.

## Optional validation and troubleshooting

Append `--validate` to `run <link>` / `./run.sh <link>`, or use
`ee2kicad convert <uuid> --validate`. If `kicad-cli` is on PATH, the program copies
the generated symbol file and entire `.pretty` directory to a temporary folder
and runs `kicad-cli sym upgrade --force` and `kicad-cli fp upgrade --force` there.
It reports PASS/FAIL for each; originals are untouched. This checks KiCad's
parser/upgrade operation, not electrical correctness or manufacturing rules.
A validation failure gives a nonzero exit status. Without KiCad CLI, validation
is skipped with one note. Fetch still skips cached items unless `--force`;
use `convert --validate` to validate a cached item without downloading again.
Dry runs can validate their temporary outputs too.

Errors suggest a fix without a traceback; add `--verbose` for diagnostics and
tracebacks. For no internet, check your connection/proxy; for 403/429, wait and
check that the Standard component is public. Access restrictions are never
bypassed, and cooldowns/retry/stop rules apply to every request as before.
UTF-8 console output is enabled by the launchers. Generated names are ASCII,
limited to 60 characters, and avoid Windows device names (including names with
extensions). Keep the checkout path short if your Windows setup enforces the
legacy 260-character path limit. Raw titles and author credits retain Unicode.

Tests are offline and use the original fixtures and mocked responses. Optional
KiCad integration tests skip when its CLI is unavailable. Windows batch and
macOS execution need native platform verification; see the delivery report for
what was actually run in the development environment.
