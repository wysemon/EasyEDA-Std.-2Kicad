# PR #1 follow-up — 2026-10-27

## Unreadable cached libraries

Previously, the overwrite guard decoded every existing library as UTF-8 before
checking ownership. A file already identified by a matching completion manifest
could therefore prevent its own repair if it contained invalid UTF-8 or UTF-16.

Manifest-owned libraries now rebuild without decoding their damaged contents.
Their exact bytes are retained in `.previous-<hash>` files. An unreadable library
without verified ownership is refused with a clear instruction to move it aside;
the converter does not assume that arbitrary binary/user files belong to it.

Ten regression cases cover both symbol and footprint files on both original
fixtures, invalid UTF-8, UTF-16, preserved bytes, offline operation, a subsequent
unchanged cache skip, and rejection of unreadable unowned files.

## Native CI failure

The original CI job incorrectly assumed Ubuntu 24.04's default repository
provided KiCad 8. It actually installs **7.0.11**, which cannot read our KiCad
8-format libraries. Reproducing that setup in an isolated Ubuntu 24.04 container
produced **18 failed native tests**. This explains the failed native job on
[the original PR run](https://github.com/wysemon/EasyEDA-Std.-2Kicad/actions/runs/40537045051).
The four Windows/Linux Python matrix jobs on that run succeeded.

The corrected job uses the KiCad team's maintained
`ppa:kicad/kicad-8.0-releases` repository, then checks that both the CLI and
Python geometry bindings report major version 8 before testing. The current
repository build is **8.0.9-0~ubuntu24.04.1**. The existing four Python matrix
jobs and all native assertions remain in place.

Launchpad's metadata API is blocked in this development environment, so local
reproduction installed the same PPA's KiCad 8.0.9 and runtime packages directly
over verified HTTPS, checking every package against the repository's published
SHA-256 metadata. No TLS checks were disabled. GitHub CI uses the normal signed
APT repository setup. The version-check step was executed locally as written.

## Verification

| Environment / check | Result |
| --- | --- |
| Debian host, Python 3.12.14, native KiCad 9.0.2 | **492 passed, 1 skipped, 1 deselected** |
| Isolated Ubuntu 24.04, Python 3.12.3, native KiCad 8.0.9 | **492 passed, 1 skipped, 1 deselected** |
| Native-only selection on KiCad 8.0.9 | **18 passed** |
| Ruff on both environments | Passed |
| CI's CLI/binding major-version guard on KiCad 8.0.9 | Passed |

The local skip is the native Windows CMD test; the live test is deselected.
No live EasyEDA request was made. No format, geometry, pacing, or 3D behavior
was changed to resolve these issues. Remaining source-to-physical comparison
limits from `API_NOTES.md`, including genuine rear/custom components and full
footprint-text layout, still apply. macOS was not executed.

The original audit is retained as a historical snapshot. This follow-up records
the corrected package assumption and actual KiCad 8 execution. Check
[PR #1's checks](https://github.com/wysemon/EasyEDA-Std.-2Kicad/pull/1/checks)
for results on the latest pushed commit.
