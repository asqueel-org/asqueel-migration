# Dialect capabilities

This page describes the current development branch. The SQLite `main`, legacy
`TIMESTAMP`, fresh-table foreign key and composite UNIQUE fixes are **unreleased**;
0.2.1 does not include them. See the changelog before adopting these features.

The tables describe the migration engine, not everything the database itself
supports. **I** = introspect, **C** = create, **A** = alter an existing object,
**D** = remove a database-only object from the desired model. A dash means no
implemented migration path. Column removal requires `allow_removals=True`.
Explicit rebuilds of an index or constraint can drop the old object even though
standalone removal is not implemented.

## PostgreSQL

| Entity | I | C | A | D |
| --- | --- | --- | --- | --- |
| Database | Existence | Yes | — | — |
| Schema | Yes | Yes | — | — |
| Table | Yes | Yes | Columns, PK, constraints, indexes, comments | — |
| Column | Yes | Yes | Type/size, default, nullability, uniqueness, comment | Opt-in |
| Primary key | Yes | Yes | Rebuild | — |
| Foreign key | Yes | Yes | Rebuild | — |
| UNIQUE / CHECK | Yes | Yes | Rebuild | — |
| Index | Yes | Yes | Rename or rebuild | — |
| Extension | Yes | Yes | — | — |
| Table/column comment | Yes | Yes | Replace | — |
| Event trigger | Yes | — | — | — |
| View, routine, table trigger, custom type, standalone sequence | — | — | — | — |

Foreign key deferral and index method, predicate, tablespace and storage options
are represented. Type conversion depends on the conversion matrix and existing
data; `force`/`backup` can be destructive. `serial` means 64-bit BIGSERIAL; see
[the SERIAL4 limitation](known_limits.md).

## SQLite

| Entity | I | C | A | D |
| --- | --- | --- | --- | --- |
| Database | File existence | File creation | — | — |
| Schema | `main` or attached file | `main` already exists; other schemas attach files | — | — |
| Table | Yes | Yes | Add columns/indexes; selected index rebuilds | — |
| Column | Declared types, defaults, nullability | Yes | Add; type/default/nullability changes unsupported | Opt-in, subject to SQLite restrictions |
| Primary key | Yes | With table | — | — |
| Foreign key | Yes | With table, same schema | — | — |
| Composite UNIQUE | Yes | With table | — | — |
| Single-column UNIQUE | Yes | With table/column | Adding/removing uniqueness on an existing column unsupported | — |
| CHECK | — | — | — | — |
| Index | Columns and predicate; unique-index fidelity limited | Yes, including partial indexes | Rebuild; unique-index fidelity limited | — |
| Comments, extensions, event triggers, extended entities | — | — | — | — |

Foreign keys are inline in `CREATE TABLE`, enforced on connections opened by
this library, and read through `PRAGMA foreign_key_list`. UPDATE/DELETE actions
and composite references round-trip. Cross-attached-file foreign keys and
requested deferral options are rejected by reviewed apply. Constraint names are
not recovered by SQLite PRAGMAs; use the default `ignore_constraint_name=True`.
No automatic table rebuild is implemented. `TIMESTAMP` maps to `DH` without
rewriting a legacy column. Use dtype `I` for SQLite integer primary keys.

## MySQL and SQL Server

| Entity | MySQL I / C / A / D | SQL Server I / C / A / D |
| --- | --- | --- |
| Database/schema | Yes / Yes / — / — | Yes / Yes / — / — |
| Table | Yes / Yes / columns and constraints / — | Yes / Yes / columns and constraints / — |
| Column | Yes / Yes / type, default, nullability, uniqueness / opt-in | Yes / Yes / type, default, nullability, uniqueness / opt-in |
| Primary key | Yes / Yes / rebuild / — | Yes / Yes / rebuild / — |
| Foreign key | Yes / Yes / rebuild / — | Yes / Yes / rebuild / — |
| UNIQUE / CHECK | Yes / Yes / rebuild / — | Yes / Yes / rebuild / — |
| Index | Yes / Yes / rename or rebuild / — | Yes / Yes / rename or rebuild / — |
| Comments, extensions, event triggers, extended entities | — / — / — / — | — / — / — / — |

Both dialects reject requested FK deferral and unsupported index options. SQL
Server supports filtered indexes; MySQL does not. Type conversions have no
PostgreSQL-style conversion expressions and may require a destructive fallback.
The CI integration suites exercise both backends; they are not SQLite substitutes.

## Interpreting a plan

`empty` only means no SQL was generated. Inspect `skipped_changes` for structured
omissions (`capability`, `context`, `warning`); legacy `skipped` remains a list of
warning strings. `apply_migration` refuses any recorded unsupported change before
DDL. Database-only objects retained by the additive contract are not omissions.
See [known limits](known_limits.md) and [test setup](maintenance.md).
