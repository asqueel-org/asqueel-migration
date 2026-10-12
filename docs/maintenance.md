# Development, typing and releases

## Test environments

Install `.[dev,postgresql]`, then run:

```bash
python -m ruff check src tests
python -m mypy src/asqueel_migration
python -m pytest -m "not postgresql and not mysql and not mssql"
```

SQLite tests use temporary files and the standard-library driver. PostgreSQL
integration tests use `testing.postgresql` and installed `initdb`/`postgres`
binaries, or a server configured with `GNR_TEST_PG_PASSWORD`, `GNR_TEST_PG_HOST`,
`GNR_TEST_PG_PORT` and `GNR_TEST_PG_USER`. Tests create disposable databases.

```bash
python -m pytest -m postgresql
python -m pip install -e ".[dev,mysql,mssql]"
python -m pytest -m "mysql or mssql"
```

MySQL and SQL Server fixtures start Docker containers and skip when Docker is
unavailable. Their CI jobs run real integrations. A local skip is not a backend
validation result. See `tests/conftest.py` and the dialect integration fixtures
for exact connection settings. Five dormant feature tests remain intentionally
skipped until their functionality exists.

## Typing policy

Ruff and mypy are blocking CI checks. Conversion and capability collections have
explicit annotations. `dev` installs JSON Schema/PyMySQL stubs and pymssql's
bundled Python 3 stubs; the targeted dictdiffer override follows its untyped
installed source instead of globally suppressing missing imports.

The migration toward `disallow_untyped_defs` is incremental:

1. `_sql` is already enforced with `disallow_untyped_defs` and body checking.
2. Annotate contract factories and exception types, retaining public signatures,
   then add those modules to the strict override after their consumer tests pass.
3. Define typed adapter/reader protocols and diff events; tighten the service,
   orchestrator and mixins one module at a time.

New code in an enforced module must be fully annotated. A broader typing change
must run producer/consumer contract tests and cannot introduce blanket ignores
or weaken the existing CI gate.

## Documentation checks

```bash
python -m pip install -e ".[docs]"
python -m sphinx -E -b html -W --keep-going docs /tmp/asqueel-docs-html
python -m sphinx -b linkcheck -W docs /tmp/asqueel-docs-links
```

Both checks run in CI. Internal handoff documents are excluded from the published
site and source distribution. The roadmap distinguishes current delivery from
historical design proposals; the capability and known-limit pages describe the
supported public surface.

## Release checklist

1. Run tests, Ruff, mypy, documentation checks and consumer compatibility checks.
2. Update `__version__` in `src/asqueel_migration/__init__.py` (the sole version
   source), the changelog and any version-specific guide text. Hatch reads this
   source directly; `pyproject.toml` declares a dynamic version.
3. Build with `python -m build`; run `python -m twine check --strict dist/*` and
   `python scripts/check_distribution.py dist/*`. The latter verifies JSON/XSD
   contracts, `py.typed`, dependency metadata, and tag/version agreement for tag
   builds.
4. Install and import each wheel and sdist in separate clean virtual environments.
   Confirm `asqueel_migration.__version__` equals installed package metadata.
5. Review and merge the release change, then create the matching `v<version>` tag
   only when a release is authorized. The tag workflow repeats validation and
   publishes through Trusted Publishing. PR builds only validate artifacts.
6. Verify published artifacts and the documentation build. Read the Docs `latest`
   follows main; `stable` follows the released version.

The `all` extra includes dev/docs, all three optional database drivers and JSON
Schema validation. SQLite needs no driver extra. HTTP/MCP dependencies belong to
the separate DB Manager distribution.
