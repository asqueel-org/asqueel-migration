# Asqueel Migration

![Asqueel Migration](https://raw.githubusercontent.com/asqueel-org/asqueel-migration/main/assets/branding/asqueel-migration-primary.svg)

**Database schema migration engine** — compare a desired database
structure against a live database and generate (or apply) the SQL
commands that align them.

ORM-agnostic by design: the library never reads your model. You
describe the database in a normalized JSON contract — directly, or
through the friendlier **human JSON** / **XML** external formats — and
the engine does the rest: introspection, diff, DDL generation,
execution.

> Status: **Alpha** — API may change.

## Features

- **Four dialects**: PostgreSQL (primary), SQLite, MySQL, MSSQL — one
  reader/writer/adapter trio per dialect, capability-gated.
- **Two equivalent external formats**: human JSON and XSD-validated
  XML; the same model in either compiles to the identical internal
  structure.
- **Deterministic entity matching**: FK/UNIQUE/index names are
  structural hashes computed from schema + table + columns, so
  renaming never causes spurious diffs.
- **Additive compatibility check**: success means the database can host the
  application without further additive changes, not that both structures are
  identical. Extra database objects are preserved; renames are never inferred.
- **Safe by default**: destructive commands (DROP) are disabled unless
  explicitly enabled; type conversions can be forced and backed up.
- **Minimal runtime dependencies**: `dictdiffer`, plus the DB driver
  of your dialect as an optional extra.

## Install

Install from PyPI:

```bash
pip install "asqueel-migration[postgresql]"
```

Extras: `postgresql` (psycopg 3), `mysql` (PyMySQL), `mssql`
(pymssql), `validation` (jsonschema), `docs`, `dev`, `all`.
SQLite needs no extra (stdlib driver).

## Quickstart

```python
from asqueel_migration import (
    JsonStructureProducer, PgDatabase, SqlMigrator, StructureValidator,
)

model = {
    "db": "mydb",
    "schemas": [
        {"name": "public", "tables": [
            {"name": "author", "pkey": "id", "columns": [
                {"name": "id", "dtype": "serial"},
                {"name": "name", "dtype": "A", "size": "0:120",
                 "notnull": True},
            ]},
        ]},
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

Swap `PgDatabase` for `SqliteDatabase`, `MysqlDatabase` or
`MssqlDatabase` for the other dialects.

## Describing the database

Three input formats, from the friendliest to the most technical:

1. **Human JSON** — readable JSON with names and lists, compiled by
   `JsonStructureProducer` (above).
2. **XML** — the same information validated by the packaged XSD
   (`sql_model-1.0.xsd`), ideal for editors and GUIs; compiled by
   `XmlStructureProducer`. The inverse `struct_to_xml()` turns an
   introspected database back into editable XML.
3. **Normalized JSON** — the internal contract, built directly with
   the `new_*_item` factories (the route an ORM extractor takes).

The complete format reference — columns, dtypes, foreign keys
(including multi-column), constraints, indexes with per-column sort
order and WITH options, extensions, event triggers — is in the
[Producer Guide](https://asqueel-migration.readthedocs.io), also
available as [docs/producer_guide.md](docs/producer_guide.md).

## How it works

```text
your model ──(producer)──► normalized JSON ──┐
                                             ├──► diff ──► SQL commands ──► apply
live database ──(reader)──► normalized JSON ─┘
```

Both sides project to the same normalized JSON (hierarchy:
`root → schemas → tables → columns/relations/constraints/indexes`,
each entity carrying `entity`, `entity_name`, `attributes`). The diff
engine (`dictdiffer`) emits added/changed/removed events; the command
builder turns them into dialect-specific DDL; the executor assembles
and applies it. The JSON Schema of the contract is packaged as
`structure-1.0.json`.

## Execution safety and recovery

`applyChanges()` is atomic by default where the generated DDL supports a
transaction. PostgreSQL, SQLite and SQL Server execute extensions and all
structural changes as one DDL unit. MySQL runs best-effort because its DDL can
implicitly commit; `applyChanges()` records an explicit warning and returns
`best_effort: true`.

Database creation is always a separate manager operation and cannot be part of
the target database transaction. If creating a new database succeeds but its
DDL later fails, the empty or partially initialized database remains, while the
transactional DDL unit is rolled back where supported.

Every failure stops execution immediately and raises
`MigrationExecutionError`. Its `phase`, `rolled_back` and
`partial_state_possible` attributes describe the outcome. The same invocation
does not try to repair or reanalyse the database. Run the migration again: it
re-introspects the current database and generates only the residual additive
changes. Objects already created are retained; no DROP or rename is inferred.

| Dialect | Default DDL mode | Failure in the DDL unit |
| --- | --- | --- |
| PostgreSQL | One transaction | Rolled back |
| SQLite | One transaction on the attached connection | Rolled back on an ordinary execution error; crash-level atomicity across multiple attached files depends on SQLite journal configuration |
| SQL Server | One transaction for the DDL generated by this library | Rolled back |
| MySQL | Best-effort, explicit warning | Earlier statements may remain committed |

## Local development editor

The optional HTTP/MCP editor is a **local development tool** and requires
Python 3.11 or newer (the core library continues to support Python 3.10). It is
not a remotely deployable administration service and has no user-management
system. Start it on the loopback interface (the CLI default):

```bash
pip install -e ".[app,postgresql]"
kajenn serve application=src/asqueel_migration/app.py:EditorApp \
  --host 127.0.0.1 --port 8000
```

The `app` extra uses Kajenn, the successor of genro-asgi. The editor is
verified against the published Kajenn 0.1.0 and development commit
`5b460b58f4bdb3a32ad94eecbf99a2e4510fe8fa`, with Bag/Builders 0.27.0,
TYTX 0.16.0, Routes 0.30.0 and Storage 0.8.1. Kajenn is constrained to the
0.1 series while its API evolves; transitive dependencies are not locked.
Run `tests/test_editor_app.py` before advancing that range. For local Kajenn
development, install the desired checkout explicitly after this extra
(`python -m pip install -e /path/to/kajenn`). The core and database CLI do not
depend on Kajenn.

The application also checks the peer address and rejects non-loopback clients,
even if it is accidentally bound to another interface. `/introspect`,
`/migrate` and `/apply` accept POST requests with an `application/json` body
only. Query parameters are rejected so database passwords never enter URLs or
access logs, and operation errors redact the supplied password.

`/migrate` is the dry-run; `/apply` is the separate, deliberate execution
operation and remains REST-only. The editor follows additive compatibility:
database-only objects are retained, with no inferred rename or implicit DROP.

The XML is trusted developer input. Native SQL fields such as `sql_type`,
`sqldefault`, `extra_sql` and CHECK expressions can intentionally contain SQL;
do not open the editor to untrusted files or expose it through a network proxy.

## Modules

| Module | Responsibility |
| --- | --- |
| `structures.py` | Contract constants, entity factories, name hashing |
| `validation.py` | `StructureValidator` — JSON Schema + semantic checks |
| `json_producer.py` | Human JSON → normalized JSON |
| `xml_producer.py` | XML → normalized JSON, and back (`struct_to_xml`) |
| `editor_service.py` | DB ↔ XML round-trip service for editors |
| `diff_engine.py` | Structure comparison → typed events |
| `command_builder.py` | Events → SQL command fragments |
| `executor.py` | SQL assembly, execution, backup verification |
| `migrator.py` | `SqlMigrator` — the orchestrator |
| `database.py` | Abstract `Database` / adapter interfaces |
| `readers/` | Per-dialect introspection (live DB → normalized JSON) |
| `writers/` | Per-dialect DDL generation |
| `adapters/` | Concrete `Database`/adapter pairs per dialect |

## Documentation

Full documentation on
[Read the Docs](https://asqueel-migration.readthedocs.io).
Design notes and milestones live in [roadmap/](roadmap/).

## License

Apache License 2.0 — Copyright Softwell S.r.l.
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
