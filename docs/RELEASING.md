# Releasing euc2k.py

Production package: [euc2k on PyPI](https://pypi.org/project/euc2k/).
Workflow: `.github/workflows/publish.yml`. GitHub environment: `pypi`.

## One-time PyPI authorization

The repository's GitHub permissions do not grant access to PyPI. A PyPI account
owner must authorize this workflow using Trusted Publishing. No token belongs in
the repository or its documentation.

For a first publication, sign in to production PyPI and open
[Publishing settings](https://pypi.org/manage/account/publishing/). Add a pending
GitHub publisher with these exact values:

| Field | Value |
| --- | --- |
| PyPI project name | `euc2k` |
| Owner | `wysemon` |
| Repository | `euc2k.py` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

If the project already exists, an authorized project owner adds the publisher in
the project's Publishing settings instead. If the name belongs to someone else,
stop: do not change the package name or upload to a different destination.
Any required GitHub environment approval must also be completed by its reviewer.

## Prepare and validate

PyPI displays the README stored in the uploaded package metadata. Later edits on
`main` do not change a published release's description. Finalize and preview the
README before tagging; corrections after publication require a new version.
Never replace an existing release's artifacts or tag to update its README.

1. Check the working tree and remote, existing Git tags/releases and production
   PyPI. Stop if the intended version already exists or ownership is uncertain.
2. Prepare a release branch. Update `pyproject.toml`, `src/euc2k/__init__.py`,
   `CHANGELOG.md`, README package links and website labels/instructions together.
   Keep historical entries, dependency versions, format versions and API editor
   versions unchanged. Keep unpublished installation links off the live site by
   promoting the branch only after publication succeeds.
3. Install the updated project, run the full offline suite and Ruff, and build:

   ```sh
   python -m pip install -e '.[test]' build twine
   python -m pytest -m "not live"
   python -m ruff check .
   python -m ruff format --check .
   python -m build
   python -m twine check --strict dist/*
   ```

4. Inspect both archives. Confirm all runtime modules and the MIT license are in
   the wheel. The source distribution must also include fixtures, their separate
   license/provenance, launchers, documentation and release tooling. Check for
   credentials, caches and unintended files.
5. Install the wheel into a clean environment, run `pip check`, version/help and
   interactive commands, then run `scripts/verify_dist.py` using that environment's
   Python with `--version` and `--fixtures` pointing to this checkout's fixtures.
   Verify the source distribution can build/install independently too.
6. Test the website on desktop/mobile, review the diff, and commit with a message
   such as `Release v1.4.1`. Push the release branch without force-pushing. Wait
   for all seven CI jobs, including the KiCad 8/9/10 matrix.

## Publish and deploy

Create an annotated version tag on the verified release commit and push it.
`publish.yml` requires a version-matched tag and successful tag CI. It builds
and checks wheel/sdist, tests the wheel in a clean environment, records checksums
and uploads those exact artifacts for the publishing jobs. Only the PyPI job
receives `id-token: write`, scoped to environment `pypi`. The official
`pypa/gh-action-pypi-publish` action uploads to production PyPI. No password is used.

After PyPI succeeds, the workflow creates a public, latest stable GitHub release
with those same distributions and their checksums. Publishing is tag-triggered
only; a GitHub release event does not upload a second copy. Manual dispatch must
select the existing release tag, not a branch. An existing PyPI version is an
error, not a reason to skip or overwrite it.

If publishing is blocked by `invalid-publisher`, finish the PyPI authorization
above, then use **Re-run failed jobs** on the existing workflow. That reuses the
validated build artifacts. Do not delete/recreate the tag or invent a new
version. After a partial success, rerun only failed jobs to avoid duplicate
uploads. Inspect the production release before any retry.

After both destinations succeed, fast-forward `main` to the tagged release
commit and push normally. This deploys `/docs` through the existing GitHub Pages
workflow. If unrelated commits have reached `main`, stop and review rather than
force-pushing. Verify the live site, release links and PyPI installation after
Pages completes. A successful local website preview is not a live deployment.
