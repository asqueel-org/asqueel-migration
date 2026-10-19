# Changelog

## 0.3.0 — unreleased

- **Breaking (SQLite):** attached schemas use `<folder of the main file>/<schema>.db`,
  as the GenroPy legacy SQLite adapter. The 0.2 layout `<stem>_<schema>.db` is no
  longer read: rename existing schema files before upgrading.
- Create the missing folder of the SQLite main file when the database is created.
- Write the GenroPy legacy SQLite type names: `A` → `character varying`,
  `C` → `character`, `DH` → `timestamp`, `X` → `blob` (`DHZ`, `H` unchanged).
  Sizes keep their form (`character varying(n)`, `character(n)`, `numeric(p,s)`).
- Read both the legacy names and the 0.2 names (`varchar`, `char`,
  `timestamp without time zone`) as the same dtype: tables written by 0.2 show
  no differences after the upgrade.

## 0.2.3 — 2026-10-18

- Create SQLite foreign keys with `DEFERRABLE` / `INITIALLY DEFERRED` on new
  tables, following the PostgreSQL writer: `initially_deferred` applies only
  together with `deferrable`. A self-referencing deferred FK lets a child row be
  inserted before its parent inside one transaction.
- Read SQLite FK deferral from the stored `CREATE TABLE` text, in table-constraint
  and column-constraint form, so a deferred FK converges on the next plan.
  Changing the deferral of an existing FK remains a gated table rebuild.

## 0.2.2 — 2026-10-15

- Remove column UNIQUE using the actual constraint and index names from the
  database catalog, following GenroPy #1425. Qualify standalone index drops by
  schema, remove all objects enforcing that column's uniqueness, and preserve
  ordinary indexes. Repeated preparation converges and duplicate values are
  accepted after the removal.
- Recognize simple single-column UNIQUE indexes as column uniqueness while
  preserving explicitly declared index names, ordering and options. Partial,
  expression and multi-column indexes retain their separate semantics.

- Add PostgreSQL `serial4` declarations across JSON/XML contracts, SQL generation
  and introspection. Preserve existing SERIAL4 sequences/data and legacy `I`
  adoption; retain `serial` as SERIAL8. Refuse implicit SERIAL4 conversions (#25);
  explicit SERIAL4-to-SERIAL8 migration is tracked separately in #27.

- Fix SQLite `main` migration to use the configured file and recognize legacy
  `TIMESTAMP` declarations without changing stored data (#20, #22).
- Create and introspect same-schema foreign keys and composite UNIQUE constraints
  on new SQLite tables; reject unsupported existing-table changes (#21, #24).
- Expose `SqlMigrator.skipped` and plan `skipped_changes` as structured omissions,
  preserving warning strings and legacy plan `skipped` (#15).
- Make mypy blocking, document gradual typing enforcement, use a single Hatch
  version source, complete the `all` extra and validate release artifacts on PRs
  (#4, #5).
- Publish a dialect matrix, known limits and current milestone status (#2).

## 0.2.1 — 2026-10-12

- Use the connection's database name for creation even when the desired
  structure carries a different model label.
- Reject missing service inputs before database access, and report malformed
  containers as validation errors with field paths, with or without the
  optional JSON Schema validator.
- Expand contract coverage for reviewed plans, input ownership, repeatable
  preparation, unsupported operations, removals and connection cleanup.
- Refresh internal architecture and usage documentation for caller-supplied
  schemas and the extracted server application. Annotate conversion tables and
  capabilities, and include the development typing dependencies needed for a
  clean mypy run without suppressing import diagnostics.

## 0.2.0 — 2026-10-12

- Move the Kajenn HTTP/MCP application to the separate
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

## 0.1.2

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
