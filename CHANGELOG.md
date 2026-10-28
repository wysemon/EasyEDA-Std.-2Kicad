# Changelog

## 1.4.1 — 2026-10-28

- Publish the corrected README to PyPI, including the clickable inspiration credit and the pip-first Windows and Linux/macOS quick starts.
- Update package/runtime versions, website release labels and version-specific documentation links together.
- Keep converter behavior, CLI options, source preservation, cache safety and request pacing unchanged. Compatibility remains Python 3.11+ and KiCad 8/9/10; exports remain strictly 2D.

## 1.4.0 — 2026-10-28

- Prepare the first production PyPI distribution under the package name `euc2k`, with `euc2k` as its sole console command and `python -m euc2k` as the module entry point.
- Add an artifact-validation and Trusted Publishing workflow. PyPI and GitHub use the same validated wheel and source distribution; publishing requires successful tests and an authorized PyPI publisher.
- Update installation instructions, package links and website release labels to 1.4.0. Make README image and documentation links work when displayed on PyPI. Correct stale descriptions of cache ownership and rebuilding.
- Include the website work added since 1.3.0: OS-specific setup, opt-in validation instructions, separate core/native test counts, and the ATMEGA16U2 source/output screenshot gallery.
- Preserve conversion geometry, CLI options, cache identity checks, source bytes, atomic writes and rollback, duplicate pins, request pacing and the 403/429 stop rule. No new converter geometry support is introduced.

Compatibility remains Python 3.11+ and KiCad 8/9/10 output. Exports remain strictly 2D. Native KiCad verification runs on Linux; manual GUI comparisons and native KiCad on Windows/macOS remain outside the automated native matrix. Review component geometry, drills and connectivity before fabrication.

Earlier release notes: [1.3.0](https://github.com/wysemon/euc2k.py/releases/tag/v1.3.0).
