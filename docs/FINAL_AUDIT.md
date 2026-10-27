# Final 2D release audit — 2026-10-27

## A. Summary

The existing converter was audited and extended with recoverable publication,
offline migration of old model references, stricter electrical-record handling,
verified layer/type corrections and native geometry regressions. No 3D feature,
runtime dependency, GUI or background service was added.

Work is on `audit/2d-release-safety`, based on `f704a24`. The default branch is
not merged or changed by this delivery. The GitHub API returned `Forbidden`, so
PR creation and remote CI status discovery are unavailable in this environment.
The branch is prepared for review through the
[comparison page](https://github.com/wysemon/EasyEDA-Std.-2Kicad/compare/main...audit/2d-release-safety).

## B. Confirmed bugs fixed

| Problem and cause | Correction and files | Regression evidence |
| --- | --- | --- |
| Existing symbol/mod filenames counted as complete, including old model references, truncated files and older partial electrical output. | `publication.py` reads actual KiCad nodes, checks essential structure, cached source counts and new completion hashes. `workflow.py` migrates from cache. | `test_publication.py`: current/legacy 2D skips, actual model nodes versus text, old names, missing pins, balanced corruption, missing fallback, source-byte preservation and idempotence. |
| File-by-file writes and validation after publication could leave mixed or invalid output and overwrite a previous good conversion. | `converter.py` stages a whole conversion; `publication.py` backs up files, journals publication, rolls back failures and writes completion metadata last. | Symbol/mod/credits/manifest/pre-publish/publication failures; an actual subprocess `os._exit()` during replacement; failed rollback recovery; failed validation and successful retry. |
| Migration could affect an unrelated converter-owned library placed in the component folder. Hand edits and attribution needed preservation. | Verify paired symbol UUID before migrating older names. Keep unassociated libraries with a manual-cleanup warning. Preserve changed legacy/edited library bytes and previous credits in hash-suffixed files. | Foreign UUID, unrelated generator, edited/truncated libraries, source/fallback cache bytes, existing model files and user files remain preserved. |
| Malformed electrical records were caught and skipped like decorative graphics. | `converter.py` fails a component for invalid pins, pads, holes, vias and known copper geometry. `geometry.py` rejects invalid point lists; `footprint.py` rejects invalid physical dimensions. | `test_electrical_safety.py`: one bad record among valid records, unsupported pad shape/layer, invalid points, empty collections, independent batch continuation and all real fixtures. |
| Multi-unit data could yield a successful unit-1-only library, including alongside top-level shapes. | `symbol.py` rejects nonempty `subparts`. Legacy cached partial units cannot skip this rule. | Recognizable, unknown and mixed layouts; empty subparts preserve single-unit behavior; cached partial multi-unit output remains unchanged after rejection. |
| Layer 12 and layers 99/100/101 were assigned arbitrary fabrication semantics. | `footprint.py`: 12 → `Dwgs.User`; 99/100/101 → `User.3/4/5`. Existing 1–8, 10, 13/14 mappings agree with KiCad. | Independent expected mapping table and generated RECT layer checks. Evidence: embedded real layer tables and KiCad's Standard importer. |
| Electrical type 4 was emitted as `power_in`. | `symbol.py` emits `passive`, matching KiCad's Standard importer; unknown types warn and remain unspecified. | Parameterized 0–4, empty, undefined and unknown type cases. |
| Every oval drill used local X for its long axis. A real tall USB-C pad therefore had its horizontal hole turned 90°. Custom polygon vertices also used the wrong inverse rotation. | `footprint.py` follows the longer local pad axis for slots and uses the correct inverse transform for polygon vertices. The ordinary pad rotation sign stays unchanged. | Real 124° asymmetric switch pads and a genuine 270° USB-C slotted pad, compared with source corners/hole centers and native KiCad. Explicitly derived polygon/back-side calibrations compare both native importers. |
| Courtyards could miss outlines/custom vertices, or grow with stale/text-inclusive BBox data. | `bounds.py` uses pads, drills and non-text physical outlines, including actual arc extrema and transformed custom vertices. Add 0.25 mm and round outwards to 0.05 mm. | `test_courtyard.py`: extended lines/circles/arcs/holes, rotated real pads, custom polygons, stale/missing BBox and remote text/documentation. Native fixture imports still pass. |
| Explicit validation returned success without KiCad. Process errors lacked useful distinctions. | `validation.py` fails if unavailable; validates disposable symbol/mod copies, attempts both kinds, reports timeout/execution errors and avoids copying unrelated model/user files. Publication follows successful validation. | `test_validation.py`: both pass, each kind fails independently, missing CLI, timeout, execution failure, unchanged original bytes and native upgrades. |
| A supplied HTTP client could enable redirects despite the converter's policy. NaN Retry-After could suppress normal backoff. | `client.py` disables redirects per request and retains normal backoff for NaN. | Redirect-following injected client makes exactly one approved-host request; NaN waits 30 seconds. Existing pacing/cap/stop tests still pass. |
| Direct API conversion accepted unsafe response UUIDs. A status-log error could also mislabel an already committed conversion as failed. | Validate UUID before filename construction; reject unsafe manifest/symlink paths. Status-log failures warn separately from conversion success. | Unsafe UUID and symlink cases; failed log after commit preserves success counts and complete output. |

The small strict S-expression reader is local code for inspecting output, not
model interpretation. No upstream importer implementation was incorporated.

## C. Investigated but unchanged

- The 0.254 mm drawing-unit scale and the ESP32 canvas-origin fallback remain
  unchanged. All six original response fixtures remain byte-for-byte unchanged.
- Symbol Y reflection, pin positions/lengths, ordinary pad dimensions and the
  existing cardinal text-angle rules retain their regression coverage.
- Real asymmetric pads confirmed the existing positive serialized pad angle.
  Footprint drawing text keeps its source angle and size. Symbol drawing text
  retains its 75 mil cap; pin labels and Reference/Value remain 1.27 mm.
- MAX98357A keeps all nine pins, including intentionally duplicated numbers.
  Unmatched physical pads remain allowed. Optional decorative records still warn.
- HTTPS host restrictions, sequential requests, the default 4 s plus 0–2 s
  jitter, 1 s minimum, bounded retries, 300 s cap and consecutive 403/429 stop
  behavior are retained. No component API request was used in this audit.
- Source licenses, authors, full descriptions and raw/fallback JSON bytes stay
  preserved. Model files are not deleted; raw SVGNODE metadata stays harmless.
- Launchers keep their shared bootstrap hash, caller-directory handling, UTF-8
  behavior and Windows code-page restoration. No launcher redesign was needed.

## D. Remaining limitations

- Full multi-unit conversion remains unsupported and is now rejected explicitly.
- Genuine custom-polygon and rear-mounted asymmetric source components, offset
  or independently angled slots, and complete footprint-text visual layout
  still need real comparisons. The derived calibration cases are labeled as
  such. KiCad parsing success alone is not physical verification.
- Courtyards are conservative 2D bounds, not IPC, clearance or fabrication
  certification. Rear-side courtyard policy is not newly verified.
- KiCad 8, native Windows CMD and macOS were not executed locally. New remote
  CI results cannot be read because the GitHub API is forbidden here.
- Official EasyEDA documentation hosts denied access. Corrections use KiCad's
  authoritative importer and real source tables/records instead; exact links
  and the reference commit are in `API_NOTES.md`.
- Publication supports rollback and next-run crash recovery, not simultaneous
  writers, an atomic directory swap, or guaranteed recovery from filesystem or
  power failure. A hard kill before journaling can leave unused hidden work
  directories. Retain recovery material while a pending journal exists.
- Unassociated/edited historical libraries may require manual cleanup. Existing
  STEP/WRL files are deliberately retained. New exported libraries are 2D only.

## E. Test results

Local environment: **Python 3.12.14**, pytest 9.1.1, Ruff 0.17.3, Linux,
**KiCad CLI 9.0.2** and native pcbnew build `9.0.2+dfsg-1`.

| Check | Result |
| --- | --- |
| Baseline `python -m pip install -e '.[test]'` | Passed |
| Baseline `python -m pytest -m 'not live'` | 240 passed, 0 failed, 1 skipped, 1 deselected |
| Final `python -m pytest -m 'not live'` | **482 passed, 0 failed, 1 skipped, 1 deselected** |
| Native selection, required CLI/bindings | 18 native cases passed; also included in the final full suite |
| `python -m ruff check .` | Passed |
| `git diff --check` | Passed |
| `python -m pip check` | Passed |
| Isolated wheel build and install | Passed; every packaged Python module matches current source; no model module |
| Installed-wheel offline smoke | Both console aliases work; all six fixtures converted, 12 native validation results PASS; raw bytes preserved and dry run unchanged |
| Actual `run.sh --version` bootstrap/reuse | Passed, including invocation from another directory |
| Remote Ubuntu/Windows Python matrix and new native KiCad job | Configured; results unavailable, not claimed passed |

The one local skip is the native Windows CMD/code-page test. The one deselected
test is the deliberately opt-in live smoke test. Native checks include symbol
and footprint import/upgrade/SVG, cardinal text angles, hidden names, both ESP32
origin regressions and the real/derived pad geometry comparisons.

Wheel smoke tests used cached responses and an unreachable proxy to detect
accidental HTTP use. The initial no-build-isolation packaging probe lacked a
locally installed build backend; the normal declared isolated build succeeded.
No runtime dependency was added to work around that environment condition.

## F. Compatibility

Bare UUIDs/links, `fetch`, `convert`, `--file`, `--output`, `--force`, `--dry-run`,
`--validate`, `--verbose`, `--version`, interactive input and both console aliases
remain. `convert` remains entirely offline. Cached dry runs remain offline even
with `--force`; no dry run changes the output directory or its log/metadata.

Intentional safety changes: malformed essentials and nonempty multi-unit data
now fail; explicit validation requires real KiCad; completion is checked more
carefully; old model references migrate offline when ownership is known. Failed
replacement keeps previous libraries/cache. New source downloads remain cached
for a later offline retry. `--force` refreshes source only upon successful commit
when replacing an existing cache. Log-write problems warn without falsely
reporting a committed conversion as failed.

Generated layer/type, polygon/slot and courtyard corrections are documented
above. Symbol/footprint names retain the title plus UUID suffix and matching
Footprint property. Format targets remain KiCad 8/9; only 9 was executed locally.

## G. Definition-of-done checklist

| # | Requirement | Status | Evidence / scope |
| --- | --- | --- | --- |
| 1 | No 3D feature reintroduced | PASS | No model host, downloader, flag, dependency or attachment workflow |
| 2 | New footprints contain no model references | PASS | Source metadata tests and offline legacy migration |
| 3 | Old 3D outputs migrate safely or receive instructions | PASS | UUID-associated migration; unassociated files warned and preserved |
| 4 | Failed conversions are not complete | PASS | Stage checks, hashes, journal, injected failure tests |
| 5 | Existing valid output survives failed replacement | PASS | Rollback, failed validation, actual process exit and recovery |
| 6 | Dry runs do not persist changes | PASS | Complete, partial, legacy and pending-journal snapshots |
| 7 | Malformed essential electrical data cannot silently disappear | PASS | Fatal record policy, empty/count checks, retained duplicate/unmatched cases |
| 8 | Multi-unit limitations explicit | PASS | Reject nonempty subparts, including old partial cached output |
| 9 | Layers checked against authoritative references | PASS | KiCad importer plus real source layer tables; official docs access limitation recorded |
| 10 | Verified rotation/slot/pin issues corrected | PASS | Real switch/USB-C geometry, labeled derived polygon cases and type table |
| 11 | Unverified conventions documented honestly | PASS | Section D and API notes |
| 12 | Courtyards reasonably safe in tested cases | PASS | Physical geometry bounds and native fixture checks; no compliance claim |
| 13 | Explicit validation fails when unavailable | PASS | Nonzero workflow results; originals preserved |
| 14 | Practical native integration CI | PARTIAL | Job added and its 18 tests passed on native 9 locally; new remote 8-series job not observed |
| 15 | Existing fixtures still work | PASS | All six fixtures; installed-wheel offline smoke too |
| 16 | Changes have regression tests | PASS | 242 more passing cases than baseline |
| 17 | README/API notes reflect implemented behavior | PASS | Migration, failure recovery, strict validation, source conventions and limits |
| 18 | Offline suite and Ruff pass | PASS | 482 passed; Ruff clean |
| 19 | No unrelated architecture/heavy features | PASS | Existing CLI/modules retained, stdlib safety helpers, unchanged runtime dependencies |

Additional verification: **BLOCKED** for remote CI status/PR creation (GitHub
API forbidden); **PARTIAL** for complete rear/custom/slot/text physical coverage
and native Windows/macOS/KiCad 8 execution. These are not marked as passed.

## H. Recommendation

Ready for review as a lightweight **2D release candidate**. Require the new
native KiCad job and existing Windows/Python matrix to turn green before making
broader KiCad 8/Windows release claims. Users must still review converted
connectivity and physical geometry. This audit does not establish electrical
design correctness or manufacturing suitability.
