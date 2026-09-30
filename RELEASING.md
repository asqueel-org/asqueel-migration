# Release Asqueel Migration

Distribution: `asqueel-migration`. Python package: `asqueel_migration`.
Repository: `asqueel-org/asqueel-migration`. Prepared version: `0.1.2`. The retained historical tags `v0.1.0` and `v0.1.1`
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

The manual `publish.yml` workflow builds, validates and smoke-tests both artifacts;
it uploads to PyPI only when the selected ref is a matching `v*` version tag.
Do not create the release tag until the publisher configuration and release
contents have been reviewed. Uploaded PyPI files cannot be replaced in place.

Publish **asqueel-migration first**. Asqueel's `migration` and `dev` extras depend
on its public distribution. Before that first migration release, Asqueel CI uses
an explicit source revision for the migration dependency; wheel metadata keeps
the normal `asqueel-migration>=0.1.2` requirement.

No PyPI upload is performed by the rename itself. Read the Docs project/account
configuration is independent of the checked-in Sphinx configuration.
