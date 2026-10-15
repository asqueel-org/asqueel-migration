# Producer Guide — describing your database

**Library**: 0.2.1 · **Structure contract**: `format_version = "1.0"`

asqueel-migration is ORM-agnostic: it never reads your model. You
describe the desired database in one of three input formats, the
library compares it against the live database and generates (or
applies) the realignment SQL.

The three doors, from the friendliest to the most technical:

1. **Human JSON** — a readable JSON document with names and lists
   (no hashes). Compiled by `JsonStructureProducer`.
2. **XML** — the same information in XML, described by the packaged
   XSD (`sql_model-1.0.xsd`); ideal for editors and GUIs. Compiled by
   `XmlStructureProducer`.
3. **Normalized JSON** — the internal contract itself, built with the
   `new_*_item` factories. For producers that need full control
   (e.g. an ORM extractor).

The two external formats are equivalent: the same model expressed in
human JSON or XML compiles to the identical internal structure. Both
compilers are thin front-ends over the same factories, so every
normalization rule below applies to both.

## Compatibility is additive

The migration check answers a compatibility question: **can this database host
the application without further additive changes?** It does not certify that
the live database and the model are structurally identical.

Objects that exist only in the database are therefore compatible and are
preserved by default. A successful check may coexist with legacy tables,
columns, indexes or constraints that the application model does not mention.
The model's root database name is descriptive metadata; the connection selects
the actual target database.

Renames are not inferred. Without an explicit rename syntax, a producer must
not expect a remove/add pair to be interpreted as a rename. Likewise, no DROP
is implied by the compatibility check.

## 1. End-to-end quickstart (human JSON)

```python
from asqueel_migration import (
    JsonStructureProducer, PgDatabase, plan_migration, apply_migration,
)

model = {
    "db": "mydb",
    "schemas": [
        {
            "name": "library",
            "tables": [
                {
                    "name": "author", "pkey": "id",
                    "columns": [
                        {"name": "id", "dtype": "serial"},
                        {"name": "name", "dtype": "A", "size": "0:120",
                         "notnull": True},
                    ],
                },
                {
                    "name": "recipe", "pkey": "id",
                    "columns": [
                        {"name": "id", "dtype": "serial"},
                        {"name": "title", "dtype": "A", "size": "0:80",
                         "notnull": True},
                        {"name": "author_id", "dtype": "L"},
                    ],
                    "relations": [
                        {"columns": ["author_id"],
                         "related_schema": "library",
                         "related_table": "author",
                         "related_columns": ["id"],
                         "on_delete": "CASCADE"},
                    ],
                    "indexes": [{"columns": ["title"]}],
                },
            ],
        },
    ],
}

structure = JsonStructureProducer(model).get_json_struct()

db = PgDatabase({"dbname": "mydb", "host": "localhost"},
                application_schemas=["library"])
try:
    plan = plan_migration(db, structure)
    print(plan["sql"])
    print(plan["warnings"])
    print(plan["plan_id"])           # retain the identifier of the reviewed plan

    # Only after reviewing the SQL and warnings:
    # result = apply_migration(db, structure, expected_plan=plan["plan_id"])
    # print(result["verified"], result["remaining"])
finally:
    db.closeConnection()
```

`JsonStructureProducer` also accepts a JSON string or a file
(`JsonStructureProducer.from_file(path)`). Compile the human JSON before
passing it to the migration API: `plan_migration` and `apply_migration` accept
**normalized** dictionaries or serialized normalized JSON, not the human
JSON format. Both functions validate and copy their input. Missing input
(`None`) is rejected before database access.

The example uses a dedicated `library` schema and can create a missing database.
If you target PostgreSQL's `public` schema, create the database before planning:
PostgreSQL creates `public` automatically, while the current new-database path
would also attempt to create it.

Install `asqueel-migration[postgresql]` for this example. The library also
provides `SqliteDatabase`, `MysqlDatabase` and `MssqlDatabase`; MySQL and SQL
Server need their respective driver extras, while SQLite uses the Python
standard library. Models must fit the target dialect: for example, SQLite
models use `I` for integer primary keys rather than PostgreSQL's `serial`,
and unsupported features are reported in the plan.

`StructureValidator().validate()` remains available for explicit validation.
It checks structural and semantic rules, plus the packaged JSON Schema when
the optional `validation` extra is installed. Malformed containers raise
`SqlValidationError` with field paths even without that extra.

