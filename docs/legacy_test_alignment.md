# Legacy migration test alignment

Audit date: 2026-09-29. Reference: `genropy/genropy` develop commit
`9bdf27a4c2`, file `gnrpy/tests/sql/test_gnrsqlmigration.py`.

The reference contains 84 distinct test methods across eight base/helper
classes. The legacy PostgreSQL adapter subclasses run inherited cases more
than once; this package runs them through its production PostgreSQL adapter.
Method counts below are coverage mappings, not pytest execution counts.

| Legacy group | Methods | Package coverage |
| --- | ---: | --- |
| `BaseGnrSqlMigration` | 52 | `tests/test_migration_pg.py`, including the two varchar-widening oracles from genropy/genropy#1054 |
| Default-exception, force, backup and extension groups | 19 | `tests/test_migration_modes_pg.py` |
| `GeneralSqlMigrationCode` | 5 | Four factory/constraint regressions in `tests/test_regressions.py`; one intentional exclusion below |
| `TestSqlCommandsForTable` | 3 | Issue #10 / PR #12: `tests/test_executor_column_order.py`, porting genropy/genropy#1194 |
| `ToDo` | 5 | `tests/test_todo_features.py`, explicitly skipped until the corresponding features exist |

The one excluded case, `test_empty_dict_structures_not_reextracted`, tests
`jsonModelWithoutMeta()`, a legacy Bag/UI helper deliberately absent from this
ORM-independent library. It is not a missing migration-engine regression.

## New regression coverage

- PR #12 preserves added/changed columns before a primary-key rebuild. It
  checks dialect-specific command assembly and live PostgreSQL apply/re-diff
  with existing rows and a newly added key column.
- The two upstream widening tests retain their original SQL expectations:
  varchar(40) to varchar(255), and a varchar primary key from 80 to 306.
- `tests/test_size_normalization.py` exercises both public producers rather
  than only the test ORM producer: `:N`, `0:N` and `5:N` must converge to the
  same physical varchar size. Live PostgreSQL checks preserve existing data
  and produce no residual DDL after creation or widening. Fixed-char and
  numeric sizes remain unchanged; caller JSON is not mutated.

## Intentional adaptations

The fixtures replace the legacy ORM with a small producer that injects the
normalized structure. Identifier quoting in older index oracles reflects the
package's physical-name fixes (#8/#9). Legacy error handling is represented
by library exceptions, not process exits. Additional SQLite, MySQL, MSSQL,
public-producer, execution-atomicity and editor suites remain package-specific
and are not removed to match the legacy test count.
