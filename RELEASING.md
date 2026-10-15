# Release Asqueel Migration

Distribution: `asqueel-migration`. Python package: `asqueel_migration`.
Repository: `asqueel-org/asqueel-migration`. Release version: `0.2.2`.
The single version source is `src/asqueel_migration/__init__.py`; Hatch reads it
for both wheel and source archive. See [CHANGELOG.md](CHANGELOG.md).
The retained historical tags `v0.1.0` and `v0.1.1`
belong to the former distribution and must not be moved or reused.

## One-time PyPI setup

While signed in as the intended PyPI owner, open
[Publishing](https://pypi.org/manage/account/publishing/) and add a pending GitHub
publisher with these exact values:

| Field | Value |
|---|---|
| PyPI project name | `asqueel-migration` |
| GitHub owner | `asqueel-org` |
| Repository | `asqueel-migration` |
| Workflow filename | `publish.yml` |
| GitHub environment | `release` |

A pending publisher does not reserve a project name. The first successful upload
creates the project. The repository must have a `release` environment matching this
configuration. No API token is required. See the official
[Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Verify before publishing

Run the test suite, build documentation, then run:

```sh
python -m build
python -m twine check --strict dist/*
python scripts/check_distribution.py dist/*
```

Install the built wheel in a fresh environment with the `dev`, `postgresql`
and `validation` extras. Run the tests from the matching source archive, with
`PYTHONPATH` unset, and verify that `asqueel_migration.__file__` points into the
environment's `site-packages`. Run `pip check`, Ruff and mypy as well.
For PostgreSQL regressions, use the disposable server selected by
`GNR_TEST_PG_HOST`, `GNR_TEST_PG_PORT`, `GNR_TEST_PG_USER` and
`GNR_TEST_PG_PASSWORD`, or the existing `testing.postgresql` fixture.

For 0.2.2, `tests/test_legacy_unique_removal.py` must pass against the installed
wheel: real constraint/index names, schema-qualified index removal, preserved
ordinary indexes, explicit unique indexes, convergence and accepted duplicates.
Do not certify these checks against published 0.2.1, which lacks the fix.
Also verify Asqueel's native and hierarchical migration JSON against this wheel,
without importing either project's source tree. Record unavailable dialects
and skipped tests separately from successful checks.

Ensure the UNIQUE changes and regression tests are tracked before tagging.
Untracked files may enter a local build but are absent from a fresh CI checkout.

The manual `publish.yml` workflow builds, validates and smoke-tests both artifacts;
it uploads to PyPI only when the selected ref is a matching `v*` version tag.
Do not create the release tag until the publisher configuration and release
contents have been reviewed. Uploaded PyPI files cannot be replaced in place.

Publish **asqueel-migration first**, once release is authorized. Asqueel's
`migration` and `dev` extras depend on its public distribution. Once 0.2.2 is
available from PyPI, update the consumer's minimum version and CI pins as
appropriate and repeat installation without the migration checkout or a local
wheel. A local 0.2.2 artifact proves preparation, not publication.

Building and checking artifacts does not publish them. Read the Docs project/account
configuration is independent of the checked-in Sphinx configuration.

## Local 0.2.2 candidate verification — 2026-10-15

- Installed wheel, with imports verified under the isolated environment:
  **581 tests passed**, including the 13 UNIQUE regressions; 12 MySQL/MSSQL
  cases skipped because Docker was unavailable, and 5 explicitly deferred cases.
- Consumer Asqueel 0.6.0 wheel: **235 tests passed**, covering the native and
  hierarchical invoice JSON, PostgreSQL application/convergence and SERIAL4.
  Neither package was imported from its checkout.
- Ruff, mypy (32 source files), `pip check`, strict Twine metadata checks and
  packaged-contract checks passed. Documentation built with warnings treated as
  errors and the external Python intersphinx inventory disabled for offline use.

These are local artifact checks, not a claim that remote CI has run or that
0.2.2 has been published. MySQL and MSSQL still require their integration jobs.