### Review a plan, then apply that plan

A plan contains:

| Field | Meaning |
| --- | --- |
| `plan_id` | Fingerprint of the inspected destination, current and desired structures, generated SQL, warnings and removal policy |
| `sql` | Commands proposed for execution |
| `warnings` | Diagnostics, including features the target cannot represent |
| `skipped` | Unsupported features or operations omitted from the plan (legacy strings) |
| `skipped_changes` | Structured omissions: `capability`, `context`, `warning` (unreleased after 0.2.1) |
| `empty` | Whether the generated SQL is empty; check `skipped` as well |

Keep the `plan_id` together with the desired document and removal policy that
were reviewed. The database facade can be closed after planning and recreated
with the same connection and schema settings for application.
`apply_migration(db, structure, expected_plan=reviewed_plan_id)` prepares a new
plan against the live database and compares its fingerprint with that identifier:

- `StaleMigrationPlan` means the identifier is missing or the plan changed.
  Inspect a new plan before retrying; do not silently replace the reviewed ID.
- `UnsupportedMigration` means `skipped` is nonempty. No migration DDL is
  executed, even if part of the proposed SQL is supported. Adjust the desired
  model or target capabilities before planning again.
- On success, `execution` reports the execution mode and completed phases;
  `remaining` contains a fresh post-apply plan. `verified` is true only when
  that residual plan has no SQL and no skipped operations.

`verified=False` does not undo executed statements. An error during post-apply
introspection likewise does not imply rollback of the preceding execution.
The identifier detects changes before execution; it is not a lock and cannot
prevent concurrent external DDL between inspection and execution.

The default `allow_removals=False` preserves database-only objects. Set
`allow_removals=True` for **both** planning and application to enable implemented
removal operations, currently `DROP COLUMN`. It does not enable inference of
renames or whole-table removal.

### Connection ownership

The caller owns database facades passed to `plan_migration`, `apply_migration`
and `SqlMigrator`. Always close them in `finally`, including when planning,
validation, execution or verification raises an error, as in the quickstart.
The functions in `editor_service` instead receive connection parameters, create
their own facades and close them on both success and failure.

### Applying safely and recovering from errors

The underlying `SqlMigrator.applyChanges()` uses one transaction for the
complete DDL unit on PostgreSQL, SQLite and SQL Server. MySQL is explicitly best-effort because DDL
statements can cause implicit commits. The service returns these details in
`result["execution"]`: `atomic`, `best_effort` and `phases_applied`.
Non-atomic execution also adds a warning to `result["warnings"]`.

`CREATE DATABASE`, when required, is executed separately through the manager
connection. It therefore remains present if the following DDL unit fails.

At the first failure execution terminates with `MigrationExecutionError`:

```python
from asqueel_migration import MigrationExecutionError

# Reopen the target and use the identifier retained after review.
reviewed_plan_id = plan["plan_id"]
db = PgDatabase({"dbname": "mydb", "host": "localhost"},
                application_schemas=["library"])
try:
    result = apply_migration(db, structure, expected_plan=reviewed_plan_id)
except MigrationExecutionError as error:
    print(error.phase)
    print(error.rolled_back)
    print(error.partial_state_possible)
    raise
finally:
    db.closeConnection()
```

There is no automatic retry or reanalysis in the failing invocation. After
fixing the cause, call `plan_migration` again, review the residual SQL and use
that new identifier for application. A new plan introspects the actual
database state and shows only the residual additive discrepancy. This is also
the recovery path for MySQL: statements committed before the error are seen as
already present, and the remaining changes are proposed. The migrator does not
infer renames and does not remove extra database objects by default.

| Dialect | Execution guarantee |
| --- | --- |
| PostgreSQL | Transactional generated DDL; rollback on failure |
| SQLite | Transactional on one attached connection; rollback on execution failure. Atomic recovery from a process/host crash across multiple attached files depends on journal configuration |
| SQL Server | Transactional DDL generated by the library; rollback on failure |
| MySQL | Best-effort with warning; partial committed state is possible |

### Server and authored SQL

