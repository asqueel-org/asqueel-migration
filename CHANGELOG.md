# Changelog

## Unreleased

- Prepare 0.2.0: move the Kajenn HTTP/MCP application to the separate
  `asqueel-dbmanager` distribution. The `app` extra and
  `asqueel_migration.app.EditorApp` are removed; Python migration and XML
  service operations remain in this package.
- Accept normalized JSON documents or dictionaries as `SqlMigrator(...,
  structure=...)`; isolate caller data and repeat dialect filtering from an
  independent source snapshot. Legacy `ormStructure` assignment also copies
  input; changing its working dictionary does not change the source snapshot.
- Add transport-independent `plan_migration` and `apply_migration`, with
  reviewed-plan validation, unsupported-operation rejection and convergence
  verification. Plan identifiers detect drift; they do not lock external DDL.

- Quote identifiers consistently in migration DDL, introspection and conversion
  backup commands, including names containing double quotes. Primary-key columns,
  primary-key constraint names and PostgreSQL extension names are now quoted in
  generated SQL. SQLite schema attachment also handles quoted aliases and paths
  containing apostrophes (#16).

## 0.1.2 (unreleased)

- Rename the distribution, Python package and CLI to Asqueel Migration.
- Retain all fixes from 0.1.1; prepare GitHub Trusted Publishing for the new name.

## 0.1.1 — 2026-09-29

- Preserve added and changed columns before primary-key rebuilds, retaining
  dialect-specific SQL assembly (#10, #12; legacy genropy/genropy#1194).
- Normalize legacy varchar min:max sizes in JSON and XML producers so
  repeated schema comparisons converge after migration (#11, #13).
- Align regression coverage with legacy develop, including varchar widening
  on primary-key columns, and document intentional test exclusions.

## 0.1.0 — 2026-09-29

First public Alpha release.

- Compare normalized database schemas and generate additive migrations for
  PostgreSQL, SQLite, MySQL and SQL Server, with JSON and XML producers.
- Apply DDL atomically where supported; MySQL reports best-effort execution.
- Preserve authored index names and PostgreSQL descending column order.
  Quote and escape index identifiers and handle schema-aware index rebuilds
  and dialect-specific renames (issues #8 and #9).
- Offer an optional localhost-only HTTP/MCP editor built on Kajenn 0.1.
  Applying migrations remains REST-only.

The API is still evolving. Renames are not inferred and database-only objects
are retained by default. See the producer guide for dialect limitations.
