# Contributing

Keep changes focused and preserve the converter's small, local, 2D-only design.
Start with the [README](README.md) for normal use and the
[API notes](docs/API_NOTES.md) for verified source formats and remaining limits.

## Development setup

Use Python 3.11 or newer. The launchers can create `.venv`, or you can set it up
directly from the checkout.

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

Windows CMD:

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
```

For the commands below, Windows users can replace `.venv/bin/python` with
`.venv\Scripts\python`. Activating the environment is optional.

## Checks

```sh
.venv/bin/python -m pytest -m "not live"
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Run `.venv/bin/python -m ruff format .` to apply the repository's formatting.
CI checks formatting and lint on both Windows and Linux with Python 3.11/3.12.

When changing package metadata, also check the wheel build:

```sh
.venv/bin/python -m pip wheel --no-deps --wheel-dir dist .
```

The normal suite uses stored fixtures and mocked HTTP. It blocks live component
requests. Reproduce bugs in a temporary output directory, and add a regression
test for a confirmed behavior change. Comments and mechanical formatting do not
need tests of their own.

### Native KiCad checks

With KiCad 8 or 9 installed and `kicad-cli` on PATH:

```sh
.venv/bin/python -m pytest -m "kicad and not live"
```

These tests import, save and render real converted fixtures. The pad comparisons
also need KiCad's Python `pcbnew` bindings. On Linux the suite can use the system
Python at `/usr/bin/python3` when the development venv cannot import them.
These are test tools, not application dependencies.

The dedicated CI job installs KiCad 8 from the KiCad team's maintained PPA and
verifies the CLI and binding versions. `EE2KICAD_REQUIRE_KICAD=1` and
`EE2KICAD_REQUIRE_PCBNEW=1` make missing native tools fail the required checks.

`pytest -m live` is a separate, explicit opt-in smoke check. It uses the normal
request pacing and stop rules. It is deselected by default and disabled in CI.

## Code map

| Module | Responsibility |
| --- | --- |
| `cli.py` | Arguments, prompts, caller-relative paths and readable errors |
| `client.py` | Approved public endpoint, sequential requests, pacing and retries |
| `workflow.py` | Cache lookup, offline boundaries, batch results and status log |
| `converter.py` | In-memory conversion, staging and compatibility exports |
| `symbol.py` / `footprint.py` | Source records and KiCad serialization |
| `shared.py` / `geometry.py` / `bounds.py` | Units, coordinate frames, SVG paths and physical bounds |
| `publication.py` / `files.py` | Completion checks, atomic file writes, rollback and recovery |
| `validation.py` | Native KiCad checks on disposable copies |
| `credits.py` | Source authors, descriptions and verbatim licenses |
| `scripts/bootstrap.py` | Dependency refresh shared by both launchers |

Document the reason behind a non-obvious rule near the code that enforces it.
Useful comments explain units, coordinate frames, format evidence, ownership or
failure recovery. Keep detailed source references in `docs/API_NOTES.md`.

## Conversion rules to preserve

- Captured responses and source licenses in `tests/fixtures/` retain their exact
  bytes. Do not run a JSON formatter or normalize their line endings. New real
  samples need provenance and source attribution.
- A source drawing unit remains **0.254 mm**. Only symbols reflect the Y axis.
  Graphic text, properties and footprint text have different angle conventions.
  Verify format changes against source evidence and native KiCad.
- Keep duplicate pins and author-drawn labels. Malformed essential electrical
  records fail the component; optional unsupported graphics warn. Multi-unit
  data is rejected rather than partially exported.
- Publication preserves previous files on failure. Dry runs do not change the
  output tree. Cached conversion must not gain a hidden HTTP fallback.
- Keep the **4 s + 0–2 s jitter** default, 1 s minimum, bounded retries and stop
  after two consecutive 403/429 responses. Do not reduce pacing for live tests.
- Keep exports 2D only. Source model metadata may remain in untouched raw JSON;
  it must not cause model downloads or attachments.

## Reporting a problem

Include the OS, Python/KiCad versions, exact command, public component link and
error or warning. For a conversion bug, include the relevant source record and
the expected geometry. Explain which checks you ran and what remains unverified.

The converter code uses the repository's MIT license. Component data keeps its
source rights; the geometry excerpts have their own license and attribution in
`tests/fixtures/geometry/`.