Since 0.2, HTTP, OpenAPI, MCP, background tasks and backup/restore belong to the
separate [asqueel-dbmanager](https://github.com/asqueel-org/asqueel-dbmanager)
application. The migration library has no bundled server or `[app]` extra.
See the manager's documentation for its deployment and access policies.
The engine continues to support Python 3.10 and newer.

Model fields such as `sql_type`, `sqldefault`, `extra_sql` and CHECK clauses
contain intentional native SQL. Treat model documents as trusted authored
input; identifier quoting and structure validation do not sandbox expressions.

## 2. The human JSON format

Top level:

```text
{
  "db": "<database name>",
  "schemas":        [ {"name": "...", "tables": [ ... ]} ],
  "extensions":     [ "unaccent" ],
  "event_triggers": [ {"name": "audit_ddl",
                       "attributes": {"event": "ddl_command_end"}} ]
}
```

`extensions` and `event_triggers` are optional (PostgreSQL-oriented).

### Table

```text
{
  "name": "recipe",
  "pkey": "id",                  // comma-joined for composite: "a,b"
  "comment": "Recipes",
  "columns":     [ ... ],
  "relations":   [ ... ],        // foreign keys
  "constraints": [ ... ],        // UNIQUE / CHECK
  "indexes":     [ ... ]
}
```

Primary-key handling is automatic: every `pkey` column becomes
`notnull` (`'_auto_'`), and a single-column PK drops a redundant
`unique` on that column.

### Column

```json
{"name": "title", "dtype": "A", "size": "0:80", "notnull": true}
```

Accepted attributes: `dtype`, `size`, `notnull`, `sqldefault`,
`unique`, `sql_type`, `extra_sql`, `generated_expression`, `comment`.
Anything else is ignored. `sql_type` is the native-type escape hatch
(emitted verbatim in the DDL).

If `dtype` is missing: `'A'` when a `size` is present, `'T'`
otherwise.

### Relation (foreign key)

```json
{"columns": ["author_id"],
 "related_schema": "library", "related_table": "author",
 "related_columns": ["id"],
 "on_delete": "CASCADE",              // optional; never emit NO ACTION
 "name": "fk_recipe_author"}          // optional readable name
```

`columns` and `related_columns` are lists — a multi-column FK is just
a longer list (positional pairing). Optional flags: `on_update`,
`deferrable`, `initially_deferred` (emit only when true).

### Constraint

```json
{"type": "UNIQUE", "columns": ["title", "author_id"], "name": "uq_t_a"}
{"type": "CHECK", "name": "ck_recipe_title",
 "check_clause": "(char_length(title) > 0)"}
```

`name` is optional for UNIQUE, **required** for CHECK. Write the CHECK
clause as PostgreSQL prints it (outer parentheses, explicit casts) so
it compares clean against introspection. Single-column uniqueness is
the column attribute `unique`, not a constraint.

### Index

Index names are physical identifiers, not SQL fragments: supply them unquoted.
Writers quote and escape them, preserving case, punctuation and embedded quotes.
The normalized entity key remains the structural hash. PostgreSQL and SQLite
preserve the physical name and each column's descending order on introspection.
Index rebuilds target the existing physical name in its schema/table namespace;
`ignore_constraint_name=True` retains that name even if the producer supplies
another. With `ignore_constraint_name=False`, a name-only change uses native
rename in PostgreSQL/MySQL and a drop/create in SQLite/SQL Server. Removing an
index from the model still does not automatically drop it, except for column
uniqueness as described below.

For column uniqueness, migration follows the legacy rule: an existing
non-partial UNIQUE index on one plain, non-primary-key column enforces the
same `unique: true` as a UNIQUE constraint. When neither column uniqueness nor
an explicit UNIQUE index is requested, migration drops **all** constraints and
indexes enforcing that column's uniqueness, using their actual catalog
names and schema-qualified index names. Partial, expression and multi-column
indexes are not classified as column uniqueness. An explicitly declared UNIQUE
index in the JSON remains an index, preserving its name, ordering and options;
it is not implicitly converted into a column constraint. The input JSON is
not modified during preparation.

```json
{"columns": ["title"]}                              // plain list
{"columns": {"pa": null, "created": "DESC"},        // per-column sort
 "unique": true, "method": "btree",
 "with_options": {"fillfactor": "70"},
 "where": "created > '2020-01-01'",
 "name": "idx_recent"}                              // optional name
```

`columns` is either a list (all default sort) or an ordered map
`name → null | "DESC"`. `with_options` is passed through to the
dialect writer.

### Optional names

An explicit `name` on a relation / UNIQUE / index becomes the entity's
readable SQL name. Internally the entity is always keyed by a
structural hash computed from schema + table + columns — two models
that differ only in names produce the same keys, so renaming never
causes spurious diffs (`SqlMigrator` ignores name differences by
default, `ignore_constraint_name=True`).

## 3. The XML format

The same model, following the packaged XSD (`src/asqueel_migration/schemas/
sql_model-1.0.xsd`, namespace `urn:genro:sql-model:1.0`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<db xmlns="urn:genro:sql-model:1.0" name="mydb">
  <schema name="library">
    <table name="author" pkey="id">
      <column name="id" dtype="serial"/>
      <column name="name" dtype="A" size="0:120" notnull="true"/>
    </table>
    <table name="recipe" pkey="id">
      <column name="id" dtype="serial"/>
      <column name="title" dtype="A" size="0:80" notnull="true"/>
      <column name="author_id" dtype="L">
        <relation to="library.author.id" on_delete="CASCADE"/>
      </column>
      <index columns="title"/>
    </table>
  </schema>
</db>
```

XML-specific notes:

- `XmlStructureProducer` parses XML and checks the root element, but does not
  run XSD validation. Editors or callers can validate against the packaged XSD
  separately; the migration services validate the compiled normalized structure;
- a single-column FK nests `<relation to="schema.table.column">` inside
  its column; a multi-column FK is a table-level `<relation>` with a
  `columns` attribute and ordered `<to>` children;
- `indexed="true"` on a column is a shortcut that generates a
  single-column index;
- `<option key value>` children carry free key/value pairs (index WITH
  options, event-trigger attributes);
- compile with `XmlStructureProducer` and the flow is identical to the
  quickstart:

```python
from asqueel_migration import XmlStructureProducer

structure = XmlStructureProducer(xml_text).get_json_struct()
# or XmlStructureProducer.from_file(path)
```

The inverse, `struct_to_xml(structure)`, de-normalizes an internal
structure (e.g. introspected from a live DB) back into editable XML.

## 4. dtype reference

Closed set of normalized type codes (PostgreSQL rendering shown; each
dialect writer maps them to its native equivalents):

| dtype | SQL type (PostgreSQL) | dtype | SQL type (PostgreSQL) |
| --- | --- | --- | --- |
| `A` | character varying(size) | `L` | bigint |
| `B` | boolean | `M` | money |
| `C` | character(size) | `N` | numeric(p,s) |
| `D` | date | `O` | bytea |
| `DH` | timestamp without time zone | `R` | real |
| `DHZ` | timestamp with time zone | `T` | text |
| `DT` | interval | `TSV` | tsvector |
| `H` | time without time zone | `VEC` | vector |
| `HZ` | time with time zone | `X`, `Z`, `P` | text |
| `I` | integer | `jsonb` | jsonb |
| `serial` | serial8 | | |

Size conventions: `'0:80'` = varchar(80); `'10'` with a char dtype =
char(10); `'12,2'` = numeric(12,2). Both public producers normalize
legacy varchar forms such as `':80'` and `'5:80'` to `'0:80'`: the
database retains the maximum length, not an application-level minimum.
This also applies when `dtype` is inferred as `A` from `size`. Fixed-char
and numeric sizes are preserved. Producers must use the canonical form
when supplying the normalized contract directly.

## 5. What NOT to emit (attribute cleaning)

The compilers strip attributes whose value is `None`, `False`, `{}`,
`[]`, `''` or `'NO ACTION'`. The format cannot distinguish "not
specified" from "explicitly default", so **never emit default-valued
attributes**: no `notnull: false`, no `on_delete: "NO ACTION"`, no
empty strings. Emit an attribute only when it carries a non-default
value.

## 6. The normalized contract (advanced)

The compiled form — what `get_json_struct()` returns and
`StructureValidator` checks (JSON Schema:
`src/asqueel_migration/schemas/structure-1.0.json`):

- Hierarchy: `root` → `schemas` → `tables` → `columns` / `relations` /
  `constraints` / `indexes`; `extensions` and `event_triggers` at root.
  Every entity carries `entity` and `entity_name`; tables and their leaf
  entities also carry `attributes`. The root and schemas carry child containers.
- FK / UNIQUE / index dict keys and `entity_name` are the structural
  hashes `fk_*` / `cst_*` / `idx_*` (`hashed_name(schema, table,
  columns, obj_type)`). CHECK constraints are keyed by their required
  user-given name.
- `table['attributes']['pkeys']` is the comma-joined physical column
  list; pkey columns carry `notnull='_auto_'`.
- Index `columns` is an ordered map `{name: 'DESC'|None}`; the hash is
  computed on the column names only.
- An explicit readable name lives in `constraint_name` / `index_name`;
  the key stays the hash.

Producers that need full control build this form directly with the
factories exported by the package (`new_structure_root`,
`new_schema_item`, `new_table_item`, `new_column_item`,
`new_relation_item`, `new_constraint_item`, `new_index_item`,
`new_extension_item`, `new_event_trigger_item`) — the compilers
themselves provide reference implementations. A complete ORM-side
producer lives in `tests/support/orm_producer.py`.

## 7. Input ownership and repeated preparation

`SqlMigrator(db, structure=desired)` validates and copies a normalized dictionary
or JSON document. The legacy `migrator.ormStructure = desired` form also copies
its input, but preserves the producer-oriented path without automatically
validating it; use `StructureValidator().validate(desired)` explicitly there
when needed.

The private source snapshot stays intact. Each `prepareMigrationCommands()`
starts from a fresh working copy, re-reads the database, reapplies dialect
filtering and regenerates warnings and SQL. You can safely reuse the original
input across preparations or database targets without losing metadata.

```python
from asqueel_migration import SqlMigrator

# db is a caller-owned database facade; structure is normalized input.
try:
    migrator = SqlMigrator(db, structure=structure)
    migrator.prepareMigrationCommands()
    first_sql = migrator.getChanges()

    migrator.prepareMigrationCommands()  # refresh against the current database
    refreshed_sql = migrator.getChanges()
finally:
    db.closeConnection()
```

The `ormStructure` getter exposes the working copy, not the private source.
Mutating that view or the original input does not update the saved source.
To change the desired schema, reassign `ormStructure` (which clears cached
commands) or construct a new migrator. SQL and warnings repeat when the input,
settings and live database are unchanged; a database change can produce a new
plan. For a reviewed plan that must be checked before execution, use the service
functions in the quickstart.

## 8. Command-line interface

The `asqueel-migrate` CLI currently supports PostgreSQL. It reads one JSON job
from stdin containing `connection`, a **normalized** `structure`, and optional
`options` for `SqlMigrator`. For example, build `job.json` from the quickstart's
compiled structure:

```python
import json
from pathlib import Path

job = {
    "connection": {
        "dbname": "mydb", "host": "localhost",
        "application_schemas": ["library"],
    },
    "structure": structure,
    "options": {"removeDisabled": True},
}
Path("job.json").write_text(json.dumps(job), encoding="utf-8")
```

```bash
asqueel-migrate migrate < job.json          # print proposed SQL
asqueel-migrate migrate --apply < job.json  # calculate and execute SQL
asqueel-migrate check < job.json            # 0: no SQL needed; 1: SQL needed
```

Each command calculates its own migration. The CLI calls `SqlMigrator` directly
and does not accept a reviewed `plan_id` or enforce the service's
`UnsupportedMigration` check. Use `plan_migration` and `apply_migration` when you
need those guarantees. CLI `check` reports whether SQL was generated; it does
not certify structural equality or the absence of unsupported features.

## References

- JSON Schema (normalized contract):
  `src/asqueel_migration/schemas/structure-1.0.json`
- XSD (external XML format):
  `src/asqueel_migration/schemas/sql_model-1.0.xsd`
- Reference producers: `src/asqueel_migration/json_producer.py`,
  `src/asqueel_migration/xml_producer.py`,
  `tests/support/orm_producer.py`

## Dialect support

See the [capability matrix](capabilities.md), [known limits](known_limits.md) and
[development/release checks](maintenance.md). Features marked unreleased are
not present in the published 0.2.1 package.

## PostgreSQL 32-bit generated keys (unreleased)

Declare `{"name": "id", "dtype": "serial4"}` on a table with `"pkey": "id"`.
The equivalent XML is `<column name="id" dtype="serial4"/>`. Both producers
emit the same normalized dtype, accepted by the JSON and XSD contracts.
Use PostgreSQL; other backends reject this declaration before connecting.

`serial4` creates integer keys with automatic sequence defaults. On an existing
SERIAL4 table the matching plan is empty, including populated tables. The legacy
`I` declaration still preserves an existing SERIAL4 column but does not request
an automatically generated key on fresh databases. `serial` retains its 64-bit
meaning. Do not change between these serial declarations to perform a width
conversion: that separate operation is not implemented. See [known limits](known_limits.md).
