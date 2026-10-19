# Known limits

These limits apply to the current development branch; the capability matrix
marks features not yet released in 0.2.1.

## Additive comparison, removals and renames

The engine checks whether the database can host the model. Extra database
objects remain. `allow_removals=True` enables the implemented DROP COLUMN handler;
it does not delete tables, schemas, indexes, relations, constraints or extensions.
Column drops can fail on dependencies and do not perform an automatic cascade.
Table and column renames are not inferred: a new name is treated as an addition,
and opting into removals can lose data. Index/constraint names are normally
ignored when structural identity matches. Use a deliberate external migration
for renames and unsupported schema transformations.

## Execution and concurrency

Database creation is separate from the target DDL transaction. PostgreSQL,
SQLite and SQL Server roll back the target DDL unit on failure; a newly created
database/file can remain. MySQL DDL can commit implicitly and reports best-effort
execution. Back up data and review destructive conversions before applying.

A `plan_id` detects drift between review and execution, but does not lock other
DDL writers. Coordinate migrations at the application/deployment level. The
post-apply `verified` flag reports convergence, not a rollback if verification
finds residual changes. Replan and review before retrying after a failure.

## SQLite

`main` uses the configured database file. Other schemas use sibling files
`<schema>.db`, as GenroPy legacy; there is no `main.db`. A missing folder of
the main file is created with the database. The 0.2 layout `<stem>_<schema>.db`
is not read. Temporary/in-memory layouts are not part of the file-based facade contract.

New tables can declare same-schema foreign keys and composite UNIQUE constraints
in the development branch. Additions or changes to those constraints on existing
tables require a table rebuild, which the engine does not implement; this
includes changing the deferral of an existing foreign key. CHECK and cross-file
foreign keys remain unsupported. Do not
suppress skipped-operation errors to create an unconstrained schema.

SQLite PRAGMAs do not expose FK names or deferral clauses. The reader represents
FK columns, target and actions, with structural names, and recovers deferral
from the stored `CREATE TABLE` text. Standalone unique indexes also have
limited introspection fidelity; prefer declared UNIQUE constraints for uniqueness.
Declared type mapping is not a full SQLite affinity equivalence system. New
columns use the GenroPy legacy names (`character varying`, `character`,
`timestamp`); the 0.2 names (`varchar`, `char`, `timestamp without time zone`)
are read as the same dtypes. Legacy `TIMESTAMP` is recognized as `DH`; this does not imply arbitrary type aliases are
interchangeable. SQLite integer primary keys should use `I`, not `serial`.

## PostgreSQL SERIAL4 and SERIAL8

`dtype="serial"` continues to mean BIGSERIAL/SERIAL8. The development branch
adds `dtype="serial4"` for PostgreSQL's 32-bit integer with a sequence-backed
default. New tables create SERIAL4 keys; existing integer columns with a
`nextval(...)` default are read as `serial4`. Planning/applying the matching
model preserves values, sequence ownership/name/options/current position,
defaults and dependent constraints without DDL.

Legacy `I` declarations can still adopt existing SERIAL4 columns without changing
them. An `I` declaration on a fresh database remains a plain integer without
auto-generation. A plain integer without a sequence default is not SERIAL4.
The new declaration is PostgreSQL-only and cannot override `size` or `sqldefault`.
This feature is unreleased after 0.2.1 and requires the coordinated Asqueel grammar
update when used through `AsqueelDb`.

Automatic conversions to/from `serial4` are rejected, including empty columns
and `force`/`backup` modes; adopting SERIAL4 as `I` is the compatibility exception.
The separate [issue #27](https://github.com/asqueel-org/asqueel-migration/issues/27)
tracks the explicit SERIAL4-to-SERIAL8 upgrade preserving sequences and
constraints. Changing the declaration to `serial` is not an upgrade procedure.

## PostgreSQL initial public schema

Creating a missing database whose desired model includes `public` can attempt
`CREATE SCHEMA public` after PostgreSQL already created it. Pre-create the target
database before planning, or use a dedicated application schema. This is an
existing engine limitation, not addressed by the SQLite changes.

## Other contract boundaries

Views, routines, table triggers, custom types and standalone sequences remain
design proposals. Event trigger creation is not implemented even though the
structure can represent it. The CLI drives PostgreSQL through `SqlMigrator` and
does not yet accept a reviewed `plan_id`; use `plan_migration`/`apply_migration`
for strict unsupported-operation rejection. XML parsing does not execute XSD
validation automatically. The HTTP/MCP server is in Asqueel DB Manager.
