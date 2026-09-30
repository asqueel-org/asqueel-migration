# Producer Guide — describing your database

**Contract**: `format_version = "1.0"`

asqueel-migration is ORM-agnostic: it never reads your model. You
describe the desired database in one of three input formats, the
library compares it against the live database and generates (or
applies) the realignment SQL.

The three doors, from the friendliest to the most technical:

1. **Human JSON** — a readable JSON document with names and lists
   (no hashes). Compiled by `JsonStructureProducer`.
2. **XML** — the same information in XML, validated by the packaged
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
    JsonStructureProducer, PgDatabase, SqlMigrator, StructureValidator,
)

model = {
    "db": "mydb",
    "schemas": [
        {
            "name": "public",
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
                         "related_schema": "public",
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
                application_schemas=["public"])
migrator = SqlMigrator(db)
migrator.ormStructure = StructureValidator().validate(structure)
migrator.prepareMigrationCommands()
print(migrator.getChanges())        # review the SQL...
# migrator.applyChanges()           # ...or apply it
```

`JsonStructureProducer` also accepts a JSON string or a file
(`JsonStructureProducer.from_file(path)`). Swap `PgDatabase` for
`SqliteDatabase`, `MysqlDatabase` or `MssqlDatabase` for the other
dialects (each needs its driver extra — see the README).

`StructureValidator().validate()` checks the compiled structure against
the packaged JSON Schema (with the `validation` extra installed) plus
the semantic rules a schema cannot express.

### Applying safely and recovering from errors

`migrator.applyChanges()` uses one transaction for the complete DDL unit on
PostgreSQL, SQLite and SQL Server. MySQL is explicitly best-effort because DDL
statements can cause implicit commits. The return value reports `atomic`,
`best_effort` and the completed phases; non-atomic execution also adds a
warning to `migrator.warnings`.

`CREATE DATABASE`, when required, is executed separately through the manager
connection. It therefore remains present if the following DDL unit fails.

At the first failure execution terminates with `MigrationExecutionError`:

```python
from asqueel_migration import MigrationExecutionError

try:
    result = migrator.applyChanges()
except MigrationExecutionError as error:
    print(error.phase)
    print(error.rolled_back)
    print(error.partial_state_possible)
```

There is no automatic retry or reanalysis in the failing invocation. After
fixing the cause, invoke the migration again. A new run introspects the actual
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

### Local editor trust boundary

The optional editor in `asqueel_migration.app` requires Python 3.11 or newer
and is intended only for a developer working on their own machine. The core
library still supports Python 3.10. Run the editor on `127.0.0.1`; the
application also rejects ASGI clients whose peer address is not loopback. It is
not a multi-user database administration service and must not be published
through a reverse proxy.

All REST operations use POST `application/json` bodies. The application rejects
query strings, so connection passwords do not enter URLs or access logs, and
redacts the submitted password from operation errors. `migrate` remains a
dry-run and `apply` remains a separate REST-only operation.

The editor applies the same additive contract as the library: objects present
only in the database are retained. Edited XML is trusted developer input;
fields such as `sql_type`, `sqldefault`, `extra_sql` and CHECK clauses contain
intentional native SQL and must never be accepted from an untrusted source.

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
 "related_schema": "public", "related_table": "author",
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
index from the model still does not automatically drop it.

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

The same model, XSD-validated (`src/asqueel_migration/schemas/
sql_model-1.0.xsd`, namespace `urn:genro:sql-model:1.0`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<db xmlns="urn:genro:sql-model:1.0" name="mydb">
  <schema name="public">
    <table name="author" pkey="id">
      <column name="id" dtype="serial"/>
      <column name="name" dtype="A" size="0:120" notnull="true"/>
    </table>
    <table name="recipe" pkey="id">
      <column name="id" dtype="serial"/>
      <column name="title" dtype="A" size="0:80" notnull="true"/>
      <column name="author_id" dtype="L">
        <relation to="public.author.id" on_delete="CASCADE"/>
      </column>
      <!-- multi-column FK: table-level, ordered <to> children -->
      <relation columns="pa,pb" name="fk_pair">
        <to schema="s" table="parent" column="a"/>
        <to schema="s" table="parent" column="b"/>
      </relation>
      <constraint type="UNIQUE" columns="title,author_id"/>
      <constraint type="CHECK" name="ck_recipe_title"
                  check_clause="(char_length(title) &gt; 0)"/>
      <index columns="title"/>
      <index name="idx_recent" unique="true">
        <column name="pa"/>
        <column name="created" sort="DESC"/>
        <option key="fillfactor" value="70"/>
      </index>
    </table>
  </schema>
  <extension name="unaccent"/>
  <event_trigger name="audit_ddl">
    <option key="event" value="ddl_command_end"/>
  </event_trigger>
</db>
```

XML-specific notes:

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
char(10); `'12,2'` = numeric(12,2).

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
  Every entity carries `entity`, `entity_name`, `attributes`.
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
themselves are ~150-line reference producers. A complete ORM-side
producer lives in `tests/support/orm_producer.py`.

## 7. Re-injection rule

Command handlers mark transient state on the injected structure.
**Build and inject a fresh structure before every**
`prepareMigrationCommands()` — never reuse a structure that already
went through a migration run.

## References

- JSON Schema (normalized contract):
  `src/asqueel_migration/schemas/structure-1.0.json`
- XSD (external XML format):
  `src/asqueel_migration/schemas/sql_model-1.0.xsd`
- Reference producers: `src/asqueel_migration/json_producer.py`,
  `src/asqueel_migration/xml_producer.py`,
  `tests/support/orm_producer.py`
