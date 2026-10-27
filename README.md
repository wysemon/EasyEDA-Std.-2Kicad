# easyeda2kicad-local

Converts public EasyEDA Standard component links to local KiCad 8/9 symbols and footprints, one link at a time, with no search or account.

## Quick start

Install **Python 3.11+** from [python.org](https://www.python.org/downloads/).
On Windows, enable the PATH option. Then open a terminal.

Windows CMD:

```bat
git clone https://github.com/wysemon/EasyEDA-Std.-2Kicad.git
cd EasyEDA-Std.-2Kicad
run https://easyeda.com/component/7db93ef938c54a728e02f6579db05977
```

Linux/macOS:

```sh
git clone https://github.com/wysemon/EasyEDA-Std.-2Kicad.git
cd EasyEDA-Std.-2Kicad
./run.sh https://easyeda.com/component/7db93ef938c54a728e02f6579db05977
```

The first run creates `.venv` and installs the package. Later runs reuse it.
The ready-marker stores a SHA-256 hash of `pyproject.toml`; dependency changes trigger reinstall automatically.
Run `run` or `./run.sh` without arguments to paste links. Finish with an empty line.
If `links.txt` exists, Enter accepts `Found links.txt, use it? [Y/n]`.

## Import into KiCad

Use the **exact absolute paths printed at the end of the run**.

1. Open **Preferences > Manage Symbol Libraries**. Add the `.kicad_sym` file.
2. Open **Preferences > Manage Footprint Libraries**. Add the `.pretty` folder.
3. Name both libraries after the generated file/folder stem, such as `MAX98357A_NO_HOLES_7db93ef9`. In the Schematic Editor, press **A** and place the symbol.

Library nicknames and generated filenames use `{safe_title}_{uuid8}` to distinguish components with the same title.
The symbol already has a matching `library:name` Footprint property.
Older cached outputs can be rebuilt with `convert`; use the new UUID-suffixed library nickname in KiCad.
Only Reference and Value properties are visible. Attribution and source metadata stay stored but hidden.
Symbol graphic text is capped at 75 mil (1.905 mm); smaller source text stays smaller.
Footprint drawing text keeps its source sizes. Property and pin-label sizes stay at 1.27 mm.
Footprint Reference/Value use KiCad 8 `property` records.

## Example

Input: https://easyeda.com/component/7db93ef938c54a728e02f6579db05977

```text
output/
├── fetch_log.tsv
└── MAX98357A_NO_HOLES_7db93ef9/
    ├── raw.json
    ├── CREDITS.txt
    ├── MAX98357A_NO_HOLES_7db93ef9.kicad_sym
    └── MAX98357A_NO_HOLES_7db93ef9.pretty/
        └── MAX98357A_NO_HOLES_7db93ef9.kicad_mod
```

Sample stdout on Linux, with an example checkout location:

```text
Summary: 1 succeeded, 0 failed, 0 skipped.
Output: /home/me/EasyEDA-Std.-2Kicad/output
add /home/me/EasyEDA-Std.-2Kicad/output/MAX98357A_NO_HOLES_7db93ef9/MAX98357A_NO_HOLES_7db93ef9.kicad_sym in Symbol Libraries
add /home/me/EasyEDA-Std.-2Kicad/output/MAX98357A_NO_HOLES_7db93ef9/MAX98357A_NO_HOLES_7db93ef9.pretty in Footprint Libraries
```

This component also logs duplicate pin numbers 1 and 2. All nine symbol pins and seven footprint pads are kept.

### More commands

Re-convert the cache and optionally check it with KiCad:

```bat
run convert 7db93ef938c54a728e02f6579db05977 --validate
```

On Linux/macOS, use `./run.sh` instead of `run`. `--validate` runs KiCad upgrades
on temporary copies, then reports PASS/FAIL. Originals stay unchanged.
If `kicad-cli` is missing, it prints one skip note. Validation is a parser check, not a design-rule check.

Several links or bare 32-hex UUIDs may be queued. They are processed sequentially.
`run --file links.txt` reads one link/UUID per line; blank lines and `#` comments are ignored.
Both `easyeda.com` and `www.easyeda.com` links work, including trailing slashes, queries and fragments.
Quote URLs containing `&` and paths containing spaces. For example:
`run "https://easyeda.com/component/7db93ef938c54a728e02f6579db05977?a=1&b=2"`.

Cached items are skipped only when both symbol and footprint files exist.
If only raw data is cached, the app reports `re-converting from cache` and rebuilds offline. `--force` fetches again and overwrites generated outputs.
`convert` uses cached data without making network requests. Use it after updating the converter.
`--dry-run` converts in a temporary directory without saving output or log changes.
Cached dry runs never request data, even with `--force`. Uncached fetch dry runs may request data.
`--verbose` shows diagnostics and tracebacks.

The launchers install from the checkout, but preserve the original working directory in `EE2KICAD_CWD`.
Relative `--file` and `--output` paths, default `output/`, and interactive `links.txt` are resolved there.
Installed console commands use the current directory unless that variable is set. `--output` chooses another location.
Windows CMD restores its original console code page when the launcher exits.
`raw.json` preserves the API response bytes. A separate footprint lookup adds `package_raw.json`.
`CREDITS.txt` records both authors and source details. `fetch_log.tsv` appends UTC timestamps and statuses.

After `pip install -e .`, `ee2kicad <link>` works without a subcommand.
Both `ee2kicad` and `easyeda2kicad-local` also accept `fetch ...`, `convert ...`, or no arguments for prompts.
Optional global installs: `pipx install .` or `uv tool install .`, from this checkout.
These require pipx or uv and their tool directory on PATH.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Python missing | Install Python 3.11+ from python.org. Enable PATH on Windows. On Debian/Ubuntu, venv creation may also need `python3-venv`. |
| HTTP 403/429 | Stop and wait. Check that the component is public. Do not retry rapidly or bypass access restrictions. |
| No internet | Check the connection and proxy settings. Cached `convert` still works offline. |
| Private component / `success:false` | Use a public Standard component link. The app does not log in or bypass permissions. |
| Text or pins look off | Re-convert cached data with the latest version. Check the source and warnings before using the result. Include the raw record when reporting a bug. |
| Duplicate pin warning | All pins are kept. In MAX98357A, speaker pins +/-- share numbers 1/2 with header pins. Check connectivity in KiCad. |
| Setup needs refreshing | Changes to `pyproject.toml` trigger refresh automatically. Delete `.venv/.ee2kicad-ready` to force a refresh. |
| Windows path too long | Keep the checkout path short. Sanitized titles are ASCII, at most 60 characters, and avoid reserved device names; library names append `_uuid8`. Console output and credits use UTF-8. |

## Be a polite client

Requests share one HTTP client and run sequentially. The default cooldown is
**4 seconds plus 0–2 seconds of random jitter** between all requests, including retries and footprint lookups.
This avoids rapid bursts against the public service. `--delay` changes the base cooldown, with a minimum of 1 second.
Caching avoids repeat downloads.

403/429/5xx responses honor `Retry-After`, capped at 300 seconds with a warning. Otherwise, retries wait 30 then 60 seconds,
with at most three attempts. **Two consecutive 403/429 responses stop the entire run**, including during retries.
Other item failures are logged and processing continues; any failure gives a nonzero exit status.
TLS verification stays enabled. Redirects, logins, captchas and paywalls are not bypassed.
The app contacts only easyeda.com, plus modules.easyeda.com when `--3d` is selected.

## Limitations

- `--3d` is experimental. The SX1308 fixture contains a real SVGNODE and its attributes are tested. STEP downloads are optional; automatic placement and relative-path attachment remain disabled pending a KiCad 3D viewer comparison. Place downloaded models manually. OBJ/WRL conversion is not implemented.
- Unverified record types are listed in [API notes](docs/API_NOTES.md). Unsupported records warn and are skipped. Unknown electrical types become unspecified. Multi-unit symbols warn and use unit 1 only when recognized.
- Circular SVG arcs become KiCad arcs. Elliptical arcs use sampled polylines. Pads support round, rectangular, oval and custom polygons, with through-hole or SMD layers.
- Pad/text rotation signs and true oval-slot orientation need a real sample to verify. Neither fixture has an asymmetric rotated pad or a true oval slot. See [API notes](docs/API_NOTES.md).
- There is no manufacturability guarantee. Review geometry, drills, pin mapping and clearances before fabrication.
- Public component data may have third-party restrictions. Attribution does not grant redistribution rights. Review the source and each generated CREDITS.txt.

### Development checks

On Linux/macOS, after setup:

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
```

On Windows, use `.venv\Scripts\python -m pip install -e ".[test]"`, then
`.venv\Scripts\python -m pytest`.
Tests are offline. KiCad integration checks skip when its CLI is unavailable.

## Credits and license

Independent implementation from the supplied API/format description and real
fixtures, released under the repository's MIT license. No upstream code copied.
Related tools and format research:
[easyeda2kicad.py](https://github.com/uPesy/easyeda2kicad.py) (AGPL-3.0) and
[JLC2KiCadLib](https://github.com/TousstNicolas/JLC2KiCadLib).
Their source code was not incorporated. Component authors retain their rights;
see each generated CREDITS.txt.

`ee2kicad --version` prints the installed application version. Developers can
run `.venv/bin/python -m ruff check .` (Windows: `.venv\Scripts\python -m ruff check .`).

### Optional live smoke test

`pytest -m live` opts into fetching exactly one public component through the
normal paced client, including its retry/stop rules. It makes no search,
footprint fallback, or model requests and writes no output files. The normal
suite deselects it. CI never runs it; `CI` or `EE2KICAD_DISABLE_LIVE` also forces
a skip even with `-m live`. The offline suite continues to block HTTP requests.
